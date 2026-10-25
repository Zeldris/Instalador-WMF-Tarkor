#!/usr/bin/env bash
# galivelop-workflow v0.3.0
# After /code-review of the diff against the protected branch, with its fixes pushed: records HEAD's sha in the
# config's `reviewMark` and commits it ("Revisado: <sha>" / "Reviewed: <sha>" by `language`). The mark travels with
# the repo, so other accounts and scheduled tasks see it; .githooks/pre-push and the PR hook accept code up to it.
# With `requireRetro`, the branch must add a retro-*.md whose **Estado:**/**Status:** paragraph (from that line to the
# next blank line) records a decision: a whole word among aplicad*, rechazad*, aplazad*, decidid*, aprobad* (applied,
# rejected, deferred, decided, approved) and none of pendiente/pending/undecided/sin decidir/aún no/not yet.
# Files not tracked by git do not count as changes (drafts stay where they are); tracked edits do.
#   bash revisado.sh                      # then: git push
#   bash revisado.sh --footer "Siguiente: <next step>"   # last line of the mark commit, for a commit-msg hook that wants it
# Bash 3.2 compatible. Root from this script's path, never from the current directory.
set -uo pipefail
footer=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --footer) [ "$#" -ge 2 ] && [ -n "$2" ] || { echo "revisado: --footer needs a line; run: bash $0 --footer \"Siguiente: <next step>\"" >&2; exit 1; }
      footer="$2"; shift 2 ;;
    *) echo "revisado: unknown argument '$1'; usage: bash $0 [--footer \"<last line of the mark commit>\"]" >&2; exit 1 ;;
  esac
done
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
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  git status --short --untracked-files=no >&2
  echo "revisado: the tree has uncommitted changes to tracked files; commit and push them, review again, then: git add -u && git commit && git push" >&2
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
    # The whole paragraph of the Estado/Status line (up to the next blank line), not only its first line.
    status="$(git show "HEAD:$file" | awk '/^\*\*(Estado|Status)/ { on = 1 } on && /^[[:space:]]*$/ { exit } on { print }' || true)"
    # Whole words only ("undecided" is not "decided"; "spending" or "dependiente" is not "pending"), and a paragraph
    # that also says it is still pending is not a decision.
    if printf '%s\n' "$status" | grep -qiwE '(aplicad[ao]s?|rechazad[ao]s?|aplazad[ao]s?|decidid[ao]s?|aprobad[ao]s?|applied|rejected|deferred|decided|approved)' \
      && ! printf '%s\n' "$status" | grep -qiE '(^|[^[:alpha:]])(pendientes?|pending|undecided|sin decidir|aún no|not yet)([^[:alpha:]]|$)'; then
      decided="$file"
    fi
  done <<<"$added"
  if [ -z "$decided" ]; then
    echo "revisado: requireRetro is on and the branch adds no retro-*.md whose **Estado:**/**Status:** paragraph records" >&2
    echo "the user's decision. Valid whole words: aplicad*, rechazad*, aplazad*, decidid*, aprobad* (applied, rejected," >&2
    echo "deferred, decided, approved); 'done' alone is not enough, and pendiente/pending/undecided/sin decidir/aún no/" >&2
    echo "not yet as whole words anywhere in that paragraph (up to the next blank line) cancels it." >&2
    echo "Run /retro, present it, apply what the user approves, record it in the Status line, push and mark again: bash $0" >&2
    exit 1
  fi
fi

mkdir -p "$(dirname "$mark")"
printf '%s\n' "$head" > "$mark"
if [ "$language" = "es" ]; then subject="Revisado: $head"; else subject="Reviewed: $head"; fi
if [ -n "$footer" ]; then message="$subject"$'\n\n'"$footer"; else message="$subject"; fi
{ git add -- "$mark" && git commit -q -m "$message" -- "$mark"; } || {
  echo "revisado: could not commit $mark; see the error above, then retry: bash $0" >&2; exit 1; }
echo "$subject. Push it: git push"
