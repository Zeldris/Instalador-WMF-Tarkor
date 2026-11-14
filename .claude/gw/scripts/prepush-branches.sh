#!/usr/bin/env bash
# galivelop-workflow v0.6.0
# What pre-push checks about the hand-off log of each branch it pushes (for projects with "logRows": true; a no-op
# otherwise). Called by .githooks/pre-push as:   prepush-branches.sh <changed-files-file> <pushed-commits-file>
# with git's ref lines ("local-ref local-sha remote-ref remote-sha" per ref) on stdin. For each pushed ref:
#   - appends to $1 the files that change (from what the remote branch already has; else from where it forked from
#     origin/<protectedBranch>; else, in a single-branch clone with neither, from the commits no remote has) and, if $2 is
#     empty, writes to it the new commits, one sha per line;
#   - handoff.py closed: tasks closed in the plan are also listed in "Done" (only against the remote branch);
#   - handoff.py in-progress: WARNING for 🚧 tasks the commits name whose plan entry did not change;
#   - handoff.py own-row: no new commit changes another branch's row or a shared one (BITACORA_COMPARTIDA=1 or
#     GW_SHARED_LOG=1 allows it); the branch is the remote one pushed to, or the current one; a commit that comes
#     from another local branch (a sub-branch merged back) may write in that branch's row instead;
#   - handoff.py clash: no task id the branch opens in the plan is also a different task on origin/<protectedBranch>,
#     and no new merge kept two tasks under one id (a WARNING for the 10 most recent other remote branches);
#   - handoff.py check: the log as the pushed tip has it (not the working copy; a later commit fixes an earlier
#     one's): rows well formed, <= 600 characters, one per branch, and "Updated" not older than the newest new
#     commit that changes the log.
# Plan folder and task-id regex: GW_PLAN and GW_TASK_ID (see handoff.py). Exit 1 if a rule is broken.
# Bash 3.2 compatible. Root from this script's path, never from $CLAUDE_PROJECT_DIR or the current directory.
set -uo pipefail
if [ "$#" -ne 2 ]; then
  echo "prepush-branches: usage: prepush-branches.sh <changed-files-file> <pushed-commits-file>" >&2; exit 2
fi
changed="$1"
pushed="$2"
here="$(cd "$(dirname "$0")" && pwd)"
# Git exports GIT_DIR (and friends) to hooks, also in a linked worktree; with GIT_DIR set `rev-parse --show-toplevel`
# answers $here, not the repo root.
root="$(unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE; git -C "$here" rev-parse --show-toplevel 2>/dev/null)" || {
  echo "prepush-branches: $here is not inside a git repository; reinstall the workflow: /gw-update" >&2; exit 2; }
cd "$root" || exit 2
config="$here/config.py"
handoff="$here/handoff.py"
rows="$(python3 "$config" --root "$root" get logRows)" || {
  echo "prepush-branches: cannot read logRows; fix the config: python3 $config --root $root validate" >&2; exit 1; }
[ "$rows" = "true" ] || exit 0
log="$(python3 "$config" --root "$root" get log)" || {
  echo "prepush-branches: cannot read log; fix the config: python3 $config --root $root validate" >&2; exit 1; }
protected="$(python3 "$config" --root "$root" get protectedBranch)" || {
  echo "prepush-branches: cannot read protectedBranch; fix the config: python3 $config --root $root validate" >&2; exit 1; }
zero=0000000000000000000000000000000000000000
handoff() { python3 "$handoff" --root "$root" "$@"; }

shared=()
{ [ -n "${BITACORA_COMPARTIDA:-}" ] || [ -n "${GW_SHARED_LOG:-}" ]; } && shared=(--shared)
pushed_was_empty=""
[ -s "$pushed" ] || pushed_was_empty=1

while read -r local_ref sha_local remote_ref sha_remote; do
  [ -n "${sha_local:-}" ] || continue
  [ "$sha_local" = "$zero" ] && continue
  case "$local_ref" in refs/tags/*) continue ;; esac
  case "$remote_ref" in refs/tags/*) continue ;; esac
  git cat-file -e "$sha_local^{commit}" 2>/dev/null || { echo "prepush-branches: commit $sha_local is not in this clone; fetch it: git fetch" >&2; exit 1; }

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
    if [ -n "$against_remote" ]; then handoff closed "$base" "$sha_local" || exit 1; fi
    handoff in-progress "$base" "$sha_local"
  fi

  branch="${remote_ref#refs/heads/}"
  { [ -n "$branch" ] && [ "$branch" != "$remote_ref" ]; } || branch="$(git branch --show-current 2>/dev/null)"

  # A task id this branch opens that the protected branch (or a merge of it) also took for another task; other
  # remote branches, the prepushClashBranches (10) most recent, only warn (they may never be merged).
  if git rev-parse -q --verify "refs/remotes/origin/$protected^{commit}" >/dev/null 2>&1; then
    handoff clash "$sha_local" "refs/remotes/origin/$protected" || exit 1
  fi
  while IFS= read -r commit; do
    [ -n "$commit" ] || continue
    handoff clash --merge "$commit" --tip "$sha_local" || { echo "handoff: in merge $(git log -1 --format='%h %s' "$commit")"; exit 1; }
  done <<<"$(git rev-list --merges "$sha_local" --not --remotes 2>/dev/null)"
  # prepushClashBranches as the pushed commit has it, not the working copy
  clash_branches="$(python3 "$config" --root "$root" --rev "$sha_local" get prepushClashBranches)" || {
    echo "prepush-branches: cannot read prepushClashBranches from .claude/gw.json in commit ${sha_local:0:7}; commit a valid one: python3 $config --root $root --rev ${sha_local:0:7} validate" >&2; exit 1; }
  case "$clash_branches" in ''|*[!0-9]*|0) echo "prepush-branches: prepushClashBranches must be a whole number of 1 or more, got '$clash_branches'; fix .claude/gw.json" >&2; exit 1 ;; esac
  others=()
  while IFS= read -r ref; do
    case "$ref" in ""|refs/remotes/origin/HEAD|"refs/remotes/origin/$protected"|"refs/remotes/origin/$branch") continue ;; esac
    others+=("$ref")
    [ "${#others[@]}" -ge "$clash_branches" ] && break
  done <<<"$(git for-each-ref --sort=-committerdate --format='%(refname)' refs/remotes/origin/ 2>/dev/null)"
  if [ "${#others[@]}" -gt 0 ]; then handoff clash --warn "$sha_local" "${others[@]}"; fi

  # Own row: the log of each new commit that is not a merge (merges bring rows from the protected branch or others).
  while IFS= read -r commit; do
    [ -n "$commit" ] || continue
    git diff-tree --no-commit-id --name-only -r "$commit" | grep -qxF "$log" || continue
    handoff own-row "$commit" "$branch" ${shared[@]+"${shared[@]}"} >/dev/null 2>&1 && continue
    ok=""
    while IFS= read -r other; do
      case "$other" in ""|"$branch"|"$protected"|"("*) continue ;; esac
      if handoff own-row "$commit" "$other" ${shared[@]+"${shared[@]}"} >/dev/null 2>&1; then ok=1; break; fi
    done <<<"$(git branch --contains "$commit" --format='%(refname:short)' 2>/dev/null)"
    [ -n "$ok" ] || handoff own-row "$commit" "$branch" ${shared[@]+"${shared[@]}"} \
      || { echo "handoff: in commit $(git log -1 --format='%h %s' "$commit")"; exit 1; }
  done <<<"$(git rev-list --no-merges "$sha_local" --not --remotes 2>/dev/null)"

  # Well-formed log as pushed (the tip's): a later commit fixes an intermediate one's bad log, as the hint says.
  # "Updated" is checked against the day of the newest new commit that changes the log.
  if [ -n "$new" ] && git cat-file -e "$sha_local:$log" 2>/dev/null; then
    last=""
    while IFS= read -r commit; do
      [ -n "$commit" ] || continue
      git diff-tree --no-commit-id --name-only -r "$commit" | grep -qxF "$log" && last="$commit"
    done <<<"$new"
    tmp="$(mktemp "${TMPDIR:-/tmp}/gw-log.XXXXXX")"
    git show "$sha_local:$log" > "$tmp"
    date=()
    [ -n "$last" ] && date=(--date "$(git log -1 --format=%as "$last")")
    if ! handoff check "$tmp" --at push ${date[@]+"${date[@]}"}; then
      echo "handoff: in commit $(git log -1 --format='%h %s' "$sha_local")"; rm -f "$tmp"; exit 1
    fi
    rm -f "$tmp"
  fi
done
sort -u -o "$changed" "$changed"
exit 0
