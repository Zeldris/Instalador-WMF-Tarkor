#!/bin/bash
# QA-50: tras pasar `/code-review --max-findings all` sobre el diff contra main y arreglar lo que
# encuentre, marca el commit revisado. El gancho `.claude/hooks/revision-antes-de-main.sh` no deja
# crear ni fusionar un PR a main si la marca no es del mismo commit.
set -euo pipefail
raiz="$(git rev-parse --show-toplevel)"
if [ -n "$(git -C "$raiz" status --porcelain --untracked-files=no)" ]; then
  echo "Hay cambios sin commit: súbelos y vuelve a revisar antes de marcar." >&2
  exit 1
fi
# QA-91 (retro del 2026-10-17): sin retro no hay marca. La rama añade una `docs/registros/retro-*.md`
# desde que se separó de main, con su línea `**Estado` diciendo lo que decidió la usuaria (no «pendiente»).
base="$(git -C "$raiz" merge-base HEAD origin/main 2>/dev/null)" || {
  echo "No encuentro origin/main: git fetch origin main y vuelve a marcar." >&2
  exit 1
}
decidida=""
for retro in $(git -C "$raiz" diff --name-only --diff-filter=A "$base" HEAD -- 'docs/registros/retro-*.md'); do
  estado="$(grep -m1 '^\*\*Estado' "$raiz/$retro" || true)"
  if [ -n "$estado" ] && ! grep -qi 'pendiente' <<<"$estado"; then
    decidida="$retro"
  fi
done
if [ -z "$decidida" ]; then
  echo "Falta la retro: la rama no añade ninguna docs/registros/retro-*.md con su «**Estado» decidido por la" >&2
  echo "usuaria. Pasa /retro, preséntasela, aplica lo que apruebe y vuelve a marcar (CLAUDE.md, QA-91)." >&2
  exit 1
fi
git -C "$raiz" rev-parse HEAD > "$raiz/.claude/revision-main.sha"
echo "Revisado: $(cat "$raiz/.claude/revision-main.sha")"
