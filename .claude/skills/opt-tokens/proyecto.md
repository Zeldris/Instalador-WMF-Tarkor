# `opt-tokens` en Tarkor

Lo propio de este proyecto para la skill. En otro proyecto, este archivo se reescribe.

## Lo que ya ahorra (no proponerlo otra vez)

- **Rondas de pruebas en texto** (`QA-104`): `tools/playwright-e2e/mcp/estado.js` (HUD, modales y cajones con sus
  botones, tarjeta del encuentro, tooltips, lo escrito, diario y combate en unas 10 líneas) y `pulsar.js` (pulsar
  por texto); se lanzan con `tools/playwright-e2e/orden.sh --ayuda <ayuda> '<tk>'`. Captura solo para lo visual.
- **Escenarios** (`QA-102`): `tools/qa/escenario.sh` guarda y carga la base de juego, avanza días y da objetos: no se
  vuelve a jugar para llegar a un estado.
- **Recorridos** (`QA-103`): `tools/qa/recorrer.sh`, una línea por comprobación ya escrita.
- **Matriz de cobertura** (`QA-101`): `tools/qa/matriz-pruebas.py --bloque <Bloque>` dice qué falta sin leer el roadmap.
- **SQL contra la partida** en vez de navegar la interfaz para mirar datos (`rondas-de-pruebas.md`, `QA-97`).
- **Mapa del agente** (`QA-108`): `docs/mapa-agente.md` da por sistema las funciones de entrada, tests, tablas e
  interfaz; si una sesión exploró para encontrar algo que no estaba, se añade ahí.
- **Compactar a 200k** (`QA-109` a 300k; 200k desde `QA-121`; 300k en `QA-122` y otra vez 200k en `QA-123`, porque
  con 300k el techo subió de ~145k a ~220k): `CLAUDE_CODE_AUTO_COMPACT_WINDOW` en `.claude/settings.json`, con los
  puntos de `/clear` de `QA-122`. Antes de `QA-109` el contexto crecía de ~76k a ~742k por tramo (media 428k por llamada).
- **Sesión directora** (`QA-121`, sustituye la sesión nueva tras cada PR de `QA-110`): skill `orchestrate-dealer`.
  Si la sesión ya compactó, se propone `/clear` tras fusionar (`QA-187`, paso 6 de `skills-y-modelos.md`): la sesión de la línea encadenó
  3 PR con 25 compactaciones y ~113k de contexto medio.
- **Curva de contexto en `medir.py`** (`QA-111`): suelo, techo y llamadas por tramo entre compactaciones; desde
  `QA-127`, medio y techo de cada uno de los últimos 8 tramos y el medio sin el primer tramo a medias.
- **`medir.py --desde <ISO|sha>`** (`QA-134`): mide solo desde una fecha o desde un commit (su fecha), con el primer tramo a medias descartado como en `--horas`.
- **`tools/qa/fusionar.sh <rama> "<mensaje>"`** (`QA-135`): merge `--no-ff` de la rama de un subagente, resuelve solo los conflictos de `pruebas-0.3-hallazgos.md` (queda el estado no pendiente), pasa los tests del paquete tocado y avisa si falta la marca de revisión.
- **Rondas en un subagente `sonnet`** (`QA-124`): la principal reparte tandas y apunta; no lanza `orden.sh`.
- **Ayudas del driver** (`QA-125`): `interactuar` también con el menú del NPC del mapa, `opcion` por número de
  `[data-opcion]` y `pelear` (acercarse, interactuar y combatir en una orden). `orden.sh` guarda cada respuesta
  entera en `tools/playwright-e2e/shots/ultima-respuesta.txt` y muestra 40 líneas (`QA-128`).
- **Revisión por arreglo** (`QA-126`): `/code-review` corto del diff de cada subagente antes de fusionarlo.
- **Tests de las herramientas** (`QA-113`): `medir.py` tiene el suyo en `tools/qa/tests/test_medir.py`; si se toca,
  se pasa `python3 -m unittest discover -s tools/qa/tests`.
- **Modelo por tarea** (`QA-117`): `medir.py` reparte la entrada por modelo, sesión principal y subagentes; el
  runbook `skills-y-modelos.md` manda escribir con un subagente `sonnet` cuando el plan está cerrado.
- **Salida de subagentes no fiable** (retro de `QA-176`): `medir.py` la da como «—» cuando su registro no la guarda.
- **Pre-push con tests de lo que cambia** (`QA-88`, `QA-98`): no hace falta pasar la suite entera tras cada cambio.

## Gastos conocidos

- **La ronda `QA-105` en la principal** (2026-10-19): 1.295 llamadas en 24 h, 1.150 órdenes de Bash, 44 capturas
  leídas, todo con Opus; 30 compactaciones. De ahí `QA-123`…`QA-128`.

- **Sesiones largas sin compactar**: el 2026-10-19, 578 llamadas en 24 h con 428k tokens de contexto medio (el 99 % de
  caché leída); en toda la sesión, 15 tramos de suelo ~76k y techo ~742k, unas 440 llamadas por tramo. (Las cifras
  de la primera medida, 543 llamadas y 566k, salían dobladas: `medir.py` contaba cada bloque de una respuesta.) Es la palanca más grande: contexto medio × llamadas
  (`QA-109`, `QA-110`).
- **Todo con el modelo grande**: en la sesión del 2026-10-19, la principal (Opus) llevó el 92 % de la entrada
  (2.795M de 3.046M) y 23 de los 61 subagentes también fueron con Opus (`QA-117`).
- **Rondas de pruebas**: muchas llamadas pequeñas (pulsar, mirar, pulsar). Encadenar pasos en una orden de
  `orden.sh` y mirar el estado al final.
- **Suites con base real** (backend, ~3.600 tests): la salida entera es grande; filtrar con `grep -E "Test Files|Tests
  |FAIL"`.
- **Páginas de documentación largas** (retro de `QA-176`, 2026-10-20): un WebFetch de la guía de skills metió 12k
  tokens en la principal y arrastró 144k. Se leen con un WebFetch de pregunta estrecha (qué dice sobre X) o en un
  subagente que devuelva solo lo que se busca.
- **Releer documentos largos enteros** (misma retro): `docs/scout/arquitectura.md` se leyó 26 veces (146k arrastrados);
  ahora `contrastar.py --seccion <título>`. Antes de un `cat` repetido, buscar la opción que lee un trozo.
- **El registro de la sesión** pesa cientos de MB: medirlo con `medir.py`, nunca leerlo.
