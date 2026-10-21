# Skills y selector de modelo

**Para qué:** qué skills usa Claude en el instalador, cuándo, y con qué modelo conviene trabajar cada
tipo de tarea. Viene del repo del juego (2026-10-21, `FLU-1`), que lo armó a partir de
[mattpocock/skills](https://github.com/mattpocock/skills); los `QA-xx` citados son de su historial.

**`.claude/skills/`, `.claude/hooks/` y `.claude/settings.json` están versionados**; el resto de
`.claude/` es local y está en el `.gitignore`. Una skill nueva se añade con `git add` normal. Si una
skill no está cargada, se sigue su descripción de aquí.

## Cómo se usa: el flujo de una tarea

Cada skill se carga con la herramienta Skill (no basta con nombrarla); `/grill-with-docs` solo lo
lanza la usuaria.

1. **Empezar la tarea:** cargar `selector`, clasificar la tarea con su tabla y decir en una línea qué
   skill y qué modelo pide, y su presupuesto de compactaciones (1 a 5, `QA-116`).
   **Sesión directora** (`QA-121`): con `orchestrate-dealer`, la principal reparte cada trozo a un
   subagente de contexto limpio y solo recibe su resumen.
   **Puntos de `/clear`** (`QA-122`): la compactación automática (tope de 200k en `settings.json`) es
   la red; el corte limpio es un `/clear` en un punto estable: al cerrar una tarea del plan, tras
   fusionar un PR o cuando la tarea ya gastó su presupuesto de compactaciones, nunca a mitad de un
   paso. Entre el `/code-review` y la `/retro` de un PR no se limpia: `/opt-tokens` y la `/retro` leen
   esta sesión. Antes de recomendarlo, todo con commit y push y la fila de la bitácora con el
   siguiente paso; entonces Claude dice «Punto de `/clear`: todo subido (`<commit>`). Escribe `/clear`
   y después «sigue».». Tras el `/clear` o una compactación, el gancho de `SessionStart`
   (`recuperar.py --estado`) pone la fila de la bitácora, `git status` y los últimos commits; un
   detalle de antes se busca con `python3 tools/qa/recuperar.py "<regex>"`.
2. **Si hay diseño o una decisión abierta:** `grilling` + `domain-modeling` (o `/grill-with-docs` si
   lo lanza la usuaria), contrastando con instaladores y lanzadores conocidos (Steam, itch.io,
   Heroic, LM Studio, el instalador de Ollama) y diciendo de cuál sale cada propuesta. Si una
   pregunta pide ver una pantalla o un flujo para decidir, `prototype` (como
   [`diseno/prototipo-asistente.html`](../../diseno/prototipo-asistente.html)). Lo decidido, a su
   documento de `docs/` y al plan; los términos, a `GLOSSARY.md`; lo difícil de revertir, a
   `docs/adr/`.
3. **Implementar** por pasos pequeños, cada uno con sus tests, y commit + push en cada punto estable
   (`CLAUDE.md`). En cada paso, los tests de lo tocado: `cargo test -p tarkor-nucleo` (segundos) y
   `npx vitest run <archivos>` en `app/`; el pre-push ya pasa `tsc`, clippy y los tests de lo que
   cambia. Al tocar pantallas o el arranque de procesos, las pruebas de punta a punta de `app/e2e`.
   Antes del commit de un arreglo, [`REVIEW.md`](../../REVIEW.md): Linux y Windows, procesos que se
   paran, compatibilidad de `config.json` y del catálogo.
4. **Si algo falla** (test rojo, intermitente, bug): `diagnosing-bugs` antes de tocar el código.
5. **Cerrar la tarea:** casilla marcada en el plan, bitácora al día, commit + push. El `/code-review`,
   `/opt-tokens` y la `/retro` van al final, antes de crear el PR a `main` (pasos 6 y 7), no por
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
      `INS-8`), `/opt-ai`; luego `/opt-tokens` y `retro` (paso 7). Lo que apruebe la usuaria se
      aplica en la rama.
   3. **Cierre:** si la fase 2 añadió código (herramientas, scripts, skills con tests),
      `/code-review --max-findings all` solo de esos commits (`<commit de la retro>..HEAD`) y sus
      arreglos. Luego `bash tools/qa/revisado.sh`, la descripción con `pr` y se crea el PR.
   Tras crear el PR, `subscribe_pr_activity` y se fusiona al llegar el CI en verde, nunca antes (el
   gancho `revision-antes-de-main.sh` lo bloquea). El último commit antes del PR deja la fila de la
   rama como «PR a `main`; al fusionarse, rama terminada», para que `main` la reciba ya cerrada.
7. **Antes de crear cada PR a `main` (fase 2 del paso 6), y al cerrar una fase del plan:** `retro`,
   sobre lo que va a entrar con el PR o sobre toda la fase. Sus propuestas se presentan a la usuaria,
   que las confirma (nada se aplica antes); quedan en `docs/registros/retro-<fecha>-<tema>.md` con su
   `**Estado:**` decidido, que `revisado.sh` exige. Cada pocas fases,
   `/improve-codebase-architecture`. Lo aceptado entra en el plan con su `INS-n` o `FLU-n`.

Nada cambia de las reglas de `CLAUDE.md`: las skills se apoyan en ellas, no las sustituyen.

## Skills que encajan

| Skill | Se invoca | Qué hace | Cuándo, en este proyecto |
|---|---|---|---|
| `selector` (propia) | sola, al empezar tarea | Elige skill y modelo según el caso | Siempre, al arrancar una tarea, un bug o un diseño |
| `orchestrate-dealer` (propia) | Claude, en toda tarea de más de un paso | La sesión principal parte y decide; cada trozo va a un subagente de contexto limpio que devuelve un resumen corto | Fases del plan con varias tareas (la 3 y la 4) |
| `/grill-with-docs` | la usuaria o Claude al proponer diseño | Entrevista por rondas hasta no dejar nada supuesto; mantiene `GLOSSARY.md` y los ADR | Antes de diseñar algo grande: actualizaciones, firma, perfiles por encima del máximo |
| `grilling` | por debajo de la anterior | La entrevista en sí | — |
| `domain-modeling` | por debajo de la anterior, o al discutir términos | Glosario (`GLOSSARY.md`) y decisiones difíciles de revertir (`docs/adr/`) | Términos del instalador (perfil, máximo seguro, motor, catálogo, carpeta de datos) |
| `diagnosing-bugs` | sola ante un bug o test rojo | Primero un test o comando que reproduzca el fallo; luego minimizar, hipótesis, arreglo y test de regresión | Fallos del CI de Windows, procesos que no paran, descargas que se cortan |
| `/improve-codebase-architecture` | la usuaria o al cerrar fase | Busca módulos que simplificar y los presenta en un informe | Cada pocas fases; candidato: `src-tauri/src/lib.rs` |
| `codebase-design` | por debajo de la anterior | Vocabulario para diseñar módulos con interfaz pequeña | — |
| `opt-tokens` | Claude, antes de crear cada PR a `main` (tras el `/code-review`), o la usuaria con `/opt-tokens` | Mide dónde se fueron los tokens de la sesión (`medir.py`) y propone cómo gastar menos | Las propuestas las confirma la usuaria |
| `opt-ai` | Claude o la usuaria con `/opt-ai`, tras medir con un Ollama real | Mide la IA local y propone ajustes por perfil de equipo | Al ajustar el catálogo y `rendimiento.rs` con lo medido en `INS-8` |
| `scout-updates` | Solo la usuaria con `/scout-updates [sección]` (gasta muchos tokens) | Inventaria la arquitectura, busca actualizaciones con fuentes citadas y compara modelos | Nuevas versiones de Ollama, Tauri o de los modelos del catálogo |
| `retro` | Claude, antes de crear cada PR a `main` y al cerrar fase (o la usuaria con `/retro`) | Propone mejoras del entorno: comprobaciones automáticas, instrucciones, herramientas | Las propuestas las confirma la usuaria |
| `writing-for-agents` | sola al escribir para agentes | Cómo escribir CLAUDE.md, skills y documentos para agentes | Al tocar `CLAUDE.md`, la bitácora o una skill |
| `prototype` | Claude, dentro de una ronda de diseño | Prototipo para tirar: un HTML con botones para probar una pantalla o un flujo antes de decidir | Pantallas del asistente y de Ajustes; se guarda en `diseno/` |
| `pr` | Claude, al abrir un PR a `main` | Descripción del PR: resumen visual, evidencia y peligro del merge | Cada PR a `main`. Evidencia: `cargo test`, clippy, `tsc`, `vitest` y las e2e si tocan pantallas |
| `research`, `to-questionnaire` | Claude, cuando haga falta | Investigar con fuentes citadas; pasar preguntas abiertas a un cuestionario | Licencias, firma de código, requisitos de Windows |

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
  tope. Detalle en el `selector`.
- En la duda, el de más riesgo.
