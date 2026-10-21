---
name: orchestrate-dealer
description: La sesión principal como orchestrator que reparte el trabajo a subagentes de contexto limpio, para trabajar horas sin `/clear`. Usar en toda tarea de más de un paso (tarea del roadmap, tanda de arreglos, ronda de pruebas) y cuando el contexto de la sesión pase de ~150k.
---

# orchestrate-dealer (`QA-121`)

La sesión principal es el **orchestrator**: guarda el plan, las decisiones y el hilo con la usuaria, y reparte cada
trozo de trabajo a un subagente que empieza con el contexto vacío. Cada reparto es un `/clear` automático: la
principal solo recibe un resumen corto y crece despacio. Si aun así llega al tope, la compactación automática
(`CLAUDE_CODE_AUTO_COMPACT_WINDOW`, 200k), los puntos de `/clear` (`QA-122`) y el gancho de `recuperar.py --estado` son la red.

## Qué se queda en la principal y qué se reparte

| Orchestrator (principal) | Subagente |
|---|---|
| Hablar con la usuaria, preguntar, presentar | Leer código, docs largos, logs, capturas y `snapshot` de Playwright |
| Partir la tarea en trozos y escribir cada encargo | Implementar, depurar, pasar tests |
| Decidir (diseño, qué se arregla, qué se apunta) | Jugar una tanda de la ronda de pruebas |
| Revisar lo que vuelve: `git log`/`git diff --stat`, nunca el diff entero salvo duda | Commit y push de su trabajo, con la bitácora en el mismo commit |
| `/code-review`, `/opt-tokens`, `/retro`, PR y fusión | — |
| Analizar una tanda (medidas, causas, RAG): `/opt-ai` en el flujo del PR, no la ronda (`QA-142`) | — |

Una lectura de más de ~200 líneas o una salida larga en la principal es un trozo que no se repartió.

## Pasos

1. **Partir.** Con el `selector` ya aplicado, divide la tarea en trozos que un subagente cierre de una vez: un
   arreglo, un sistema, una tanda de 3-5 comprobaciones de la ronda. La tanda de juego se mide también en llamadas:
   como mucho ~60 por subagente; al llegar, guarda el estado con `escenario.sh guardar` y el siguiente lo carga
   (`QA-147`). Cada trozo, con su criterio de hecho
   comprobable (un test en verde, un P-número comprobado o abierto, un commit subido) y lo que le bloquea. La
   **frontera** son los trozos que nada pendiente bloquea: salen a la vez (ver Reglas).
2. **Repartir.** Un subagente por trozo con `Agent`, en primer plano (`run_in_background: false`) cuando el
   siguiente trozo depende de él. Modelo y esfuerzo por la escalera del `selector` (`QA-118`): `sonnet` para
   implementar y jugar, `opus` para depurar algo no obvio. El encargo lleva **punteros**, no copias: dónde está lo que
   necesita (fila de la bitácora, P-número del registro, fila de la matriz, commit, archivo y función del
   `docs/mapa-agente.md`), nunca el texto pegado. Si el encargo escribe en la partida (scripts de QA, escenarios), pruébalo con
   `escenario.sh probar` contra una instantánea (`QA-153`). Con esta forma:

   ```text
   Trabajas en Tarkor, rama <rama>. Lee docs/registros/traspaso.md (tu fila) y, si tocas código,
   docs/mapa-agente.md. Sigue CLAUDE.md (commit + push con la bitácora en el mismo commit).
   Encargo: <qué, en una o dos frases>.
   Hecho cuando: <criterio comprobable>.
   No hagas: <lo que es de otro trozo o pide decisión de la usuaria>.
   Si cambias una función o un campo, busca (grep) a todos los que lo usan y ajústalos o dilo en FALTA.
   Si escribes estado de la partida (scripts de QA, escenarios), pasa por las funciones del juego que aplican esas reglas
   (docs/mapa-agente.md dice cuáles), sin reescribirlas a mano.
   Si algo pide decidir a la usuaria, para y devuélvelo como pregunta.
   Devuelve como mucho 15 líneas:
   HECHO: … · HALLADO: P-números con una línea cada uno · HERRAMIENTAS: fallos de orden.sh, escenario.sh o del driver · COMMIT: <sha> · FALTA: … · PREGUNTAS: …
   ```

3. **Revisar lo que vuelve.** Comprueba el commit (`git fetch` + `git log -1 --stat`) y que el criterio de hecho
   se cumple. Si no cierra, el reintento sube un peldaño; dos fallos, se para y se le cuenta a la usuaria.
   De cada rama de subagente con worktree, **antes de fusionarla**, un `/code-review` corto de su diff hecho por un
   subagente revisor que devuelve solo los hallazgos; no se fusiona hasta arreglarlos (`QA-126`, `QA-131`: la tanda
   P223-P237 fusionó 8 ramas sin esa revisión y el `/code-review` final halló 17). El encargo del revisor le pide
   comparar el diff con el **contrato**: el doc que lo describe y los llamadores reales fuera de la rama (grep en la
   rama de trabajo), no solo el diff (`QA-137`: en `opt-ai` las revisiones cortas no vieron tres fallos entre ramas,
   `medir.py` frente al backend, las tareas de `proyecto.md` y `rag-eval` distinto del juego).
   Si la rama escribe estado de la partida, el revisor mira también que pase por las funciones del juego que aplican
   esas reglas y no las rehaga a mano (`QA-151`: `darReino.ts` duplicaba el Ayuntamiento y se saltaba cupos y topes).
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
  subagente de fusión solo para conflictos que no sean del registro de hallazgos (el script resuelve ese).
- **Registros compartidos, solo la principal** (`QA-132`): con subagentes en paralelo, ninguno toca la bitácora ni
  `docs/registros/pruebas-0.3-hallazgos.md` (ni otro registro compartido); devuelven sus P-números en `HALLADO` y la
  principal los apunta. Escribirlos en paralelo da conflictos al fusionar.
- **Lo que nombra archivos de una rama, tras fusionarla** (`QA-138`): `docs/mapa-agente.md` y los docs que enlazan
  archivos nuevos de un worktree se escriben en la principal después de fusionar esa rama; antes, el pre-push rechaza
  las rutas que aún no existen.
- **Sin worktree, uno a la vez en la misma rama**: dos subagentes que hacen commit en la rama de trabajo chocan
  en la bitácora. En paralelo, además, todo lo que no escribe (buscar, leer, medir).
- **Rondas de pruebas, en un subagente `sonnet` y en serie** (`QA-124`: la ronda `QA-105` la jugó la principal con
  Opus, 1.150 órdenes de Bash): la principal no lanza `orden.sh`; reparte tandas y apunta lo que vuelve. Comparten
  el navegador y la base de juego. Cada tanda deja la partida en un
  estado que la siguiente pueda retomar y lo dice en `FALTA` (pantalla, partida, día).
- **El subagente no habla con la usuaria**: lo que necesite de ella vuelve como `PREGUNTAS`.
- **Medir**: `/opt-tokens` antes de cada PR compara el contexto medio por llamada, las compactaciones y el reparto
  `POR MODELO` con la sesión anterior; si no bajan, el reparto se está quedando en la principal.
