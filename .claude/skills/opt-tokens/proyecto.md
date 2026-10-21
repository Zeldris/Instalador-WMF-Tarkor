# `opt-tokens` en el instalador

Lo propio de este proyecto para la skill. En otro proyecto, este archivo se reescribe. Lo que vino del repo del
juego (2026-10-21, `FLU-1`) lleva sus `QA-xx`; el detalle de cada uno está en el historial de ese repo.

## Lo que ya ahorra (no proponerlo otra vez)

- **Compactar a 200k** (`QA-123`): `CLAUDE_CODE_AUTO_COMPACT_WINDOW` en `.claude/settings.json`, con los puntos de
  `/clear` del paso 1 de [`skills-y-modelos.md`](../../../docs/runbooks/skills-y-modelos.md) (`QA-122`).
- **Estado tras compactar o `/clear`** (`QA-116`): el gancho de `SessionStart` corre `tools/qa/recuperar.py --estado`
  (fila de la bitácora, `git status`, últimos commits); un detalle de antes se busca con
  `recuperar.py "<regex>"`, nunca leyendo el registro entero.
- **Sesión directora** (`QA-121`): skill `orchestrate-dealer`.
- **`medir.py`**: curva de contexto por tramo (`QA-111`, `QA-127`), `--desde <ISO|sha>` (`QA-134`), reparto
  `POR MODELO` y `POR SUBAGENTE` (`QA-117`); su test en `tools/qa/tests/test_medir.py` (`QA-113`).
- **`tools/qa/fusionar.sh <rama> "<mensaje>"`** (`QA-135`): fusiona la rama de un subagente y pasa los tests del
  paquete tocado.
- **Revisión por arreglo** (`QA-126`): `/code-review` corto del diff de cada subagente antes de fusionarlo.
- **Pre-push con tests de lo que cambia** (`QA-88`, `tools/qa/tests-relacionados.sh`): `vitest related` para
  `app/src` y `cargo test -p tarkor-nucleo` para el núcleo y el catálogo; no hace falta pasar todo tras cada cambio.

## Gastos conocidos

- **Compilar Rust en frío**: el primer `cargo build`/`clippy` de una sesión tarda minutos y su salida es larga. Se
  filtra (`-q`, `grep -E "^(warning|error)"`) y se lanza en segundo plano si no bloquea.
- **Las e2e** (`app/e2e`, tauri-driver con xvfb): compilan la app entera; solo al tocar pantallas o el arranque de
  procesos, y en un subagente.
- **El ejemplo `motor`** descarga el motor y varios GB de modelos: nunca en la sesión principal ni sin necesidad.
- **Leer el repo del juego**: cuando la tarea cruza con él (la fase 2), se lee con búsquedas estrechas o en un
  subagente, no enteros sus documentos.
- **Páginas de documentación largas** (`QA-176`): un WebFetch con pregunta estrecha o un subagente que devuelva
  solo lo que se busca.
- **Documentos largos del repo** (retro del 2026-10-21): el plan y el `README` fueron lo que más arrastró en
  `FLU-1` (leídos enteros 19 y 10 veces). Se leen por tramos (`grep -n` y `sed -n` de la sección); enteros solo
  al cambiar la estructura del documento.
- **El registro de la sesión** pesa cientos de MB: medirlo con `medir.py`, nunca leerlo.
