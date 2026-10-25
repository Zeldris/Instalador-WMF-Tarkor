<!-- galivelop-workflow v0.3.0 -->
# opt-tokens — notas del proyecto

Las lee la skill `opt-tokens` antes de proponer nada, y se actualizan cuando la usuaria aprueba un cambio. El flujo
las crea una vez; desde entonces son del proyecto. Vienen de `.claude/skills/opt-tokens/proyecto.md` (`FLU-1`); lo
que vino del repo del juego lleva sus `QA-xx`. La lanza Claude antes de cada PR a `main`, tras el `/code-review` y
antes de la `/retro`; todo en español, y solo lo que confirme la usuaria entra como tarea del plan.

## Herramientas que ya ahorran

- **Compactar a 200k** (`QA-123`): `CLAUDE_CODE_AUTO_COMPACT_WINDOW` en `.claude/settings.json`, con los puntos de
  `/clear` del paso 1 de [`skills-y-modelos.md`](../../docs/runbooks/skills-y-modelos.md) (`QA-122`).
- **Estado tras compactar o `/clear`** (`QA-116`): `python3 .claude/gw/scripts/recuperar.py --estado` (lo corre el
  gancho de inicio) y `--buscar "<texto>"` para un detalle de antes, nunca leyendo el registro entero.
- **Sesión directora** (`QA-121`): skill `orchestrate-dealer`.
- **`bash .claude/gw/scripts/fusionar.sh <rama> "<mensaje>"`** (`QA-135`): fusiona la rama de un subagente y corre
  el check.
- **Revisión por arreglo** (`QA-126`): `/code-review` corto del diff de cada subagente antes de fusionarlo.
- **Pre-push con tests de lo que cambia** (`QA-88`): `relatedTests` de `.claude/gw.json` llama a
  `tools/qa/tests-app.sh` (`vitest related` para `app/src`, `cargo test -p tarkor-nucleo` para el núcleo y el
  catálogo); no hace falta pasar todo tras cada cambio.

## Costes conocidos

- **Compilar Rust en frío**: el primer `cargo build`/`clippy` de una sesión tarda minutos y su salida es larga. Se
  filtra (`-q`, `grep -E "^(warning|error)"`) y se lanza en segundo plano si no bloquea.
- **Las e2e** (`app/e2e`, tauri-driver con xvfb): compilan la app entera; solo al tocar pantallas o el arranque de
  procesos, y en un subagente.
- **El ejemplo `motor`** descarga el motor y varios GB de modelos: nunca en la sesión principal ni sin necesidad.
- **Leer el repo del juego**: cuando la tarea cruza con él, se lee con búsquedas estrechas o en un subagente.
- **Páginas de documentación largas** (`QA-176`): un WebFetch con pregunta estrecha o un subagente que devuelva
  solo lo que se busca.
- **Documentos largos del repo** (retro del 2026-10-21): el plan y el `README` fueron lo que más arrastró en
  `FLU-1` (leídos enteros 19 y 10 veces). Se leen por tramos (`grep -n` y `sed -n` de la sección); enteros solo
  al cambiar la estructura del documento.
- **El registro de la sesión** pesa cientos de MB: medirlo con `medir.py` de la skill, nunca leerlo.

## Ajustes en vigor

- Ventana de compactación automática: `CLAUDE_CODE_AUTO_COMPACT_WINDOW` en `.claude/settings.json` (200k).

## Referencias medidas

<!-- Cifras medidas con las que comparar: fecha, sesión, contexto medio, llamadas, total. -->
