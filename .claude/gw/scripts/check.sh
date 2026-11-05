#!/usr/bin/env bash
# galivelop-workflow v0.5.0
# Runs the project's `check` (every command of .claude/gw.json, prefixed by `checkWrapper` exactly as the pre-push
# does) at the repo root with GW_PUSH_PROTECTED=false, stopping at the first failure, then prints a summary (each
# command, ok/FAILED, seconds). By default the commands run as always, with live output. With --quiet (-q, or
# GW_CHECK_QUIET=1/true/yes) their output goes straight into a log file (<git dir>/gw-check.log, or GW_CHECK_LOG, a
# relative path is taken from the current directory), appended command by command, and only the last GW_CHECK_TAIL
# lines (default 40) of the one that fails are shown, with the log path. When it all passes and the work tree did
# not change during the run, it records the tree it would commit (see check-green.sh), so the next push of that
# same tree skips the check. GW_CHECK_CACHE=0 leaves the cache alone.
#   bash scripts/check.sh [--quiet|-q]
# Bash 3.2 compatible. Root from this script's path, never from $CLAUDE_PROJECT_DIR or the current directory.
set -uo pipefail
orig_pwd="$PWD"
quiet=""
case "${GW_CHECK_QUIET:-}" in 1|true|yes) quiet=1 ;; esac
case "${1:-}" in
  --quiet|-q) quiet=1; shift ;;
esac
[ "$#" -eq 0 ] || { echo "check: unexpected argument '$1'; usage: bash $0 [--quiet|-q]" >&2; exit 2; }
tail_lines="${GW_CHECK_TAIL:-40}"
case "$tail_lines" in ''|*[!0-9]*) tail_lines=40 ;; esac
here="$(cd "$(dirname "$0")" && pwd)"
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE  # git exports GIT_DIR to hooks, also in a linked worktree
root="$(unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE; git -C "$here" rev-parse --show-toplevel 2>/dev/null)" || {
  echo "check: $here is not inside a git repository; reinstall the workflow: /gw-update" >&2; exit 1; }
cd "$root" || exit 1
if [ -d "$root/.claude/gw/scripts" ]; then scripts="$root/.claude/gw/scripts"; else scripts="$root/scripts"; fi
config="$scripts/config.py"
helper="$scripts/check-green.sh"
fail() {  # fail <message>: the message ends with the command that fixes it
  echo "check: $1" >&2
  exit 1
}
[ -f "$config" ] || fail "the workflow scripts are missing ($config); reinstall them: /gw-update"
checks="$(python3 "$config" --root "$root" get check)" || fail "cannot read 'check' from .claude/gw.json; fix the config: python3 $config --root $root validate"
wrapper="$(python3 "$config" --root "$root" get checkWrapper)" || fail "cannot read 'checkWrapper' from .claude/gw.json; fix the config: python3 $config --root $root validate"

key=""
tree_before=""
if [ "${GW_CHECK_CACHE:-}" != "0" ] && [ -f "$helper" ]; then  # any failure of the cache only means no recording
  # Its reason for not giving a tree (a skip-worktree entry, a modified submodule) goes to stderr: the check still runs.
  tree_before="$(bash "$helper" worktree-tree)" || tree_before=""
  if [ -n "$tree_before" ]; then
    key="$(printf '%s\n' "$checks" | bash "$helper" key "$tree_before" "$wrapper" 2>/dev/null)" || key=""
  fi
fi

log=""
if [ -n "$quiet" ]; then  # only --quiet writes the log; the default mode leaves the output alone
  log="${GW_CHECK_LOG:-}"
  if [ -z "$log" ]; then
    gitdir="$(git rev-parse --git-dir 2>/dev/null)" && gitdir="$(cd "$gitdir" 2>/dev/null && pwd)" || gitdir=""
    if [ -n "$gitdir" ]; then
      log="$gitdir/gw-check.log"
    else
      fail "cannot find the git dir for the log; set GW_CHECK_LOG to a writable file outside the work tree"
    fi
  fi
  case "$log" in /*) ;; *) log="$orig_pwd/$log" ;; esac
  case "$log" in
    "$root"/.git/*) ;;  # inside the git dir: not part of the tree
    "$root"/*)
      git check-ignore -q -- "$log" 2>/dev/null ||
        fail "the log $log is inside the work tree and would change it; set GW_CHECK_LOG to a path outside the work tree or git-ignored, e.g. GW_CHECK_LOG=\$(git rev-parse --git-dir)/gw-check.log" ;;
  esac
  : > "$log" 2>/dev/null || fail "cannot write the log $log; set GW_CHECK_LOG to a writable file"
fi
summary=""
failed_cmd=""
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  [ -z "$wrapper" ] || cmd="$wrapper bash -c '$(printf '%s' "$cmd" | sed "s/'/'\\\\''/g")'"
  echo "check: running '$cmd'"
  start=$SECONDS
  if [ -n "$quiet" ]; then
    printf '== %s\n' "$cmd" >> "$log"
    offset="$(wc -c < "$log" | tr -d ' ')"
    GW_PUSH_PROTECTED=false bash -c "$cmd" < /dev/null >> "$log" 2>&1
    rc=$?
  else
    GW_PUSH_PROTECTED=false bash -c "$cmd" < /dev/null
    rc=$?
  fi
  secs=$((SECONDS - start))
  if [ "$rc" -eq 0 ]; then
    summary="$summary  ok      ${secs}s  $cmd
"
  else
    summary="$summary  FAILED  ${secs}s  $cmd (exit $rc)
"
    failed_cmd="$cmd"
    break
  fi
done <<<"$checks"

echo "check: summary"
printf '%s' "$summary"
if [ -n "$failed_cmd" ]; then
  if [ -n "$quiet" ]; then
    echo "check: last $tail_lines lines of the failed command:"
    tail -c +"$((offset + 1))" "$log" | tail -n "$tail_lines"
    echo "check: full output: $log"
  fi
  fail "failed: '$failed_cmd'; fix it and run the whole check again: bash $0"
fi

if [ -z "$key" ]; then
  if [ "${GW_CHECK_CACHE:-}" = "0" ]; then
    echo "check: all green (not recorded for the pre-push: the cache is off; to record it: bash $0)"
  else
    echo "check: all green (not recorded for the pre-push: the cache is unavailable, see above; after fixing it: bash $0)"
  fi
  exit 0
fi
tree_after="$(bash "$helper" worktree-tree 2>/dev/null)" || tree_after=""
if [ "$tree_after" != "$tree_before" ]; then
  echo "check: all green, but the work tree changed during the run (${tree_before:0:7} -> ${tree_after:0:7}); not recorded, so the next push runs the check again. To record it: bash $0"
  exit 0
fi
bash "$helper" add "$key" < /dev/null
if bash "$helper" has "$key" > /dev/null 2>&1; then
  echo "check: all green on tree ${tree_before:0:7}; the next push of this same tree will skip the check (to run it anyway: GW_CHECK_CACHE=0 git push)"
else
  echo "check: all green, but it could not be recorded (see above); the next push will run the check again"
fi
