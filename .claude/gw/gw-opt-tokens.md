<!-- galivelop-workflow v0.5.1 -->
# gw-opt-tokens — notas del proyecto

Las lee la skill `gw-opt-tokens` antes de proponer nada, y se actualizan cuando la usuaria aprueba un cambio. El flujo
las crea una vez; desde entonces son del proyecto. Vienen de `.claude/skills/opt-tokens/proyecto.md` (`FLU-1`); lo
que vino del repo del juego lleva sus `QA-xx`. La lanza Claude antes de cada PR a `main`, tras el `/code-review` y
antes de la `/retro`; todo en español, y solo lo que confirme la usuaria entra como tarea del plan.

## Herramientas que ya ahorran

- **Compactar a 200k** (`QA-123`): `CLAUDE_CODE_AUTO_COMPACT_WINDOW` en `.claude/settings.json`, con los puntos de
  `/clear` del paso 1 de [`skills-y-modelos.md`](../../docs/runbooks/skills-y-modelos.md) (`QA-122`).
- **Estado tras compactar o `/clear`** (`QA-116`): `python3 .claude/gw/scripts/recover.py --state` (lo corre el
  gancho de inicio) y `--search "<texto>"` para un detalle de antes, nunca leyendo el registro entero.
- **Sesión directora** (`QA-121`): skill `gw-orchestrate-dealer`.
- **`bash .claude/gw/scripts/merge-branch.sh <rama> "<mensaje>"`** (`QA-135`): fusiona la rama de un subagente y corre
  el check.
- **Revisión por arreglo** (`QA-126`): `/code-review` corto del diff de cada subagente antes de fusionarlo.
- **Pre-push con tests de lo que cambia** (`QA-88`): `relatedTests` de `.claude/gw.json` llama a
  `tools/qa/tests-app.sh` (`vitest related` para `app/src`, `cargo test -p tarkor-nucleo` para el núcleo y el
  catálogo); no hace falta pasar todo tras cada cambio.
- **Texto de cada pantalla en la e2e** (opt-tokens del 2026-10-25): `app/e2e/asistente.e2e.mjs` guarda junto a
  cada `NN-pantalla.png` un `NN-pantalla.txt` con su `innerText`. Se revisa el `.txt`; la imagen, solo si importa
  lo visual (una pantalla que cambia de aspecto).
- **Bitácora en el pre-commit** (opt-tokens del 2026-10-25): `.githooks/pre-commit` corre `handoff.py own-row --staged` sobre
  la bitácora preparada, y la fila se escribe con `handoff.py set-row`, que rechaza pasar de 600 caracteres: el fallo
  salta antes del commit y no al subir, cuando arreglarlo obliga a rehacer commits.

- **Compactaciones de la tarea** (opt-tokens de `INS-43`): `recover.py --state` da también las compactaciones
  desde la última fusión de `origin/main` (el inicio de la tarea), que son las que se comparan con el presupuesto de
  la bitácora; las de toda la sesión sumaban tareas anteriores.
- **Arreglos al mismo subagente y revisores acotados** (opt-tokens de `INS-43`): en
  [`gw-orchestrate-dealer.md`](gw-orchestrate-dealer.md).
- **Check en una llamada y encargos por tramos** (opt-tokens de `INS-42`): en
  [`gw-orchestrate-dealer.md`](gw-orchestrate-dealer.md), «Encargo del implementador».
- **La fila de la bitácora, sola** (opt-tokens de `INS-42`): `python3 .claude/gw/scripts/recover.py --state` la da (o
  `grep -n '<rama>' docs/records/traspaso.md`), y se escribe con `handoff.py set-row` (retro de `FLU-8`). La bitácora entera se leyó 16 veces en `INS-42`.
- **Revisión de un `/gw-update`** (retro de `FLU-8`): la fase 1 revisa solo lo propio y las adaptaciones del flujo
  (`REVIEW.md`); los 68 archivos copiados de v0.5.1 costaron 1,5 M sin nada arreglable aquí.

## Costes conocidos

- **Compilar Rust en frío**: el primer `cargo build`/`clippy` de una sesión tarda minutos y su salida es larga. Se
  filtra (`-q`, `grep -E "^(warning|error)"`) y se lanza en segundo plano si no bloquea.
- **Las e2e** (`app/e2e`, tauri-driver con xvfb): compilan la app entera; solo al tocar pantallas o el arranque de
  procesos, y en un subagente.
- **El ejemplo `motor`** descarga el motor y varios GB de modelos: nunca en la sesión principal ni sin necesidad.
- **Leer el repo del juego**: cuando la tarea cruza con él, se lee con búsquedas estrechas o en un subagente.
- **Medidas de referencia** (opt-tokens de `FLU-6`): tras un `/clear`, cada llamada parte de ~90k de contexto fijo
  (instrucciones, herramientas, skills), así que una tarea pequeña cuesta sobre todo por número de llamadas;
  `/code-review` de un diff de 26 líneas, ~1 M (subagente de 13 llamadas). No se abarata: su contexto limpio
  encontró tres medios que la sesión no vio.
- **Leer la bitácora al empezar** (opt-tokens de `FLU-6`): 80 líneas leídas con la fila ya dada por el gancho
  arrastraron ~70k; el paso 1 de «Al empezar» de `AGENTS.md` pide solo la fila.
- **Páginas de documentación largas** (`QA-176`): un WebFetch con pregunta estrecha o un subagente que devuelva
  solo lo que se busca.
- **Documentos largos del repo** (retro del 2026-10-21): el plan y el `README` fueron lo que más arrastró en
  `FLU-1` (leídos enteros 19 y 10 veces). Se leen por tramos (`grep -n` y `sed -n` de la sección); enteros solo
  al cambiar la estructura del documento.
- **Arreglos de una revisión** (retro de `INS-49`, 2026-10-25): los 11 arreglos de la fase 1 en la sesión principal
  costaron ~60 llamadas a 116k de media. Si son más de tres, a un subagente (`gw-orchestrate-dealer`) con la lista de
  hallazgos como encargo (ya trae rutas y escenario), el modelo grande si hay graves y `/code-review` corto de su
  diff. Los hallazgos se guardan en el scratchpad al salir de la revisión: la lista de leves se copia de ahí.
- **Archivos de código de más de ~300 líneas** (retro de `INS-49`): `lib.rs` y `motor.rs`, leídos enteros 8 y 11
  veces, arrastraron ~300k. Por tramos (`grep -n` del nombre y `sed -n`), como el plan.
- **Qué archivos no pasan `cargo fmt`** (opt-tokens de `FLU-5`): `cargo fmt --all -- --check -l` da solo la lista;
  el diff de `--check` filtrado con `grep` volcó 230 líneas y arrastró ~217k.
- **El registro de la sesión** pesa cientos de MB: medirlo con `measure.py` de la skill, nunca leerlo.

## Ajustes en vigor

- Ventana de compactación automática: `CLAUDE_CODE_AUTO_COMPACT_WINDOW` en `.claude/settings.json` (200k).

## Referencias medidas

<!-- Cifras medidas con las que comparar: fecha, sesión, contexto medio, llamadas, total. -->

## Medidas

- **2026-10-25, `INS-14`, `INS-48`, `FLU-4` en una sola sesión**: 749 llamadas, 13 compactaciones, contexto medio
  267k (los tramos con la ventana de 200k: ~117k de media). El 96 % de la entrada fue de la sesión principal.
  Acordado: **`/clear` tras cada subida a `main`** (o cada tarea grande), sin enlazar tareas en una sesión; el código
  de un plan cerrado, a subagentes con Sonnet (`gw-orchestrate-dealer`) con `/code-review` corto de su diff; el repo del
  juego, solo con un subagente (`docs/06` y su `index.css` arrastraron 1,9M).
- **2026-10-25, `INS-43`** (desde las 16:30): sesión principal 80 llamadas, contexto medio 106k, 2 compactaciones;
  15 subagentes, 197 llamadas y 17,2M de entrada de 25,7M (el reparto funciona: la principal bajó del 96 % al 33 %).
  Lo más caro: 7 revisores con Opus (4,7M, 17-21 llamadas cada uno), 4 rondas de arreglos con un subagente nuevo
  (~1,5M cada una) y el primer E2E (40 llamadas, 4,2M, buscando cómo correrlo; el segundo, con el README al día, 8).
  Acordado: arreglos al mismo subagente, revisores acotados y compactaciones de la tarea en `recover.py`.
- **2026-10-26, `INS-42`** (desde `f399a63`): sesión principal 87 llamadas, contexto medio 114k, 2 compactaciones;
  8 subagentes, 245 llamadas y 23,8M de entrada de 33,6M (71 %), de 52k al arrancar a ~100k de media. Acordado: el
  check con `ci-local.py`, encargos por tramos y la fila de la bitácora con `recover.py --state`.
