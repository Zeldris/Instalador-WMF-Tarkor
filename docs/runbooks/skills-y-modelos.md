# Skills y selector de modelo

**Para qué:** qué skills usa Claude en el instalador, cuándo, y con qué modelo conviene trabajar cada
tipo de tarea. Viene del repo del juego (2026-10-21, `FLU-1`), que lo armó a partir de
[mattpocock/skills](https://github.com/mattpocock/skills); los `QA-xx` citados son de su historial. Desde el
piloto `FLU-2` (2026-10-22), las skills, los scripts (`.claude/gw/scripts/`) y los ganchos son los de
Galivelop-workflow v0.2.0; lo propio del instalador está al final, en
[Notas del proyecto por skill](#notas-del-proyecto-por-skill).

**`.claude/skills/`, `.claude/gw.json`, `.claude/gw/` y `.claude/settings.json` están versionados**; el resto de
`.claude/` es local y está en el `.gitignore`. Si una skill no está cargada, se sigue su descripción de aquí.

## Cómo se usa: el flujo de una tarea

Cada skill se carga con la herramienta Skill (no basta con nombrarla); `/grill-with-docs` solo lo
lanza la usuaria.

1. **Empezar la tarea:** cargar `gw-selector`, clasificar la tarea con su tabla y decir en una línea qué
   skill y qué modelo pide, y su presupuesto de compactaciones (1 a 5, `QA-116`).
   **Sesión directora** (`QA-121`): con `gw-orchestrate-dealer`, la principal reparte cada trozo a un
   subagente de contexto limpio y solo recibe su resumen.
   **Puntos de `/clear`** (`QA-122`): la compactación automática (tope de 200k en `settings.json`) es
   la red; el corte limpio es un `/clear` en un punto estable: al cerrar una tarea del plan, tras
   fusionar un PR o cuando la tarea ya gastó su presupuesto de compactaciones, nunca a mitad de un
   paso. Entre el `/code-review` y la `/retro` de un PR no se limpia: `/gw-opt-tokens` y la `/retro` leen
   esta sesión. Antes de recomendarlo, todo con commit y push y la fila de la bitácora con el
   siguiente paso; entonces Claude dice «Punto de `/clear`: todo subido (`<commit>`). Escribe `/clear`
   y después «sigue».». Tras el `/clear` o una compactación, el gancho de `SessionStart`
   (`recover.py --state`) pone la fila de la bitácora, `git status` y los últimos commits; un
   detalle de antes se busca con `python3 .claude/gw/scripts/recover.py --search "<texto>"`.
2. **Si hay diseño o una decisión abierta:** `grilling` + `domain-modeling` (o `/grill-with-docs` si
   lo lanza la usuaria), contrastando con instaladores y lanzadores conocidos (Steam, itch.io,
   Heroic, LM Studio, el instalador de Ollama) y diciendo de cuál sale cada propuesta. Si una
   pregunta pide ver una pantalla o un flujo para decidir, `prototype` (como
   [`diseno/prototipo-asistente.html`](../../diseno/prototipo-asistente.html)). Lo decidido, a su
   documento de `docs/` y al plan; los términos, a `GLOSSARY.md`; lo difícil de revertir, a
   `docs/adr/`.
3. **Implementar** por pasos pequeños, cada uno con sus tests, y commit + push en cada punto estable
   (`AGENTS.md`). En cada paso, los tests de lo tocado: `cargo test -p tarkor-nucleo` (segundos) y
   `npx vitest run <archivos>` en `app/`; el pre-push ya pasa `tsc`, `cargo fmt --check`, clippy y los tests de lo que
   cambia. Al tocar pantallas o el arranque de procesos, las pruebas de punta a punta de `app/e2e`.
   Antes del commit de un arreglo, [`REVIEW.md`](../../REVIEW.md): Linux y Windows, procesos que se
   paran, compatibilidad de `config.json` y del catálogo.
   **Los ganchos** (`.claude/gw/scripts/`, `.githooks/`) y `.claude/settings.json`: en modo automático el
   clasificador bloquea editarlos; se pide permiso a la usuaria antes, no al fallar (retro del
   2026-10-21).
4. **Si algo falla** (test rojo, intermitente, bug): `diagnosing-bugs` antes de tocar el código.
5. **Cerrar la tarea:** casilla marcada en el plan, bitácora al día, commit + push. El `/code-review`,
   `/gw-opt-tokens` y la `/retro` van al final, antes de crear el PR a `main` (pasos 6 y 7), no por
   tanda. Al contárselo a la usuaria, el destino con su nombre: «en la rama de trabajo, no en `main`»
   o «en `main` (PR #N)».
   «Actualiza con main» es traer `main` a la rama de trabajo en local y decir si está al día; sin
   commit ni push, salvo que lo pida.
6. **Antes de un PR a `main`** (solo cuando lo pide la usuaria), en tres fases (`QA-183`); esta es la
   fuente única del orden:
   1. **Código:** `git fetch origin main` y `/code-review --max-findings all` del diff contra
      `origin/main` (criterio en [`REVIEW.md`](../../REVIEW.md)). Se arregla lo que encuentre y se
      sube.
   2. **Entorno:** si la rama trae medidas con un Ollama real (el ejemplo `motor` del núcleo,
      `INS-8`), `/gw-opt-ai`; luego `/gw-opt-tokens` y `retro` (paso 7). Lo que apruebe la usuaria se
      aplica en la rama.
   3. **Cierre:** si la fase 2 añadió código (herramientas, scripts, skills con tests),
      `/code-review --max-findings all` solo de esos commits (`<commit de la retro>..HEAD`) y sus
      arreglos. Luego `bash .claude/gw/scripts/reviewed.sh`, la descripción con `pr` y se crea el PR.
   Tras crear el PR, `subscribe_pr_activity` y se fusiona al llegar el CI en verde, nunca antes (el
   gancho `review-before-main.sh` lo bloquea). El último commit antes del PR deja la fila de la
   rama como «PR a `main`; al fusionarse, rama terminada», para que `main` la reciba ya cerrada.
7. **Antes de crear cada PR a `main` (fase 2 del paso 6), y al cerrar una fase del plan:** `retro`,
   sobre lo que va a entrar con el PR o sobre toda la fase. Sus propuestas se presentan a la usuaria,
   que las confirma (nada se aplica antes); quedan en `docs/records/retro-<fecha>-<tema>.md` con su
   `**Estado:**` decidido, que `reviewed.sh` exige. Cada pocas fases,
   `/improve-codebase-architecture`. Lo aceptado entra en el plan con su `INS-n` o `FLU-n`.

Nada cambia de las reglas de `AGENTS.md`: las skills se apoyan en ellas, no las sustituyen.

## Skills que encajan

| Skill | Se invoca | Qué hace | Cuándo, en este proyecto |
|---|---|---|---|
| `gw-selector` | sola, al empezar tarea | Elige skill y modelo según el caso | Siempre, al arrancar una tarea, un bug o un diseño |
| `gw-orchestrate-dealer` | Claude, en toda tarea de más de un paso | La sesión principal parte y decide; cada trozo va a un subagente de contexto limpio que devuelve un resumen corto | Fases del plan con varias tareas (la 3 y la 4) |
| `/grill-with-docs` | la usuaria o Claude al proponer diseño | Entrevista por rondas hasta no dejar nada supuesto; mantiene `GLOSSARY.md` y los ADR | Antes de diseñar algo grande: actualizaciones, firma, perfiles por encima del máximo |
| `grilling` | por debajo de la anterior | La entrevista en sí | — |
| `domain-modeling` | por debajo de la anterior, o al discutir términos | Glosario (`GLOSSARY.md`) y decisiones difíciles de revertir (`docs/adr/`) | Términos del instalador (perfil, máximo seguro, motor, catálogo, carpeta de datos) |
| `diagnosing-bugs` | sola ante un bug o test rojo | Primero un test o comando que reproduzca el fallo; luego minimizar, hipótesis, arreglo y test de regresión | Fallos del CI de Windows, procesos que no paran, descargas que se cortan |
| `/improve-codebase-architecture` | la usuaria o al cerrar fase | Busca módulos que simplificar y los presenta en un informe | Cada pocas fases; candidato: `src-tauri/src/lib.rs` |
| `codebase-design` | por debajo de la anterior | Vocabulario para diseñar módulos con interfaz pequeña | — |
| `gw-opt-tokens` | Claude, antes de crear cada PR a `main` (tras el `/code-review`), o la usuaria con `/gw-opt-tokens` | Mide dónde se fueron los tokens de la sesión (`measure.py`) y propone cómo gastar menos | Las propuestas las confirma la usuaria |
| `gw-opt-ai` | Claude o la usuaria con `/gw-opt-ai`, tras medir con un Ollama real | Mide la IA local y propone ajustes por perfil de equipo | Al ajustar el catálogo y `rendimiento.rs` con lo medido en `INS-8` |
| `gw-scout-updates` | Solo la usuaria con `/gw-scout-updates [sección]` (gasta muchos tokens) | Inventaria la arquitectura, busca actualizaciones con fuentes citadas y compara modelos | Nuevas versiones de Ollama, Tauri o de los modelos del catálogo |
| `retro` | Claude, antes de crear cada PR a `main` y al cerrar fase (o la usuaria con `/retro`) | Propone mejoras del entorno: comprobaciones automáticas, instrucciones, herramientas | Las propuestas las confirma la usuaria |
| `writing-for-agents` | sola al escribir para agentes | Cómo escribir AGENTS.md, skills y documentos para agentes | Al tocar `AGENTS.md`, la bitácora o una skill |
| `prototype` | Claude, dentro de una ronda de diseño | Prototipo para tirar: un HTML con botones para probar una pantalla o un flujo antes de decidir | Pantallas del asistente y de Ajustes; se guarda en `diseno/` |
| `pr` | Claude, al abrir un PR a `main` | Descripción del PR: resumen visual, evidencia y peligro del merge | Cada PR a `main`. Evidencia: `cargo test`, clippy, `tsc`, `vitest` y las e2e si tocan pantallas |
| `research`, `to-questionnaire` | Claude, cuando haga falta | Investigar con fuentes citadas; pasar preguntas abiertas a un cuestionario | Licencias, firma de código, requisitos de Windows |
| `gw-doctor`, `gw-update`, `gw-init` | la usuaria, o Claude si el flujo falla | Diagnosticar el flujo (`doctor.py`), actualizarlo a una versión nueva de Galivelop-workflow, o montarlo | `gw-init` ya se usó (piloto `FLU-2`); `gw-doctor` ante un gancho que no salta |

## Descartadas, y por qué

- **`handoff`**: guarda el traspaso en una carpeta temporal; en la nube se pierde. Ya está la
  bitácora.
- **`to-spec`, `to-tickets`, `triage`, `wayfinder`, `implement`**: suponen un gestor de issues; aquí el
  trabajo vive en el plan.
- **`code-review`**: Claude Code trae `/code-review` de serie.
- **`git-guardrails-claude-code`**, **`setup-pre-commit`**: van contra el commit + push constante.

## Selector de modelo

Tres tamaños: **grande** (Opus), **medio** (Sonnet), **ligero** (Haiku).

| Caso | Modelo | Por qué |
|---|---|---|
| Diseño, decisiones, `/grill-with-docs` | grande | Un error se arrastra a todo lo que se construye encima |
| Procesos, descargas, plataformas (Windows y Linux a la vez) | grande | Fallos que solo salen en la otra plataforma o al cerrar |
| Bug difícil o intermitente | grande | Hace falta sostener la hipótesis y el bucle de prueba |
| Tarea acotada del plan (una pantalla, un comando de Tauri, un ajuste del catálogo) | medio | Bien definida; lo caro es escribir, no pensar |
| Cambios mecánicos (docs, bitácora, renombrados) | medio o ligero | Poco razonamiento |
| Búsquedas amplias en el código (subagente) | ligero | Solo localizar; lo que afirme se comprueba con un grep antes de decidir con ello |
| Revisión del diff antes de PR, `/retro`, arquitectura | grande | Juicio sobre el conjunto |

**Límites:**

- El modelo de la sesión lo elige la usuaria con `/model`; Claude no puede cambiarlo desde dentro.
  Si la tarea pide otro, lo dice en una línea al empezar y sigue.
- Claude sí elige el modelo de los **subagentes** que lance. El diseño y las decisiones nunca se
  delegan.
- **Planificar con el grande, escribir con el medio** (`QA-117`): con el plan cerrado (archivos,
  funciones, tests que tienen que pasar), la implementación acotada va a un subagente `sonnet` y la
  sesión principal revisa su diff antes del commit.
- **Escalera y topes** (`QA-118`): cada subagente empieza en el peldaño más barato que encaje y sube
  uno por fallo (`sonnet` low → `sonnet` medium → `opus` medium → `opus` high), con dos fallos como
  tope. Detalle en el `gw-selector`.
- En la duda, el de más riesgo.

## Notas del proyecto por skill

Lo propio del instalador para cada skill del flujo (las skills no se editan: vienen de Galivelop-workflow). Las de
`gw-opt-ai`, `gw-opt-tokens` y `gw-scout-updates` están en `.claude/gw/<skill>.md`, que la skill lee sola.

### `improve-codebase-architecture`

el informe y las propuestas, en español; cada candidata aceptada entra
como tarea del plan (`docs/05-plan-de-trabajo.md`) con su `INS-n` o `FLU-n`.

### `research`

para lo que pide fuentes antes de decidir (licencias de Ollama y de los
modelos, firma de código en Windows, requisitos de WebView2, versiones nuevas de Tauri): cada
afirmación con su fuente primaria y la fecha de consulta, en español. Es también el molde de las
citas de `gw-scout-updates` y `gw-opt-ai`. 

### `domain-modeling`

escribe el glosario y los ADR en español. `GLOSSARY.md` (raíz) es el vocabulario del instalador: perfil, máximo seguro, motor, catálogo,
carpeta de datos, asistente. Un término que ya define un documento de `docs/` (el 09 los perfiles,
el 12 el catálogo) se enlaza, no se redefine. ADR en `docs/adr/`. El juego tiene su propio
glosario en su repositorio: un término del juego se nombra igual que allí.

### `pr`

cada PR a `main`, después de `/code-review` y sus arreglos. Todo en
español; título con los identificadores de las tareas (`INS-31`, `FLU-1`…). **Evidencia:** los
números de `cargo test -p tarkor-nucleo`, clippy, `tsc` y `vitest` (y las e2e de `app/e2e` si
toca pantallas o el arranque de procesos), la CI de Linux y Windows, y el test que cubre cada
cambio importante. **Peligro:** lo que ya está en el equipo de alguien es puerta de un solo
sentido: el formato de `config.json` y del catálogo, la versión y el SHA256 del motor, las rutas de
la carpeta de datos y cualquier cosa que pueda borrar partidas ([`REVIEW.md`](../../REVIEW.md)). Al final, las líneas de atribución que pida la sesión.

### `grilling`

las rondas, en español. Lo decidido se apunta en su documento de `docs/`
y en el plan (`docs/05-plan-de-trabajo.md`), o en la bitácora (`docs/records/traspaso.md`,
«Decisiones de la usuaria»), como pide `AGENTS.md`.

**Instaladores de referencia** (como en el repo del juego con sus juegos de referencia): antes de
cada ronda, busca cómo resuelven esa decisión Steam, itch.io, Heroic, LM Studio y el instalador de
Ollama (con `WebSearch`). Cada recomendación dice cuál la respalda o de cuál se aparta y por qué,
y la ronda acaba con las fuentes enlazadas.

**Prototipo:** si una pregunta pide ver una pantalla o un flujo para decidir, llama a la
herramienta Skill con `prototype` y pon el enlace en esa pregunta.

### `prototype`

en español. Se usa dentro de una ronda de diseño (`grilling`) cuando
la usuaria tiene que ver una pantalla o un flujo para decidir (pasos del asistente, Ajustes,
cómo se enseña el máximo seguro): sobre todo la rama de UI, en un solo HTML como
`diseno/prototipo-asistente.html`. La rama de lógica, para reglas que sobre el papel no se sienten
(qué perfil se recomienda con cada equipo, cuánto margen deja `rendimiento`).
Si la sesión tiene la herramienta `Artifact`, publícalo y pon el enlace en la ronda (la usuaria
lo abre desde el móvil); si no, envíaselo con `SendUserFile`.

**Guardarlo:** las sesiones solo suben a su rama de trabajo, así que no hay rama aparte. El HTML
se queda en `diseno/<tarea>-<tema>.html`; las variantes descartadas se borran al elegir. El
veredicto (qué pregunta resolvió y qué se eligió) va a la tarea del plan y a su documento
(`docs/11-diseno-del-frontal.md` para pantallas), con el enlace al prototipo.

### `retro`

la lanza Claude antes de crear cada PR a `main`, tras el `/code-review` y sus
arreglos y tras `/gw-opt-tokens` (usuaria, en el repo del juego, 2026-10-13 y 2026-10-19; entre lo revisado, también la propia skill
`gw-opt-tokens`: si su medida o sus propuestas fallaron o se quedaron cortas), y al cerrar cada fase del plan (2026-10-06). Lo que se revisa es lo que va
a entrar con el PR, o la fase entera,
que suele cruzar varias sesiones:
sus commits, la bitácora y sus tareas en el plan. Las propuestas, en español,
se presentan a la usuaria: ella las revisa y decide, y lo aprobado se aplica en la rama antes de
crear el PR. Solo las que confirme
entran como tarea del plan con su `INS-n` o `FLU-n`, y quedan en `docs/records/retro-<fecha>-<tema>.md`
con su `**Estado:**` decidido, que `.claude/gw/scripts/reviewed.sh` exige (`requireRetro`).

**Las skills propias, también** (usuaria, 2026-10-19, `QA-130`): cada retro mira cómo rindieron en lo revisado
las skills del proyecto (`.claude/skills/`: `gw-opt-tokens`, `gw-orchestrate-dealer`, `gw-selector`, `pr`, esta misma…)
y el `/code-review`, y propone mejorarlas donde fallaron o se quedaron cortas: un fallo que la revisión dejó
pasar o encontró tarde, un ahorro de `gw-opt-tokens` que costó calidad o no se midió, un paso que se saltó porque
la skill no lo pedía con claridad.

**Y proponen desde ellas** (usuaria, 2026-10-20): antes de proponer, lee la tabla de
[`.claude/skills/README.md`](../../.claude/skills/README.md). Si lo que falló es de una skill propia (`gw-opt-ai` para la IA
local, `gw-opt-tokens` para el gasto, `gw-orchestrate-dealer` para el reparto…), la propuesta cambia esa skill o la usa,
en vez de añadir una regla suelta a `AGENTS.md` o un runbook; y no propone lo que una skill ya hace.
