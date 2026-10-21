#!/bin/bash
# QA-135 (de Tarkor): fusiona una rama de subagente en la actual y comprueba el resultado en una salida corta.
# Uso: tools/qa/fusionar.sh <rama> "<mensaje del merge>" [--revisada]
#  - `git merge --no-ff`; con conflictos, para y los lista (el merge queda abierto).
#  - pasa los tests de lo tocado: en `app/src`, vitest de los archivos cambiados y los que los importan y `tsc -b`;
#    en `app/nucleo`, `cargo test -p tarkor-nucleo`; en `app/src-tauri`, `cargo check -p tarkor`.
#    Con tests en rojo el merge YA está hecho: dice cómo deshacerlo y sale con 1.
#  - QA-152: tras fusionar bien una rama `worktree-agent-*` (o cualquiera con worktree en .claude/worktrees/), borra
#    su worktree (`git worktree remove`, sin forzar: con cambios sin commitear avisa y lo deja) y la rama
#    (`git branch -d`, solo borra lo fusionado; si falla avisa y sigue). Nunca borra la rama actual, main ni `claude/*`.
#  - `--revisada` = la principal ya hizo revisar el diff (paso 3 de orchestrate-dealer); sin él, lo recuerda.
set -uo pipefail
[ $# -ge 2 ] && [ $# -le 3 ] && { [ $# -eq 2 ] || [ "$3" = "--revisada" ]; } || { echo "Uso: $0 <rama> \"<mensaje>\" [--revisada]" >&2; exit 2; }
rama="$1"; mensaje="$2"; revisada="${3:-}"
raiz="$(git rev-parse --show-toplevel)"; cd "$raiz"
logs="$(mktemp -d)"

git rev-parse --verify --quiet "$rama^{commit}" >/dev/null || { echo "No existe la rama $rama" >&2; exit 2; }
antes="$(git rev-parse HEAD)"
if ! git merge --no-ff "$rama" -m "$mensaje" >"$logs/merge.log" 2>&1; then
  conflictos="$(git diff --name-only --diff-filter=U)"
  echo "CONFLICTO (merge abierto: resuélvelo o git merge --abort):"
  echo "${conflictos:-$(tail -5 "$logs/merge.log")}" | sed 's/^/  /'
  exit 1
fi

if [ "$(git rev-parse HEAD)" = "$antes" ]; then
  echo "Nada que fusionar: $rama ya está en la rama actual."
  exit 0
fi

limpiar_rama() {
  local actual wt
  actual="$(git branch --show-current)"
  case "$rama" in main|claude/*) return 0 ;; esac
  [ "$rama" = "$actual" ] && return 0
  wt="$(git worktree list --porcelain | awk -v r="refs/heads/$rama" '/^worktree /{w=substr($0,10)} $1=="branch" && $2==r {print w}')"
  case "$rama" in
    worktree-agent-*) ;;
    *) case "$wt" in */.claude/worktrees/*) ;; *) return 0 ;; esac ;;
  esac
  if [ -n "$wt" ] && [ "$wt" != "$raiz" ]; then
    case "$wt" in
      */.claude/worktrees/*)
        git worktree remove "$wt" >"$logs/wt.log" 2>&1 \
          && echo "Worktree $wt borrado." \
          || { echo "AVISO: no borro el worktree $wt ($(head -1 "$logs/wt.log")); la rama $rama queda."; return 0; } ;;
      *) echo "AVISO: $rama tiene worktree fuera de .claude/worktrees/ ($wt); no lo borro."; return 0 ;;
    esac
  fi
  git branch -d "$rama" >"$logs/br.log" 2>&1 \
    && echo "Rama $rama borrada." \
    || echo "AVISO: no borro la rama $rama ($(head -1 "$logs/br.log"))."
  return 0
}

echo "Commit $(git rev-parse --short HEAD) · $(git log -1 --format=%s)"
cambiados="$(git diff --name-only HEAD^1 HEAD)"
PARTES="app/src app/nucleo app/src-tauri"
for parte in $PARTES; do
  n="$(grep -c "^$parte/" <<<"$cambiados")"
  [ "$n" -gt 0 ] && echo "  $parte: $n archivos"
done
otros="$(grep -vE '^app/(src|nucleo|src-tauri)/' <<<"$cambiados" | grep -c .)"
[ "$otros" -gt 0 ] && echo "  resto: $otros archivos"

fallo=0
for parte in $PARTES; do
  grep -q "^$parte/" <<<"$cambiados" || continue
  resultado="OK"
  case "$parte" in
    app/src)
      archivos=()
      while read -r f; do
        [ -f "$f" ] && archivos+=("${f#app/}")
      done < <(grep -E "^app/src/.*\.(ts|tsx)$" <<<"$cambiados")
      if [ ${#archivos[@]} -gt 0 ]; then
        (cd app && npx vitest related --run --passWithNoTests "${archivos[@]}" >"$logs/app.log" 2>&1) \
          || resultado="FAIL (log en $logs/app.log)"
      fi
      if [ "$resultado" = OK ]; then
        (cd app && npx tsc -b >"$logs/tsc.log" 2>&1) || resultado="FAIL tsc (log en $logs/tsc.log)"
      fi ;;
    app/nucleo)
      (cd app && cargo test -q -p tarkor-nucleo >"$logs/nucleo.log" 2>&1) || resultado="FAIL (log en $logs/nucleo.log)" ;;
    app/src-tauri)
      (cd app && cargo check -q -p tarkor >"$logs/tauri.log" 2>&1) || resultado="FAIL (log en $logs/tauri.log)" ;;
  esac
  echo "  tests $parte: $resultado"
  [ "$resultado" = OK ] || fallo=1
done

[ "$revisada" = "--revisada" ] || echo "Sin --revisada: confirma el /code-review del diff (paso 3 de orchestrate-dealer)."
if [ "$fallo" -ne 0 ]; then
  echo "TESTS EN ROJO: el merge YA está hecho en la rama actual. Para deshacerlo: git reset --hard HEAD^1"
  exit 1
fi
# Tras los tests: con ellos en rojo, `git reset --hard HEAD^1` necesita la rama para no perderla.
limpiar_rama
exit 0
