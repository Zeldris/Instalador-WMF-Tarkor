#!/usr/bin/env bash
# galivelop-workflow v0.3.0
# What pre-push checks about the hand-off log of each branch it pushes (for projects with "logRows": true; a no-op
# otherwise). Called by .githooks/pre-push as:   prepush-ramas.sh <changed-files-file> <pushed-commits-file>
# with git's ref lines ("local-ref local-sha remote-ref remote-sha" per ref) on stdin. For each pushed ref:
#   - appends to $1 the files that change (from what the remote branch already has; else from where it forked from
#     origin/<protectedBranch>; else, in a single-branch clone with neither, from the commits no remote has) and, if $2 is
#     empty, writes to it the new commits, one sha per line;
#   - bitacora.py closed: tasks closed in the plan are also listed in "Done" (only against the remote branch);
#   - bitacora.py in-progress: WARNING for 🚧 tasks the commits name whose plan entry did not change;
#   - bitacora.py own-row: no new commit changes another branch's row or a shared one (BITACORA_COMPARTIDA=1 or
#     GW_SHARED_LOG=1 allows it); the branch is the remote one pushed to, or the current one; a commit that comes
#     from another local branch (a sub-branch merged back) may write in that branch's row instead;
#   - bitacora.py check: the log as each new commit has it (not the working copy): rows well formed, <= 600
#     characters, one per branch, and "Updated" not older than the commit if the commit changes the log.
# Plan folder and task-id regex: GW_PLAN and GW_TASK_ID (see bitacora.py). Exit 1 if a rule is broken.
# Bash 3.2 compatible. Root from this script's path, never from $CLAUDE_PROJECT_DIR or the current directory.
set -uo pipefail
if [ "$#" -ne 2 ]; then
  echo "prepush-ramas: usage: prepush-ramas.sh <changed-files-file> <pushed-commits-file>" >&2; exit 2
fi
changed="$1"
pushed="$2"
here="$(cd "$(dirname "$0")" && pwd)"
root="$(git -C "$here" rev-parse --show-toplevel 2>/dev/null)" || {
  echo "prepush-ramas: $here is not inside a git repository; reinstall the workflow: /gw-update" >&2; exit 2; }
cd "$root" || exit 2
config="$here/config.py"
bitacora="$here/bitacora.py"
rows="$(python3 "$config" --root "$root" get logRows)" || {
  echo "prepush-ramas: cannot read logRows; fix the config: python3 $config --root $root validate" >&2; exit 1; }
[ "$rows" = "true" ] || exit 0
log="$(python3 "$config" --root "$root" get log)" || {
  echo "prepush-ramas: cannot read log; fix the config: python3 $config --root $root validate" >&2; exit 1; }
protected="$(python3 "$config" --root "$root" get protectedBranch)" || {
  echo "prepush-ramas: cannot read protectedBranch; fix the config: python3 $config --root $root validate" >&2; exit 1; }
zero=0000000000000000000000000000000000000000
bita() { python3 "$bitacora" --root "$root" "$@"; }

shared=()
{ [ -n "${BITACORA_COMPARTIDA:-}" ] || [ -n "${GW_SHARED_LOG:-}" ]; } && shared=(--shared)
pushed_was_empty=""
[ -s "$pushed" ] || pushed_was_empty=1

while read -r local_ref sha_local remote_ref sha_remote; do
  [ -n "${sha_local:-}" ] || continue
  [ "$sha_local" = "$zero" ] && continue
  case "$local_ref" in refs/tags/*) continue ;; esac
  case "$remote_ref" in refs/tags/*) continue ;; esac
  git cat-file -e "$sha_local^{commit}" 2>/dev/null || { echo "prepush-ramas: commit $sha_local is not in this clone; fetch it: git fetch" >&2; exit 1; }

  # Where to look from: what the remote branch has if that commit is here; else where it forked from the protected
  # branch.
  base=""
  if [ "$sha_remote" != "$zero" ] && git cat-file -e "$sha_remote^{commit}" 2>/dev/null; then
    base="$sha_remote"
  else
    base="$(git merge-base "$sha_local" "refs/remotes/origin/$protected" 2>/dev/null || echo "")"
  fi
  # The commits no remote-tracking ref has (a single-branch clone may lack origin/<protected>: this is the fallback).
  new="$(git rev-list --reverse "$sha_local" --not --remotes 2>/dev/null)"
  against_remote=""
  [ -n "$base" ] && [ "$base" = "$sha_remote" ] && against_remote=1
  if [ -n "$base" ]; then
    git diff --name-only "$base" "$sha_local" >> "$changed" 2>/dev/null
  else
    git log -m --name-only --no-renames --format= "$sha_local" --not --remotes 2>/dev/null | grep . >> "$changed"
    oldest="$(printf '%s\n' "$new" | head -n 1)"
    [ -n "$oldest" ] && base="$(git rev-parse -q --verify "$oldest^" 2>/dev/null || echo "")"
  fi
  if [ -n "$pushed_was_empty" ] && [ -n "$new" ]; then printf '%s\n' "$new" >> "$pushed"; fi

  if [ -n "$base" ]; then
    # Only against the remote branch: from the protected branch it would ask for tasks that already left the Done section.
    if [ -n "$against_remote" ]; then bita closed "$base" "$sha_local" || exit 1; fi
    bita in-progress "$base" "$sha_local"
  fi

  branch="${remote_ref#refs/heads/}"
  { [ -n "$branch" ] && [ "$branch" != "$remote_ref" ]; } || branch="$(git branch --show-current 2>/dev/null)"

  # Own row: the log of each new commit that is not a merge (merges bring rows from the protected branch or others).
  while IFS= read -r commit; do
    [ -n "$commit" ] || continue
    git diff-tree --no-commit-id --name-only -r "$commit" | grep -qxF "$log" || continue
    bita own-row "$commit" "$branch" ${shared[@]+"${shared[@]}"} >/dev/null 2>&1 && continue
    ok=""
    while IFS= read -r other; do
      case "$other" in ""|"$branch"|"$protected"|"("*) continue ;; esac
      if bita own-row "$commit" "$other" ${shared[@]+"${shared[@]}"} >/dev/null 2>&1; then ok=1; break; fi
    done <<<"$(git branch --contains "$commit" --format='%(refname:short)' 2>/dev/null)"
    [ -n "$ok" ] || bita own-row "$commit" "$branch" ${shared[@]+"${shared[@]}"} \
      || { echo "bitacora: in commit $(git log -1 --format='%h %s' "$commit")"; exit 1; }
  done <<<"$(git rev-list --no-merges "$sha_local" --not --remotes 2>/dev/null)"

  # Well-formed log in every new commit (an intermediate one with a bad log would also reach the remote).
  while IFS= read -r commit; do
    [ -n "$commit" ] || continue
    git cat-file -e "$commit:$log" 2>/dev/null || continue
    tmp="$(mktemp "${TMPDIR:-/tmp}/gw-log.XXXXXX")"
    git show "$commit:$log" > "$tmp"
    date=()
    git diff-tree --no-commit-id --name-only -r "$commit" | grep -qxF "$log" && date=(--date "$(git log -1 --format=%as "$commit")")
    if ! bita check "$tmp" ${date[@]+"${date[@]}"}; then
      echo "bitacora: in commit $(git log -1 --format='%h %s' "$commit")"; rm -f "$tmp"; exit 1
    fi
    rm -f "$tmp"
  done <<<"$new"
done
sort -u -o "$changed" "$changed"
exit 0
