# Instrucciones para Claude en este repositorio

Instalador de escritorio de Tarkor (Tauri v2, Windows y Linux). El flujo de trabajo viene del repo del
juego (`World-Maker-Fantasy`, 2026-10-21): los `QA-xx` que se citan aquí y en `tools/qa` son de su
historial; las tareas de este repo son `INS-n` (el [plan](docs/05-plan-de-trabajo.md)) y `FLU-n` (el
flujo de trabajo).

Se trabaja por relevos: una sesión puede quedarse sin tokens en cualquier momento y otra (de otra
cuenta) tiene que poder seguir **sin perder nada y sin preguntar por dónde iba**.

## Al empezar cualquier sesión

1. Lee [`docs/registros/traspaso.md`](docs/registros/traspaso.md): rama de trabajo, tarea en curso,
   qué falta y siguiente paso.
2. Mira `git log` de esa rama (`git fetch origin <rama>` primero) y comprueba que el último commit
   coincide con lo que dice la bitácora.
3. Comprueba que los tests están como dice la bitácora antes de tocar nada.
4. Sigue por el **siguiente paso** de la bitácora, salvo que la usuaria pida otra cosa.
5. **Al empezar cada tarea y al fusionar cada PR, trae `main`** (`QA-72`): `git fetch origin main` y,
   si trae commits, `git merge origin/main` (merge, nunca rebase: las ramas están subidas). Si el
   conflicto toca la misma lógica por los dos lados, se para y se consulta a la usuaria.
6. Al empezar cada tarea, aplica el `selector` (qué skill y qué modelo pide el caso) y sigue el flujo
   de [`docs/runbooks/skills-y-modelos.md`](docs/runbooks/skills-y-modelos.md#cómo-se-usa-el-flujo-de-una-tarea).

**Diseño:** una ronda de diseño (una pantalla del asistente, un perfil, cómo se descarga o se
actualiza algo) se contrasta con instaladores y lanzadores conocidos (Steam, itch.io, Heroic, el
asistente de LM Studio y el instalador de Ollama), citando de cuál sale cada propuesta. Lo decidido va
a su documento de `docs/` y, si es una tarea, al plan con su `INS-n`.

**Dónde está cada cosa:** documentos de diseño en `docs/01`…`docs/12` (índice en el
[README](README.md)); código y cómo se prueba en [`app/README.md`](app/README.md).

## Trabajo por relevos: commit y push constantes

Cada sesión corre en un contenedor temporal: **lo que no está subido a GitHub no existe** para la
siguiente.

- **Al cerrar cada tarea** del plan: commit + push en el acto, la casilla marcada (`- [x] **INS-n**`)
  con fecha y qué se hizo, y la bitácora al día. Una tarea a medias lleva `🚧` con lo hecho y lo que
  falta.
- **El estado vive en los `.md`, no en la conversación**: el plan dice qué está implementado, la
  bitácora qué se está haciendo.
- **Ninguna tarea sin fase**: toda tarea nueva entra en una fase del plan con su `INS-n`.
- **Dentro de una tarea grande**, commit + push en cada punto estable (tests en verde). **Nunca más
  de 30-45 minutos de trabajo sin subir.**
- **Si hay que parar con algo a medias o en rojo:** commit igualmente, con `WIP:` al principio del
  mensaje, y en la bitácora qué falla y por qué.
- **Push tras cada commit**, a la rama de trabajo (`git push -u origin <rama>`; si falla por red,
  reintentar con espera 2 s, 4 s, 8 s, 16 s).
- **La bitácora se actualiza en el mismo commit** que el trabajo que describe.
- **Tras una llamada interrumpida o rechazada, `git status` y `git diff` antes de repetirla**
  (`QA-48`): el cambio puede haberse guardado, o incluso subido.
- **Si la usuaria dice que se para, se para**: se sube lo que haya, se deja la bitácora al día y no
  se sigue con nada más.

## Pruebas

- Lo mecánico lo hacen el pre-push (`.githooks/pre-push`: `tsc`, clippy, enlaces, bitácora y los
  tests de lo que cambia) y la CI (`comprobar.yml`, Linux y Windows).
- Lo que dependa del equipo de la usuaria (la Steam Deck, un Windows limpio) no se da por probado con
  tests: se apunta en el plan como pendiente de `INS-8` o de la fase 5.
- Las pruebas de punta a punta del asistente (`app/e2e`, tauri-driver con xvfb) se corren al tocar
  pantallas o el arranque de procesos.

## Mensajes de commit

- Primera línea en español, qué cambia, con los identificadores de las tareas tocadas.
- Cuerpo: qué se hizo, qué queda de esa tarea si no está cerrada, y estado de los tests.
- Última línea antes de la atribución: `Siguiente: <próximo paso concreto>`.

## Ramas y `main`

- Se trabaja en la rama que indique la bitácora (o la que asigne la sesión, que se apunta en la
  bitácora nada más empezar).
- **Cada sesión, su propia rama** (`QA-136`): si la rama de la bitácora ya la usa otra sesión, crea
  `claude/<tema>` desde ella con su fila «Tarea en curso», y escribe solo en esa fila. El pre-push
  rechaza tocar filas de otra rama o compartidas (`QA-145`); para una compartida,
  `BITACORA_COMPARTIDA=1 git push`.
- **A `main` solo se sube cuando la usuaria lo confirma**, siempre por pull request, y se apunta en la
  bitácora.
- **Se fusiona solo con el CI del PR en verde**, también cuando pide «fusiona directamente». El gancho
  `.claude/hooks/revision-antes-de-main.sh` lo comprueba.
- **Antes de crear un PR a `main`, tres fases** (detalle en el
  [paso 6](docs/runbooks/skills-y-modelos.md#cómo-se-usa-el-flujo-de-una-tarea)):
  1. **Código:** `/code-review --max-findings all` del diff contra `origin/main` (con `git fetch`
     antes), criterio en [`REVIEW.md`](REVIEW.md); arreglos subidos.
  2. **Entorno:** `/opt-ai` si hubo medidas con un Ollama real, `/opt-tokens` y `/retro`. Sus
     propuestas se presentan a la usuaria; lo que confirme **se aplica en la rama**.
  3. **Cierre:** si la fase 2 trajo código, `/code-review --max-findings all` de esos commits; luego
     `bash tools/qa/revisado.sh`, la descripción con la skill `pr`, y solo entonces se crea. Sin la
     marca de revisión del mismo commit, el gancho bloquea crear o fusionar el PR.

## La bitácora (`docs/registros/traspaso.md`)

Tiene siempre al día: ramas de trabajo, fase, tarea en curso con lo hecho y lo pendiente, último
commit en `main`, estado de los tests, siguientes pasos en orden, decisiones de la usuaria que
bloquean algo y los comandos para comprobar el estado. Al cerrar una tarea, va tachada a «Hecho
recientemente» (las 10 últimas). Cada rama tiene su fila «Tarea en curso · `<rama>`» y solo escribe
en la suya, como mucho 600 caracteres (lo comprueba el push, `QA-69`).
