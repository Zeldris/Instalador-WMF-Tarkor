#!/bin/bash
# QA-88 (de Tarkor): los tests de lo que cambia, en el push. En Tarkor un cambio rompió 13 tests que solo se vieron
# al pasar la suite completa; el pre-push solo tipaba y pasaba el lint.
# En el instalador:
#   - `app/src` (asistente React): `vitest related`, los tests que importan, directa o indirectamente, lo cambiado.
#   - `app/nucleo` (Rust puro): `cargo test -p tarkor-nucleo` (52 tests, segundos con la caché).
#   - `app/catalogo/`: lo valida el núcleo (`catalogo` y `perfiles`), así que también `cargo test -p tarkor-nucleo`.
# Uso: tests-relacionados.sh <archivo con los cambiados, uno por línea, relativos a la raíz>
set -uo pipefail
cambiados="$1"
cd "$(git rev-parse --show-toplevel)"

archivos=()
while read -r f; do
  [ -f "$f" ] && archivos+=("${f#app/}")
done < <(grep -E "^app/src/.*\.(ts|tsx)$" "$cambiados" | sort -u)
if [ ${#archivos[@]} -gt 0 ]; then
  log="/tmp/pre-push-related-app.log"
  echo "pre-push: tests relacionados del asistente (${#archivos[@]} archivos cambiados)…"
  (cd app && npx vitest related --run --passWithNoTests "${archivos[@]}" > "$log" 2>&1) \
    || { grep -E "FAIL|AssertionError|Error:|Test Files|Tests " "$log" | head -30; echo "pre-push: tests del asistente en rojo (log completo en $log)"; exit 1; }
fi

if grep -qE "^app/(nucleo/|catalogo/|Cargo\.(toml|lock)$)" "$cambiados"; then
  log="/tmp/pre-push-nucleo.log"
  echo "pre-push: tests del núcleo (cargo test -p tarkor-nucleo)…"
  (cd app && cargo test -q -p tarkor-nucleo > "$log" 2>&1) \
    || { grep -E "^test .* FAILED|panicked|error(\[|:)|test result" "$log" | head -30; echo "pre-push: núcleo en rojo (log completo en $log)"; exit 1; }
fi
exit 0
