#!/usr/bin/env bash
# galivelop-workflow v0.2.0
# After /code-review of the diff against the protected branch, with its fixes pushed: records HEAD's sha in the
# config's `reviewMark` and commits it ("Revisado: <sha>" / "Reviewed: <sha>" by `language`). The mark travels with
# the repo, so other accounts and scheduled tasks see it; .githooks/pre-push and the PR hook accept code up to it.
# With `requireRetro`, the branch must add a retro-*.md whose **Estado:**/**Status:** line records a decision.
#   bash revisado.sh      # then: git push
# Bash 3.2 compatible. Root from this script's path, never from the current directory.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(git -C "$here" rev-parse --show-toplevel 2>/dev/null)" || {
  echo "revisado: $here is not inside a git repository; reinstall the workflow: /gw-update" >&2; exit 1; }
cd "$root" || exit 1
config="$here/config.py"
cfg() {
  python3 "$config" --root "$root" get "$1" || {
    echo "revisado: cannot read '$1' from the config; fix it: python3 $config --root $root validate" >&2; return 1; }
}
protected="$(cfg protectedBranch)" || exit 1
mark="$(cfg reviewMark)" || exit 1
language="$(cfg language)" || exit 1
retro="$(cfg requireRetro)" || exit 1

branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$branch" = "HEAD" ]; then
  echo "revisado: detached HEAD; switch to your working branch first: git switch <branch>" >&2; exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  git status --short >&2
  echo "revisado: the tree has uncommitted or untracked changes; commit and push them, review again, then: git add -A && git commit && git push" >&2
  exit 1
fi
git fetch -q origin "$protected" "$branch" || {
  echo "revisado: cannot fetch origin/$protected and origin/$branch; push the branch first: git push -u origin $branch" >&2; exit 1; }
head="$(git rev-parse HEAD)"
if [ "$head" != "$(git rev-parse -q --verify "refs/remotes/origin/$branch")" ]; then
  echo "revisado: HEAD is not what origin/$branch has; push the fixes before marking: git push -u origin $branch" >&2; exit 1
fi
if ! git merge-base --is-ancestor "refs/remotes/origin/$protected" HEAD; then
  echo "revisado: the branch does not include the latest origin/$protected; merge it, review again and mark: git merge origin/$protected" >&2
  exit 1
fi

if [ "$retro" = "true" ]; then
  base="$(git merge-base HEAD "refs/remotes/origin/$protected")" || {
    echo "revisado: no common history with origin/$protected; fetch more: git fetch --deepen=200 origin $protected" >&2; exit 1; }
  decided=""
  added="$(git diff --no-renames --name-only --diff-filter=A "$base" HEAD | grep -E '(^|/)retro-[^/]*\.md$' || true)"
  while IFS= read -r file; do
    [ -n "$file" ] || continue
    status="$(git show "HEAD:$file" | grep -m1 -E '^\*\*(Estado|Status)' || true)"
    # Whole words only ("undecided" is not "decided"), and a line that also says it is still pending is not a decision.
    if printf '%s\n' "$status" | grep -qiwE '(aplicad[ao]s?|rechazad[ao]s?|aplazad[ao]s?|decidid[ao]s?|applied|rejected|deferred|decided)' \
      && ! printf '%s\n' "$status" | grep -qiE 'pendiente|pending|undecided|sin decidir|aún no|not yet'; then
      decided="$file"
    fi
  done <<<"$added"
  if [ -z "$decided" ]; then
    echo "revisado: requireRetro is on and the branch adds no retro-*.md whose **Estado:**/**Status:** line records" >&2
    echo "the user's decision (applied, rejected, deferred or decided; 'pending' or 'done' alone is not enough)." >&2
    echo "Run /retro, present it, apply what the user approves, record it in the Status line, push and mark again: bash $0" >&2
    exit 1
  fi
fi

mkdir -p "$(dirname "$mark")"
printf '%s\n' "$head" > "$mark"
if [ "$language" = "es" ]; then subject="Revisado: $head"; else subject="Reviewed: $head"; fi
{ git add -- "$mark" && git commit -q -m "$subject" -- "$mark"; } || {
  echo "revisado: could not commit $mark; see the error above, then retry: bash $0" >&2; exit 1; }
echo "$subject. Push it: git push"
