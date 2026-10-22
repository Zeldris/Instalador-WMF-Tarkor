#!/bin/bash
# Los tests de lo que cambia en `app/` (QA-88 de Tarkor), para `relatedTests.fast` de `.claude/gw.json` (FLU-2):
#   - `app/src` (asistente React): `vitest related`, los tests que importan, directa o indirectamente, lo cambiado.
#   - `app/nucleo`, `app/catalogo/` (lo valida el núcleo) y `app/Cargo.toml|lock`: `cargo test -p tarkor-nucleo`.
# El resto de archivos no corre nada. Va por `en-app.sh`, que vale también en el worktree del pre-push.
# Uso: bash tools/qa/tests-app.sh <archivo>...   (rutas relativas a la raíz, como las pasa el pre-push)
set -uo pipefail
cd "$(dirname "$0")/../.."
app=()
nucleo=0
for f in "$@"; do
  case "$f" in
    app/src/*.ts|app/src/*.tsx) [ -f "$f" ] && app+=("${f#app/}") ;;
    app/nucleo/*|app/catalogo/*|app/Cargo.toml|app/Cargo.lock) nucleo=1 ;;
  esac
done
if [ ${#app[@]} -gt 0 ]; then
  log="$(mktemp)"
  echo "tests-app: tests relacionados del asistente (${#app[@]} archivos cambiados)…"
  bash tools/qa/en-app.sh npx vitest related --run --passWithNoTests "${app[@]}" > "$log" 2>&1 \
    || { grep -E "FAIL|AssertionError|Error:|Test Files|Tests " "$log" | head -30
         echo "tests-app: tests del asistente en rojo (log completo en $log)" >&2; exit 1; }
fi
if [ "$nucleo" = 1 ]; then
  log="$(mktemp)"
  echo "tests-app: tests del núcleo (cargo test -p tarkor-nucleo)…"
  bash tools/qa/en-app.sh cargo test -q -p tarkor-nucleo > "$log" 2>&1 \
    || { grep -E "^test .* FAILED|panicked|error(\[|:)|test result" "$log" | head -30
         echo "tests-app: núcleo en rojo (log completo en $log)" >&2; exit 1; }
fi
exit 0
