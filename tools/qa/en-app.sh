#!/bin/bash
# Corre una orden en `app/` del checkout donde se llama (FLU-2). El pre-push de Galivelop-workflow pasa el check en
# un worktree temporal cuando la copia de trabajo no está limpia, y ese worktree solo enlaza los `node_modules` de la
# raíz: aquí se enlaza `app/node_modules` del checkout principal si falta, y Cargo reutiliza su `app/target` para no
# compilar desde cero.
# Uso: bash tools/qa/en-app.sh <orden> [args...]   (desde la raíz del checkout)
set -euo pipefail
[ "$#" -gt 0 ] || { echo "en-app: uso: bash tools/qa/en-app.sh <orden> [args...]" >&2; exit 2; }
raiz="$(git rev-parse --show-toplevel)"
principal="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"
cd "$raiz/app"
if [ "$raiz" != "$principal" ]; then
  if [ ! -e node_modules ] && [ -d "$principal/app/node_modules" ]; then
    ln -s "$principal/app/node_modules" node_modules
  fi
  export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$principal/app/target}"
fi
exec "$@"
