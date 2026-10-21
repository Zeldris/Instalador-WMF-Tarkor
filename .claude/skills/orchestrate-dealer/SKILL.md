---
name: orchestrate-dealer
description: La sesión principal como orchestrator que reparte el trabajo a subagentes de contexto limpio, para trabajar horas sin `/clear`. Usar en toda tarea de más de un paso (tarea del plan, tanda de arreglos, una fase entera) y cuando el contexto de la sesión pase de ~150k.
---

# orchestrate-dealer (`QA-121`)

La sesión principal es el **orchestrator**: guarda el plan, las decisiones y el hilo con la usuaria, y reparte cada
trozo de trabajo a un subagente que empieza con el contexto vacío. Cada reparto es un `/clear` automático: la
principal solo recibe un resumen corto y crece despacio. Si aun así llega al tope, la compactación automática
(`CLAUDE_CODE_AUTO_COMPACT_WINDOW`, 200k), los puntos de `/clear` (`QA-122`) y el gancho de `recuperar.py --estado` son la red.

## Qué se queda en la principal y qué se reparte

| Orchestrator (principal) | Subagente |
|---|---|
| Hablar con la usuaria, preguntar, presentar | Leer código, docs largos, logs de la CI y capturas de las e2e |
| Partir la tarea en trozos y escribir cada encargo | Implementar, depurar, pasar tests |
| Decidir (diseño, qué se arregla, qué se apunta) | Pasar las e2e o una prueba con el motor real |
| Revisar lo que vuelve: `git log`/`git diff --stat`, nunca el diff entero salvo duda | Commit y push de su trabajo, con la bitácora en el mismo commit |
| `/code-review`, `/opt-tokens`, `/retro`, PR y fusión | — |
| Analizar medidas del motor (`/opt-ai` en el flujo del PR, `QA-142`) | — |

Una lectura de más de ~200 líneas o una salida larga en la principal es un trozo que no se repartió.

## Pasos

1. **Partir.** Con el `selector` ya aplicado, divide la tarea en trozos que un subagente cierre de una vez: un
   arreglo, un módulo del núcleo, una pantalla del asistente, un comando de Tauri. Cada trozo, con su criterio de
   hecho comprobable (un test en verde, la CI de Windows en verde, un commit subido) y lo que le bloquea. La
   **frontera** son los trozos que nada pendiente bloquea: salen a la vez (ver Reglas).
2. **Repartir.** Un subagente por trozo con `Agent`, en primer plano (`run_in_background: false`) cuando el
   siguiente trozo depende de él. Modelo y esfuerzo por la escalera del `selector` (`QA-118`): `sonnet` para
   implementar, `opus` para depurar algo no obvio o que toca procesos en Linux y Windows. El encargo lleva
   **punteros**, no copias: dónde está lo que necesita (fila de la bitácora, tarea del plan, documento de `docs/`,
   commit, archivo y función), nunca el texto pegado. Con esta forma:

   ```text
   Trabajas en el instalador de Tarkor, rama <rama>. Lee docs/registros/traspaso.md (tu fila), la tarea
   del plan y, si tocas código, REVIEW.md. Sigue CLAUDE.md (commit + push con la bitácora en el mismo commit).
   Encargo: <qué, en una o dos frases>.
   Hecho cuando: <criterio comprobable>.
   No hagas: <lo que es de otro trozo o pide decisión de la usuaria>.
   Si cambias una función o un campo, busca (grep) a todos los que lo usan y ajústalos o dilo en FALTA.
   Si tocas procesos, rutas o permisos, escríbelo para Linux y Windows y compila el destino de Windows
   (cargo check --target x86_64-pc-windows-gnu).
   Si algo pide decidir a la usuaria, para y devuélvelo como pregunta.
   Devuelve como mucho 15 líneas:
   HECHO: … · HALLADO: fallos vistos, una línea cada uno · HERRAMIENTAS: fallos de tools/qa, los ganchos o la CI · COMMIT: <sha> · FALTA: … · PREGUNTAS: …
   ```

3. **Revisar lo que vuelve.** Comprueba el commit (`git fetch` + `git log -1 --stat`) y que el criterio de hecho
   se cumple. Si no cierra, el reintento sube un peldaño; dos fallos, se para y se le cuenta a la usuaria.
   De cada rama de subagente con worktree, **antes de fusionarla**, un `/code-review` corto de su diff hecho por un
   subagente revisor que devuelve solo los hallazgos; no se fusiona hasta arreglarlos (`QA-126`, `QA-131`: en el
   juego, una tanda fusionó 8 ramas sin esa revisión y el `/code-review` final halló 17). El encargo del revisor le pide
   comparar el diff con el **contrato**: el doc que lo describe y los llamadores reales fuera de la rama (grep en la
   rama de trabajo), no solo el diff (`QA-137`: en el juego, las revisiones cortas no vieron tres fallos entre ramas).
   Aquí el contrato suele estar entre el núcleo y el asistente: lo que decide el núcleo llega por su comando de Tauri
   y el asistente no lo recalcula (`REVIEW.md`).
   La principal apunta lo que vuelve: lo de `HALLADO` en la bitácora o como tarea del
   [plan](../../../docs/05-plan-de-trabajo.md), y lo de `HERRAMIENTAS` como tarea `FLU-n` (`QA-133`).
   Las `PREGUNTAS` van a la usuaria tal cual, con la respuesta que recomiendas.
4. **Seguir.** Siguiente trozo. A la usuaria, una línea por trozo cerrado; el detalle está en la bitácora.

## Reglas

- **Arreglos de código de la frontera, en paralelo** (idea de `implement-spec` de Matt Pocock): cada subagente con
  `isolation: "worktree"`, en `run_in_background`, hace commit en su worktree en cada punto estable (`WIP:` si
  aún falla; `QA-139`: un reinicio perdió dos subagentes con todo sin commit) sin tocar la bitácora ni subir, y
  devuelve su rama. La principal los hace revisar (paso 3), los fusiona uno a uno con
  `tools/qa/fusionar.sh <rama> "<msg>" --revisada` (merge, tests del paquete tocado), escribe la bitácora y sube. Un
  subagente de fusión solo para conflictos que el script no resuelva.
- **Registros compartidos, solo la principal** (`QA-132`): con subagentes en paralelo, ninguno toca la bitácora ni
  otro registro compartido (el plan, `docs/registros/`); devuelven lo suyo en `HALLADO` y la principal lo apunta. Escribirlos en paralelo da conflictos al fusionar.
- **Lo que nombra archivos de una rama, tras fusionarla** (`QA-138`): los docs que enlazan
  archivos nuevos de un worktree se escriben en la principal después de fusionar esa rama; antes, el pre-push rechaza
  las rutas que aún no existen.
- **Sin worktree, uno a la vez en la misma rama**: dos subagentes que hacen commit en la rama de trabajo chocan
  en la bitácora. En paralelo, además, todo lo que no escribe (buscar, leer, medir).
- **Pruebas largas, en un subagente `sonnet` y en serie** (`QA-124`): las e2e (`app/e2e`, xvfb) y las pruebas con el
  motor real (ejemplo `motor`, descargas de varios GB) comparten pantalla virtual, puertos y carpeta de datos; la
  principal no las lanza, reparte y apunta lo que vuelve.
- **El subagente no habla con la usuaria**: lo que necesite de ella vuelve como `PREGUNTAS`.
- **Medir**: `/opt-tokens` antes de cada PR compara el contexto medio por llamada, las compactaciones y el reparto
  `POR MODELO` con la sesión anterior; si no bajan, el reparto se está quedando en la principal.
