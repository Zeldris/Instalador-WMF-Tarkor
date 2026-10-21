#!/bin/bash
# QA-74 (retro del PR #50, 2026-10-13): lo que `.githooks/pre-push` mira de cada rama que se sube, aparte
# para poder probarlo (`tools/qa/tests/test_prepush_ramas.py`). Lee de la entrada lo que git le pasa al
# gancho («ref local, sha local, ref remota, sha remota» por rama) y:
#   - escribe en $1 los archivos que cambian (QA-35: imágenes);
#   - escribe en $2 los commits nuevos, uno por línea (QA-66);
#   - comprueba la bitácora de cada commit nuevo que se sube (QA-69) y que nombra las tareas que se tachan
#     en los roadmaps (QA-85), y su fecha si el commit la cambia (QA-115); sale con 1 si no cumple.
#   - QA-182: avisa (sin fallar) de las tareas 🚧 que nombran los commits y cuya entrada del roadmap no cambia.
#   - QA-145: ningún commit cambia la fila «Tarea en curso» de otra rama ni una fila compartida (salvo con
#     BITACORA_COMPARTIDA=1); la rama es la remota a la que se sube, o la actual si no hay nombre; si el commit
#     está en otra rama local (subrama fusionada de vuelta), vale la fila de esa rama.
# La bitácora se lee con BITACORA_PY (por defecto, la de este repo), para poder probarlo en otro.
set -uo pipefail
cambiados="$1"
subidos="$2"
bitacora_py="${BITACORA_PY:-$(dirname "$0")/bitacora.py}"
: > "$cambiados"
: > "$subidos"
CERO=0000000000000000000000000000000000000000
while read -r _ sha_local ref_remota sha_remoto; do
  [ "$sha_local" = "$CERO" ] && continue
  # Desde dónde mirar los cambios: lo que ya tiene la rama remota si ese commit está aquí; si no (rama
  # nueva, o la otra cuenta subió y no se ha traído), desde donde se separó de main.
  if [ "$sha_remoto" != "$CERO" ] && git cat-file -e "$sha_remoto^{commit}" 2>/dev/null; then
    base="$sha_remoto"
  else
    base=$(git merge-base "$sha_local" origin/main 2>/dev/null || echo "")
  fi
  [ -n "$base" ] && git diff --name-only "$base" "$sha_local" >> "$cambiados" 2>/dev/null
  # QA-85: solo desde lo que ya tiene la rama remota; desde main pediría tareas que ya salieron de
  # «Hecho recientemente» (guarda las 10 últimas).
  if [ "$base" = "$sha_remoto" ]; then python3 "$bitacora_py" --cerradas "$base" "$sha_local" || exit 1; fi
  # QA-182: solo avisa.
  [ -n "$base" ] && python3 "$bitacora_py" --en-curso "$base" "$sha_local"
  # Commits nuevos de verdad: los que no están en ninguna rama remota conocida.
  git log --format='  %h %s' "$sha_local" --not --remotes >> "$subidos" 2>/dev/null
  # QA-69: la bitácora tal como va en cada commit nuevo que se sube (no la del directorio de trabajo,
  # ni solo la del último commit: uno intermedio con la bitácora mal también llegaría al remoto).
  rama="${ref_remota#refs/heads/}"
  { [ -n "$rama" ] && [ "$rama" != "$ref_remota" ]; } || rama=$(git branch --show-current 2>/dev/null)
  compartida=()
  [ -n "${BITACORA_COMPARTIDA:-}" ] && compartida=(--compartida)
  # QA-145: sin los merges (traen filas de main o de otra rama que no son de este commit).
  for commit in $(git rev-list --no-merges "$sha_local" --not --remotes 2>/dev/null); do
    git diff-tree --no-commit-id --name-only -r "$commit" | grep -qx docs/registros/traspaso.md || continue
    # Un commit que viene de otra rama local sin subir (una subrama `claude/<tema>` fusionada de vuelta, QA-136)
    # escribe en la fila de esa rama: vale si cumple contra la que se sube o contra alguna rama local que lo
    # contenga (las de los subagentes también lo contienen si fusionaron esta: por eso se prueba primero esta).
    python3 "$bitacora_py" --ajenas "$commit" "$rama" ${compartida[@]+"${compartida[@]}"} >/dev/null 2>&1 && continue
    vale=""
    for otra in $(git branch --contains "$commit" --format='%(refname:short)' 2>/dev/null); do
      case "$otra" in "$rama"|main|master|"("*) continue ;; esac
      python3 "$bitacora_py" --ajenas "$commit" "$otra" ${compartida[@]+"${compartida[@]}"} >/dev/null 2>&1 \
        && { vale=1; break; }
    done
    [ -n "$vale" ] || python3 "$bitacora_py" --ajenas "$commit" "$rama" ${compartida[@]+"${compartida[@]}"} \
      || { echo "bitácora: en el commit $(git log -1 --format='%h %s' "$commit")"; exit 1; }
  done
  for commit in $(git rev-list "$sha_local" --not --remotes 2>/dev/null); do
    git cat-file -e "$commit:docs/registros/traspaso.md" 2>/dev/null || continue
    tmp=$(mktemp)
    git show "$commit:docs/registros/traspaso.md" > "$tmp"
    # QA-115: si el commit cambia la bitácora, su «Actualizado» no es anterior al día del commit.
    fecha=()
    git diff-tree --no-commit-id --name-only -r "$commit" | grep -qx docs/registros/traspaso.md && fecha=(--fecha "$(git log -1 --format=%as "$commit")")
    # La forma `${a[@]+…}` evita el «unbound variable» de un array vacío con `set -u` en bash 3.2 (macOS).
    python3 "$bitacora_py" "$tmp" ${fecha[@]+"${fecha[@]}"} || { echo "bitácora: en el commit $(git log -1 --format='%h %s' "$commit")"; rm -f "$tmp"; exit 1; }
    rm -f "$tmp"
  done
done
exit 0
