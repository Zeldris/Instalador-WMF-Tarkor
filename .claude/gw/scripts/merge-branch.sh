#!/usr/bin/env bash
# galivelop-workflow v0.6.0
# Merges a subagent's branch into the current one (merge, never rebase: branches are pushed), runs the config's
# `check` commands and the related tests (`relatedTests`) on the result and, if they pass, cleans up the subagent's
# worktree and branch.
#   bash merge-branch.sh <branch> "<merge message>" [--reviewed]
#  - Before merging it reads `check` (at least one command) and `checkWrapper` from the config; if it cannot, it
#    merges nothing and exits 2 (D77).
#  - `git merge --no-ff`. On conflict it stops, lists the files and leaves the merge open (resolve it, or abort
#    with: git merge --abort), exit 1. If the hand-off log (`log` of the config) is among them it says so (D86):
#    when it is the only one, the commands to join both sides (git merge-file --union) and close the merge, and the check and cleanup to run by hand afterwards; when there are others, that
#    the log is not the only conflict.
#  - then `check.sh --quiet` runs every `check` command of .claude/gw.json in the project root (E20): its registry
#    stays in <git common dir>/gw/check-<sha>.log (never deleted here), it shows that run's summary and the closing
#    `CHECK <ok|FAILED>: ...` line (not the last output lines), and a green is recorded for the pre-push. If it
#    fails the merge IS already done: it says how to undo it (git reset --hard HEAD^1) and exits 1; branch and
#    worktree stay.
#  - after a green check, the related tests the pre-push would run: related-tests.sh gets the files the merge
#    changed (git diff --name-only --no-renames <HEAD before the merge> HEAD) and runs the `relatedTests` commands
#    that apply (a no-op without `relatedTests`). If they fail it behaves like a failed check: the merge IS already
#    done, it says how to rerun them and how to undo the merge, exits 1; branch and worktree stay. If `relatedTests`
#    is configured but related-tests.sh is not installed it fails the same way (reinstall: /gw-update); with an
#    empty `relatedTests` a missing script is skipped silently.
#  - after a green check and green related tests: `git worktree remove` (without force: with uncommitted changes it warns and leaves it)
#    and `git branch -d` (deletes only what is merged; if it refuses it warns and goes on). Only a branch named
#    worktree-agent-* or agent/* (branchPrefixes.agent) or whose worktree is under .claude/worktrees/ is cleaned;
#    never the current branch, the protected branch or claude/* (branchPrefixes.keep: session branches). mergeCleanup
#    false skips the cleanup altogether.
#  - Refs (D16): the ids of the branch (the one in a name agent/<id>-<topic>, if it looks like a task id, and the
#    `Refs:` trailers of the commits it brings, read with git interpret-trailers) are joined with the ones the
#    message already has into ONE `Refs: A, B` trailer, without repeats; with no ids the message stays as it is.
#  - With `commitNext: true` the message must end in the next-step trailer (`Siguiente:` for language es, `Next:`
#    otherwise); without it the script stops before merging (exit 2). GW_NO_NEXT=1 skips that requirement.
#  - --reviewed = the main session already had the diff reviewed; without it, it reminds you.
# Bash 3.2 compatible. Root from this script's path, never from $CLAUDE_PROJECT_DIR or the current directory.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
usage() { echo "merge-branch: usage: bash $0 <branch> \"<merge message>\" [--reviewed]" >&2; exit 2; }
{ [ $# -eq 2 ] || { [ $# -eq 3 ] && [ "$3" = "--reviewed" ]; }; } || usage
branch="$1"; message="$2"; reviewed="${3:-}"
# Git exports GIT_DIR (and friends) to hooks, also in a linked worktree; with GIT_DIR set `rev-parse --show-toplevel`
# answers $here, not the repo root.
root="$(unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE; git -C "$here" rev-parse --show-toplevel 2>/dev/null)" || {
  echo "merge-branch: $here is not inside a git repository; reinstall the workflow: /gw-update" >&2; exit 2; }
cd "$root" || exit 2
config="$here/config.py"
protected="$(python3 "$config" --root "$root" get protectedBranch)" || {
  echo "merge-branch: cannot read protectedBranch; fix the config: python3 $config --root $root validate" >&2; exit 2; }
logs="$(mktemp -d "${TMPDIR:-/tmp}/gw-merge-branch.XXXXXX")" || { echo "merge-branch: cannot create a temp dir; free space and retry" >&2; exit 2; }
trap 'rm -rf "$logs"' EXIT

commit_next="$(python3 "$config" --root "$root" get commitNext 2>/dev/null)" || {
  echo "merge-branch: cannot read commitNext; fix the config: python3 $config --root $root validate" >&2; exit 2; }
if [ "$commit_next" = "true" ] && [ "${GW_NO_NEXT:-}" != "1" ]; then
  lang="$(python3 "$config" --root "$root" get language 2>/dev/null)" || {
    echo "merge-branch: cannot read language; fix the config: python3 $config --root $root validate" >&2; exit 2; }
  case "$lang" in es) next_word="Siguiente" ;; *) next_word="Next" ;; esac
  parsed="$(printf '%s\n' "$message" | git interpret-trailers --parse --no-divider)" || {
    echo "merge-branch: cannot read the trailers of the merge message (git interpret-trailers failed); update git or fix the message, then retry: bash $0 $branch \"<merge message>\"" >&2; exit 2; }
  if ! printf '%s\n' "$parsed" | grep -iq "^$next_word:[[:space:]]*[^[:space:]]"; then
    echo "merge-branch: the merge message has no \`$next_word:\` trailer (commitNext: true in .claude/gw.json); add a \`$next_word: <next step>\` line to its last paragraph and retry: bash $0 $branch \"<merge message>\"; for a message that legitimately has none: GW_NO_NEXT=1 bash $0 $branch \"<merge message>\"" >&2
    exit 2
  fi
fi

# Fail closed BEFORE merging (D77): the check that runs after the merge reads `check` and `checkWrapper`; if either
# cannot be read, or `check` has no command, the merge would be left done with no check to judge it.
checks="$(python3 "$config" --root "$root" get check 2>/dev/null)" || {
  echo "merge-branch: cannot read 'check' from .claude/gw.json, so nothing was merged; fix the config: python3 $config --root $root validate" >&2; exit 2; }
printf '%s\n' "$checks" | grep -q '[^[:space:]]' || {
  echo "merge-branch: 'check' in .claude/gw.json has no command, so nothing was merged; set at least one, e.g. \"check\": [\"bash tests/check.sh\"], then retry" >&2; exit 2; }
python3 "$config" --root "$root" get checkWrapper >/dev/null 2>&1 || {
  echo "merge-branch: cannot read 'checkWrapper' from .claude/gw.json, so nothing was merged; fix the config: python3 $config --root $root validate" >&2; exit 2; }

# Branch cleanup after the merge (A13): which branches it may delete (branchPrefixes.agent), which never (branchPrefixes.keep),
# and whether it cleans at all (mergeCleanup). Read before merging, so an unreadable key merges nothing.
agent_globs="$(python3 "$config" --root "$root" get branchPrefixes.agent 2>/dev/null)" || {
  echo "merge-branch: cannot read 'branchPrefixes.agent' from .claude/gw.json, so nothing was merged; fix the config: python3 $config --root $root validate" >&2; exit 2; }
keep_globs="$(python3 "$config" --root "$root" get branchPrefixes.keep 2>/dev/null)" || {
  echo "merge-branch: cannot read 'branchPrefixes.keep' from .claude/gw.json, so nothing was merged; fix the config: python3 $config --root $root validate" >&2; exit 2; }
merge_cleanup="$(python3 "$config" --root "$root" get mergeCleanup 2>/dev/null)" || {
  echo "merge-branch: cannot read 'mergeCleanup' from .claude/gw.json, so nothing was merged; fix the config: python3 $config --root $root validate" >&2; exit 2; }
glob_match() {  # glob_match <name> <globs, one per line>: 0 if the name matches one of them
  local pat
  while IFS= read -r pat; do
    [ -n "$pat" ] || continue
    # shellcheck disable=SC2254  # the glob is the point
    case "$1" in $pat) return 0 ;; esac
  done <<<"$2"
  return 1
}

git rev-parse --verify --quiet "$branch^{commit}" >/dev/null || { echo "merge-branch: no branch $branch; list them: git branch -a" >&2; exit 2; }
before="$(git rev-parse HEAD)"

# The ids the merge message carries as ONE `Refs:` trailer: the message's own, then the branch name's, then the
# `Refs:` of the commits the branch brings (oldest first). Values split on commas and whitespace; order kept, no repeats.
refs_fail() {
  echo "merge-branch: cannot read the Refs trailers ($1); update git (interpret-trailers needs 2.x) or fix the commit message, then retry: bash $0 $branch \"<merge message>\"" >&2
  exit 2
}
# Reads a message on stdin and prints its Refs values, one per line (git's own trailer parse; fails if git does).
refs_of() {
  local parsed
  parsed="$(git interpret-trailers --parse)" || return 1
  printf '%s\n' "$parsed" | awk -F: 'tolower($1)=="refs" {sub(/^[^:]*:/, ""); gsub(/[,[:space:]]+/, "\n"); print}' | grep -v '^$' || true
}
# `get taskId` gives the schema default when the project did not set the key (it fails only on an unreadable config,
# which the reads above already ruled out). Then the shape of a branch name's id applies, not handoff.py's `AB-12`: the
# id of `agent/<id>-<topic>` is cut at the first `-`, so it never looks like `AB-12` (A13 C5: kept, not unified).
id_pattern="$(python3 "$config" --root "$root" get taskId 2>/dev/null)" || id_pattern=""
id_default="$(python3 "$config" default taskId 2>/dev/null)" || id_default=""
if [ -z "$id_pattern" ] || [ "$id_pattern" = "$id_default" ]; then id_pattern='[A-Za-z]+[0-9]+'; fi
: > "$logs/ids"
# m = ids the message already carries (kept as given); c = the branch name's and the commits' (must look like an id).
printf '%s\n' "$message" | refs_of | sed 's/^/m /' >> "$logs/ids" ; [ "${PIPESTATUS[1]}" = 0 ] || refs_fail "the merge message"
case "$branch" in
  agent/*) name_id="${branch#agent/}"; echo "c ${name_id%%-*}" >> "$logs/ids" ;;
esac
for c in $(git rev-list --reverse --no-merges "HEAD..$branch" 2>/dev/null); do
  git show -s --format=%B "$c" | refs_of | sed 's/^/c /' >> "$logs/ids" ; [ "${PIPESTATUS[1]}" = 0 ] || refs_fail "commit $c"
done
joined="$(python3 -c '
import re, sys
pat, seen = sys.argv[1], []
for line in sys.stdin:
    kind, _, ident = line.rstrip("\n").partition(" ")
    if ident and ident not in seen and (kind == "m" or re.fullmatch(pat, ident)):
        seen.append(ident)
print(", ".join(seen))' "$id_pattern" < "$logs/ids")" || { echo "merge-branch: cannot build the Refs list; check that python3 works, then retry: bash $0 $branch \"<merge message>\"" >&2; exit 2; }
if [ -n "$joined" ]; then
  # Drop every Refs line of the last paragraph, then add ONE at the start of the trailer block so a final
  # `Siguiente:` line stays last.
  stripped="$(printf '%s\n' "$message" | awk '{l[NR]=$0} END {s=1; for (i=NR;i>=1;i--) if (l[i] ~ /^[[:space:]]*$/) {s=i+1; break}; for (i=1;i<=NR;i++) if (!(i>=s && tolower(l[i]) ~ /^refs:/)) print l[i]}')"
  message="$(printf '%s\n' "$stripped" | git interpret-trailers --where start --if-exists add --if-missing add --trailer "Refs: $joined")" \
    || refs_fail "writing the trailer"
fi

if ! git merge --no-ff "$branch" -m "$message" > "$logs/merge.log" 2>&1; then
  # core.quotePath=false: git quotes non-ASCII paths ("bit\303\241cora.md") and they would never match `log`.
  conflicts="$(git -c core.quotePath=false diff --name-only --diff-filter=U)"
  # D86: the hand-off log (`log` of the config) is the conflict of almost every parallel merge: say so and give the
  # commands. Only when it is NOT the only conflicted file do the others come first. The config was already
  # validated above, so if `log` still cannot be read the generic message below is all that is lost.
  log_file="$(python3 "$config" --root "$root" get log 2>/dev/null)" || log_file=""
  log_file="${log_file#./}"
  log_hit=""; others=""
  if [ -n "$log_file" ]; then
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      if [ "$f" = "$log_file" ]; then log_hit=1; else others="${others:+$others
}$f"; fi
    done <<EOF_CONFLICTS
$conflicts
EOF_CONFLICTS
  fi
  if [ -n "$log_hit" ]; then
    qlog="$(printf '%q' "$log_file")"
    wt="$(git worktree list --porcelain | awk -v r="refs/heads/$branch" '/^worktree /{w=substr($0,10)} $1=="branch" && $2==r {print w}')"
    if [ -z "$others" ]; then
      echo "merge-branch: CONFLICT only in the hand-off log ($log_file); the merge stays open. Both sides add entries to it, so join them (nothing is lost), review the result, then close the merge:"
    else
      echo "merge-branch: CONFLICT (the merge stays open; resolve it and commit, or abort with: git merge --abort):"
      printf '%s\n' "$conflicts" | sed 's/^/  /'
      echo "merge-branch: the hand-off log ($log_file) is one of them, but NOT the only one: resolve the other files by hand and git add them; for the log:"
    fi
    echo "  join both sides:  cd \"\$(git rev-parse --show-toplevel)\" && t=\$(mktemp -d) && git show :2:$qlog > \$t/ours && { git show :1:$qlog > \$t/base || : > \$t/base; } && git show :3:$qlog > \$t/theirs && git merge-file --union \$t/ours \$t/base \$t/theirs && cp \$t/ours $qlog && rm -rf \$t"
    echo "  then edit $qlog (duplicated rows, Siguiente/Next), and: python3 $here/handoff.py check && git add $qlog${others:+ <the other files>} && git commit --no-edit"
    echo "  WARNING: git checkout --ours -- $qlog (or --theirs) keeps one side and DROPS the other's entries; see what $branch brings with: git diff :1:$qlog :3:$qlog"
    echo "  to give up instead: git merge --abort"
    # What this script would do after the merge (see cleanup_branch below): worktree only if there is one, branch only if it is not protected, claude/* or the current one.
    after="bash $here/check.sh --quiet"
    [ "$merge_cleanup" != "true" ] || [ -z "$wt" ] || [ "$wt" = "$root" ] || after="$after && git worktree remove $(printf '%q' "$wt")"
    if [ "$merge_cleanup" = "true" ] && [ "$branch" != "$protected" ] && ! glob_match "$branch" "$keep_globs" && [ "$branch" != "$(git branch --show-current)" ]; then
      after="$after && git branch -d $(printf '%q' "$branch")"
    fi
    echo "  Closing it by hand skips what this script does after a merge (re-running it says \"nothing to merge\"); then run: $after"
  else
    echo "merge-branch: CONFLICT (the merge stays open; resolve it and commit, or abort with: git merge --abort):"
    printf '%s\n' "${conflicts:-$(tail -n 5 "$logs/merge.log")}" | sed 's/^/  /'
  fi
  exit 1
fi
if [ "$(git rev-parse HEAD)" = "$before" ]; then
  echo "merge-branch: nothing to merge, $branch is already in the current branch."
  exit 0
fi
echo "merge-branch: merged $branch into $(git branch --show-current) at $(git rev-parse --short HEAD)"

# The check is scripts/check.sh --quiet (E20): one registry per sha in <git common dir>/gw/check-<sha>.log that stays
# after the run, a lock against a second check, a closing `CHECK <ok|FAILED>: ...` line, and the green recorded for
# the pre-push (check-green.sh) so the push does not repeat it. Only its summary is shown here, never the tail.
check_script="$here/check.sh"
if [ ! -f "$check_script" ]; then
  echo "merge-branch: CHECK CANNOT RUN: $check_script is not installed. The merge is ALREADY done in the current branch; branch and worktree stay." >&2
  echo "merge-branch: reinstall the workflow with: /gw-update, or undo the merge with: git reset --hard HEAD^1" >&2
  exit 1
fi
bash "$check_script" --quiet > "$logs/check.out" 2> "$logs/check.err" < /dev/null
check_rc=$?
check_line="$(grep '^CHECK ' "$logs/check.out" "$logs/check.err" | tail -n 1 | sed 's/^[^:]*://')"
check_log="$(grep '^check: log: ' "$logs/check.out" | tail -n 1 | sed 's/^check: log: //')"
if [ "$check_rc" -eq 0 ]; then
  echo "merge-branch: check OK: ${check_line:-CHECK ok} (log: ${check_log:-unknown})"
else
  # The summary block (each command, ok/FAILED, seconds) and the closing CHECK line; the log has the rest.
  awk '/^check: summary/ {on=1; next} /^check: last / {on=0} on' "$logs/check.out" >&2
  if [ -n "$check_line" ]; then
    echo "merge-branch: $check_line" >&2
  else  # check.sh stopped before running anything (no CHECK line): its own message says why
    cat "$logs/check.err" >&2
    tail -n 5 "$logs/check.out" >&2
  fi
  echo "merge-branch: the check did not pass. The merge is ALREADY done in the current branch; branch and worktree stay." >&2
  [ -z "$check_log" ] || echo "merge-branch: full log: $check_log" >&2
  if [ "$check_rc" -eq 3 ]; then
    echo "merge-branch: another check holds the lock; once it ends rerun the check with: bash $check_script --quiet (or undo the merge with: git reset --hard HEAD^1)" >&2
  else
    echo "merge-branch: fix it and commit, or undo the merge with: git reset --hard HEAD^1" >&2
  fi
  exit 1
fi

# The related tests the pre-push would run, on the files this merge brought. Fail closed: with commands in
# `relatedTests` but related-tests.sh not installed they cannot run, so that is an error (with an empty
# `relatedTests` a missing script has nothing to run); also if the changed list cannot be built.
related_configured=""
for kind in fast slow; do
  value="$(python3 "$config" --root "$root" get "relatedTests.$kind" 2>/dev/null)" && [ -n "$value" ] && related_configured=1
done
if [ ! -f "$here/related-tests.sh" ]; then
  if [ -n "$related_configured" ]; then
    echo "merge-branch: RELATED TESTS CANNOT RUN: relatedTests is configured but $here/related-tests.sh is not installed. The merge is ALREADY done in the current branch; branch and worktree stay." >&2
    echo "merge-branch: reinstall the workflow with: /gw-update (then run the related tests), or undo the merge with: git reset --hard HEAD^1" >&2
    exit 1
  fi
else
  rerun="f=\$(mktemp) && git diff --name-only --no-renames ${before:0:7} HEAD > \"\$f\" && bash $here/related-tests.sh \"\$f\""
  git diff --name-only --no-renames "$before" HEAD > "$logs/changed" || {
    echo "merge-branch: cannot list the files the merge changed. The merge is ALREADY done in the current branch; branch and worktree stay." >&2
    echo "merge-branch: run the related tests by hand: $rerun" >&2
    exit 1; }
  if bash "$here/related-tests.sh" "$logs/changed" > "$logs/related.log" 2>&1 < /dev/null; then
    echo "merge-branch: related tests OK"
  else
    tail -n 20 "$logs/related.log" >&2
    echo "merge-branch: RELATED TESTS FAILED. The merge is ALREADY done in the current branch; branch and worktree stay." >&2
    echo "merge-branch: fix it and commit, or undo the merge with: git reset --hard HEAD^1" >&2
    echo "merge-branch: rerun them with: $rerun" >&2
    exit 1
  fi
fi

cleanup_branch() {
  local current wt
  current="$(git branch --show-current)"
  [ "$branch" = "$protected" ] && return 0
  glob_match "$branch" "$keep_globs" && return 0
  [ "$branch" = "$current" ] && return 0
  wt="$(git worktree list --porcelain | awk -v r="refs/heads/$branch" '/^worktree /{w=substr($0,10)} $1=="branch" && $2==r {print w}')"
  if ! glob_match "$branch" "$agent_globs"; then
    case "$wt" in */.claude/worktrees/*) ;; *) return 0 ;; esac
  fi
  if [ -n "$wt" ] && [ "$wt" != "$root" ]; then
    case "$wt" in
      */.claude/worktrees/*)
        if git worktree remove "$wt" > "$logs/wt.log" 2>&1; then
          echo "merge-branch: worktree $wt removed."
        else
          echo "merge-branch: WARNING: worktree $wt not removed ($(head -n 1 "$logs/wt.log")); $branch stays. Fix it: git worktree remove --force $wt"
          return 0
        fi ;;
      *) echo "merge-branch: WARNING: $branch has a worktree outside .claude/worktrees/ ($wt); not removed."; return 0 ;;
    esac
  fi
  if git branch -d "$branch" > "$logs/br.log" 2>&1; then
    echo "merge-branch: branch $branch deleted."
  else
    echo "merge-branch: WARNING: branch $branch not deleted ($(head -n 1 "$logs/br.log")); check it: git branch --no-merged"
  fi
  return 0
}
if [ "$merge_cleanup" = "true" ]; then
  cleanup_branch
else
  echo "merge-branch: mergeCleanup is false: worktree and branch $branch stay; remove them by hand when done."
fi
[ "$reviewed" = "--reviewed" ] || echo "merge-branch: no --reviewed: confirm the /code-review of the diff (step 3 of gw-orchestrate-dealer)."
exit 0
