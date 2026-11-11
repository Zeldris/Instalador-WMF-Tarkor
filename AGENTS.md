<!-- galivelop-workflow v0.5.1 -->
# Instalador-WMF-Tarkor — instrucciones para agentes

Este proyecto se trabaja por relevos: una sesión puede acabarse en cualquier momento (tokens, contenedor, cambio de
cuenta) y la siguiente tiene que seguir **sin perder nada y sin preguntar por dónde iba**. Todo lo de este archivo
existe para eso. El flujo es Galivelop-workflow v0.5.1; sus scripts están en `.claude/gw/scripts/`, sus skills
en `.claude/skills/` y su configuración en `.claude/gw.json` (solo la lee `.claude/gw/scripts/config.py`).

## Al empezar cualquier sesión

1. La bitácora, `docs/records/traspaso.md`: rama, tarea en curso, qué falta y siguiente paso. Basta la fila de tu
   rama que da el gancho de inicio (`recover.py --state`); «Siguiente paso» solo si la fila no lo da, y
   siempre «Decisiones de la usuaria que bloquean algo» (es corta).
2. `git fetch origin <rama>` y comprueba que el último commit coincide con lo que dice la bitácora.
3. Comprueba que el check está en verde antes de tocar nada: las órdenes de `check` en `.claude/gw.json`.
4. Sigue por el **siguiente paso** de la bitácora, salvo que la usuaria pida otra cosa.
5. Al empezar cada tarea, trae la rama protegida: `git fetch origin main` y, si trae commits,
   `git merge origin/main` (merge, nunca rebase: las ramas están subidas). Si el conflicto toca la
   misma lógica por los dos lados, se para y se consulta a la usuaria.
6. **La sesión se abre con el repo como carpeta de trabajo.** Abierta en otra (una que contiene varios repos, la
   carpeta personal), no carga `.claude/settings.json`: ni el tope de compactación, ni el gancho de inicio, ni el que
   vigila la subida a la rama protegida. Si pasa, dilo a la usuaria para que la reabra desde el repo; mientras tanto,
   `git config core.hooksPath .githooks` antes del primer commit y, antes de subir a `main` o de crear
   o fusionar un pull request, comprueba a mano lo que comprobaría ese gancho: la marca de revisión del mismo commit y
   el CI en verde.

## Relevos: commit y push constantes

Cada sesión puede correr en un contenedor temporal: **lo que no está subido no existe** para la siguiente.

- Commit + push en cada punto estable (check en verde). **Nunca más de 30-45 minutos de trabajo sin subir.** Las
  tareas grandes se parten en pasos pequeños con su propio commit.
- **La bitácora se actualiza en el mismo commit** que el trabajo que describe, no al final de la sesión; su fila,
  con `python3 .claude/gw/scripts/handoff.py set-row`.
- **El estado vive en los archivos, no en la conversación**: el plan dice qué está implementado y la bitácora qué se
  está haciendo. Una tarea a medias dice qué está hecho y qué falta.
- Si hay que parar con algo a medias o en rojo: commit igualmente con `WIP:` al principio del mensaje y, en la
  bitácora, qué falla y por qué. Nunca dejar trabajo solo en local.
- Push a la rama de trabajo (`git push -u origin <rama>`); si falla por red, reintentar con espera 2, 4, 8 y 16 s.
  El push y el check largo se lanzan en segundo plano y se espera su aviso, sin bucles de espera.
- **Tras una llamada interrumpida o rechazada, `git status` y `git diff` antes de repetirla**: el cambio puede
  haberse guardado, o incluso subido, y repetirlo lo duplica.
- Si la usuaria dice que se para, se para: se sube lo que haya, se deja la bitácora al día y no se sigue con nada más.
- **Al cerrar cada tarea o PR** (y cada fase), con todo subido y la bitácora al día, se pide a la usuaria un `/clear` en
  una línea, con el porqué: el contexto largo es casi todo el gasto, y la bitácora basta para retomar.
- **Al cerrar cada bloque o fase, mira el CI de la última subida.** Un CI que no arranca (sin cuota, sin runners)
  cuenta como rojo: se dice a la usuaria y no se da nada por comprobado en el CI. Entonces vale el check pasado en
  local sobre el mismo commit (el de `.githooks/pre-push`) **solo si la usuaria lo confirma**, y se dice y se apunta en
  la bitácora como «comprobado solo en local». Un CI que arrancó y falló nunca se sustituye así.

## Comprobar

- **El check del proyecto:** las órdenes de `check` en `.claude/gw.json`. `.githooks/pre-push` lo corre sobre el commit que se sube, y el CI
  (`.github/workflows/check.yml`) en cada push fuera de `main` y en cada pull request; las pruebas propias del
  instalador (`npm test`, el build, `cargo test` en Linux y Windows) van en `.github/workflows/app.yml`.
- **Antes de subir, pásalo con `bash .claude/gw/scripts/check.sh`**: corre el check y, si sale en verde, lo apunta; el
  `pre-push` no lo repite sobre el mismo árbol (`GW_CHECK_CACHE=0` lo desactiva).
- **Lo comprobable lo hace un script**, no un agente: las skills y guías solo deciden lo que exige criterio. Si una
  regla se sigue rompiendo, se convierte en una comprobación.
- **Lo que depende de una máquina concreta no se da por probado con tests** (otro sistema operativo, un dispositivo,
  el equipo de la usuaria): se apunta como pendiente en el plan, con quién lo comprueba y dónde.
- Un test nuevo tiene que fallar sin su arreglo: `bash .claude/gw/scripts/red-without-fix.sh "<orden del test>"
  <archivo-del-arreglo>...`.
- Un test que espera un fallo comprueba **el motivo** (el mensaje o la causa), no solo el código de salida: si no,
  pasa también cuando falla por otra razón.
- `python3 .claude/gw/scripts/doctor.py` dice si el flujo está bien montado, con la orden que arregla cada problema.

## Mensajes de commit

- Primera línea: qué cambia, en el idioma del proyecto, con los identificadores de las tareas tocadas. Con
  `commitFormat: "conventional"` en `.claude/gw.json`, en la forma `tipo(id): …` (`feat`, `fix`, `docs`…), y con
  `commitRefs: true`, un trailer `Refs: <id>` en el último párrafo, antes de `Siguiente:`; lo comprueba `commit-msg`.
- Cuerpo: qué se hizo, qué queda de esa tarea si no está cerrada, y estado del check.
- **Última línea: `Siguiente: <próximo paso concreto>`**, en el mismo bloque final que las líneas de atribución, si las hay.
- Con `agentSignatures: false` en `.claude/gw.json`, el commit **no lleva firmas del agente** (ni `Co-Authored-By` de
  Claude, ni `Claude-Session`, ni «Generated with Claude Code», ni enlaces de sesión) y el gancho `commit-msg` rechaza
  el mensaje que las traiga.

## Ramas y `main`

- Se trabaja en la rama que indique la bitácora (o la que asigne la sesión, que se apunta en la bitácora nada más
  empezar).
- **Cada sesión, su propia rama**: dos sesiones a la vez nunca suben a la misma rama. Si la rama de la bitácora ya la
  usa otra sesión, crea `claude/<tema>` desde ella y escribe solo en tu parte de la bitácora. Lo tuyo vuelve por
  `git merge` antes de ir a `main`.
- Merge, nunca rebase: las ramas están subidas.
- **A `main` solo con confirmación de la usuaria**, y se apunta en la bitácora. Según `pushToProtected`
  de `.claude/gw.json`, se sube directo (`direct`: `.githooks/pre-push` pide la marca de revisión) o por pull request
  (`pr`: un gancho de Claude Code pide la marca antes de crearlo o fusionarlo; un push directo la sigue pidiendo).
- **Se fusiona solo con el CI en verde**, también cuando la usuaria dice «fusiona directamente»: eso quita esperar a
  más revisiones, nunca el CI ni la retro presentada a la usuaria. Si el CI no arranca, vale el check en local de
  «Relevos» con la confirmación de la usuaria: se sube directo (el `pre-push` corre el check) o, para un pull
  request, `python3 .claude/gw/scripts/ci-local.py --record` corre el CI en local y lo apunta; con esa línea verde
  subida, el gancho deja fusionar.
- La rama de un subagente vuelve con `bash .claude/gw/scripts/merge-branch.sh <rama> "<mensaje>"`, que corre el check
  y los tests relacionados, y limpia su worktree.

## Antes de ir a `main`: tres fases

Nunca sobre trabajo ya fusionado.

1. **Código:** `git fetch origin main` y revisión del diff contra `origin/main` con
   todos los hallazgos (en Claude Code, `/code-review --max-findings all`), con el criterio de `REVIEW.md`. Arreglos
   con commit y subidos: lo grave o medio y lo que el propio arreglo rompe; lo leve se apunta como pendiente en la
   bitácora y no vuelve a revisarse en ese PR. Solo el código necesita revisión: lo que casa con `content` de `.claude/gw.json` es
   contenido.
2. **Entorno:** la skill `gw-opt-tokens` y luego `retro` (más `gw-opt-ai` si hubo medidas con un modelo de IA local). Sus
   propuestas se **presentan a la usuaria**; lo que confirme se aplica en la rama. Una retro escrita sin presentarla no
   vale. Si la usuaria pidió ir a `main` y no está para decidir la retro, se deja todo listo (retro con
   `**Estado:** pendiente`, check en verde sobre la fusión con `main`, descripción del pull request) y
   se para antes de `reviewed.sh`: su confirmación de la retro es el único paso que falta; la decisión no se escribe
   por ella.
3. **Cierre:** si la fase 2 trajo código, revisión solo de esos commits y sus arreglos; luego
   `bash .claude/gw/scripts/reviewed.sh` (escribe la marca de revisión, `docs/records/reviewed.txt`, y hace su commit) y
   `git push`; para un pull request, su descripción con la skill `pr`. Solo entonces se sube a `main`
   o se crea el pull request. Sin la marca del mismo commit, los ganchos lo rechazan.

## Subagentes

**Reparto a subagentes autorizado:** el trabajo de más de un paso se reparte a subagentes de contexto limpio con la
skill `gw-orchestrate-dealer` (y los modelos que elija la skill `gw-selector`) sin preguntar cada vez; la sesión principal
planea, decide y revisa. Esta línea es la autorización que piden las instrucciones del propio agente.

- Cada subagente recibe un encargo: objetivo, rutas, restricciones, el check que debe pasar y qué tiene que devolver.
- Otros repositorios se leen con un subagente que devuelve un resumen con rutas; desde aquí nunca se modifican. Lo
  que se les encarga lleva en su casilla del plan dónde vive el encargo (rama o issue de ese repo) y su estado.

## Reglas del proyecto

<!-- Las rellena el proyecto: stack, cómo se arranca, lo que nunca se hace, reglas del dominio, dónde está cada cosa.
     Breve; una regla comprobable se convierte en un script. -->

Instalador de escritorio de Tarkor (Tauri v2, Windows y Linux). El flujo viene del repo del juego
(`World-Maker-Fantasy`): los `QA-xx` que se citan son de su historial.

- Instalar: `bash tools/dev/instalar-entorno.sh`. Código, cómo se arranca y cómo se prueba: [`app/README.md`](app/README.md).
- **Tareas:** `INS-n` (el [plan](docs/05-plan-de-trabajo.md)) y `FLU-n` (el flujo de trabajo). Ninguna tarea sin fase:
  toda tarea nueva entra en una fase del plan con su id; al cerrarla, su casilla `- [x]` con fecha y qué se hizo.
- **Dónde está cada cosa:** diseño en `docs/01`…`docs/13` (índice en el [README](README.md)); skills y modelos en
  [`docs/runbooks/skills-y-modelos.md`](docs/runbooks/skills-y-modelos.md).
- **Diseño:** una ronda de diseño (una pantalla del asistente, un perfil, cómo se descarga o se actualiza algo) se
  contrasta con Steam, itch.io, Heroic, el asistente de LM Studio y el instalador de Ollama, citando de cuál sale cada
  propuesta. Lo decidido va a su documento de `docs/` y, si es una tarea, al plan.
- **E2E:** las pruebas de punta a punta del asistente (`app/e2e`, tauri-driver con xvfb) se corren al tocar pantallas
  o el arranque de procesos.
- Lo que dependa del equipo de la usuaria (la Steam Deck, un Windows limpio) se apunta en el plan como pendiente de
  `INS-8` o de la fase 5.
