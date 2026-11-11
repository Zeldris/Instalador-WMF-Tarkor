#!/usr/bin/env bash
# galivelop-workflow v0.5.1
# Runs the project's `check` (every command of .claude/gw.json, prefixed by `checkWrapper` exactly as the pre-push
# does) at the repo root with GW_PUSH_PROTECTED=false, stopping at the first failure, then prints a summary (each
# command, ok/FAILED, seconds) and ends with one line `CHECK <ok|FAILED>: <what failed>`.
# The output of every command always goes to a log: <git common dir>/gw/check-<sha>.log (<sha> = HEAD, plus -dirty
# when the work tree has changes; GW_CHECK_LOG overrides the path, a relative one is taken from the current
# directory), also shown live unless --quiet (-q, or GW_CHECK_QUIET=1/true/yes): then only the last GW_CHECK_TAIL
# lines (default 40) of the command that fails are shown, with the log path. The log of a run is never deleted by
# the scripts. A lock <git common dir>/gw/check.lock (the pid and sha of the run) keeps two checks from running at
# once (check-green.sh lock-acquire; the pre-push takes the same one): a second one waits up to `checkLockWait`
# seconds (.claude/gw.json, default 0 = no wait) and then exits 3 saying which pid/sha runs; a lock whose process is
# gone (or whose pid is now another process) is discarded; Ctrl-C or a kill releases it. The failed line names the
# sections that failed: the `FAILED: <section>` lines the command printed.
# When it all passes and the work tree did not change during the run, it records the tree it would commit (see
# check-green.sh), so the next push of that same tree skips the check. GW_CHECK_CACHE=0 leaves the cache alone.
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
inputs=""
input_paths=""
tree_before=""
if [ "${GW_CHECK_CACHE:-}" != "0" ] && [ -f "$helper" ]; then  # any failure of the cache only means no recording
  # Its reason for not giving a tree (a skip-worktree entry, a modified submodule) goes to stderr: the check still runs.
  tree_before="$(bash "$helper" worktree-tree)" || tree_before=""
  if [ -n "$tree_before" ]; then
    # E23: the ignored files the check reads (checkCacheInputs) are part of the key, as the tree does not see them.
    # A list that cannot be read means no recording (fail closed), not a key without the inputs.
    if input_paths="$(python3 "$config" --root "$root" get checkCacheInputs)" && inputs="$(printf '%s\n' "$input_paths" | bash "$helper" inputs "$root")"; then
      key="$(printf '%s\n' "$checks" | bash "$helper" key "$tree_before" "$wrapper" "$inputs" 2>/dev/null)" || key=""
    else
      echo "check: cannot key the files of 'checkCacheInputs' (see above if it says why), so this green is not recorded; fix the config: python3 $config --root $root validate" >&2
    fi
  fi
fi

# --- the log and the lock live in <git common dir>/gw (shared by linked worktrees)
common="$(git rev-parse --git-common-dir 2>/dev/null)" && common="$(cd "$common" 2>/dev/null && pwd)" || common=""
[ -n "$common" ] || fail "cannot find the git dir (the log and the lock live in <git common dir>/gw); run it inside the repository: cd $root && bash $0"
gwdir="$common/gw"
mkdir -p "$gwdir" 2>/dev/null || fail "cannot create $gwdir; make the git dir writable, e.g. chmod u+w $common"
sha="$(git rev-parse --short=12 HEAD 2>/dev/null)" || sha="nohead"
[ -z "$(git status --porcelain 2>/dev/null | head -n 1)" ] || sha="$sha-dirty"
log="${GW_CHECK_LOG:-$gwdir/check-$sha.log}"
case "$log" in /*) ;; *) log="$orig_pwd/$log" ;; esac
case "$log" in
  "$root"/.git/*) ;;  # inside the git dir: not part of the tree
  "$root"/*)
    git check-ignore -q -- "$log" 2>/dev/null ||
      fail "the log $log is inside the work tree and would change it; set GW_CHECK_LOG to a path outside the work tree or git-ignored, e.g. GW_CHECK_LOG=$gwdir/check.log" ;;
esac

lock_wait="$(python3 "$config" --root "$root" get checkLockWait 2>/dev/null)" || lock_wait=0
case "$lock_wait" in ''|*[!0-9]*) lock_wait=0 ;; esac
grace="$(python3 "$config" --root "$root" get checkOutputGrace 2>/dev/null)" || grace=5
case "$grace" in ''|*[!0-9]*) grace=5 ;; esac
[ -f "$helper" ] || fail "$helper is missing, so the check cannot take its lock; reinstall the workflow: /gw-update"
have_lock=""
fifos=""
tee_out=""
tee_err=""
cleanup_output() {  # stops the output tees and removes their fifos
  [ -z "$tee_out$tee_err" ] || kill $tee_out $tee_err 2>/dev/null
  [ -z "$fifos" ] || rm -rf "$fifos"
  fifos=""; tee_out=""; tee_err=""
}
# shellcheck disable=SC2317,SC2329  # called from the traps below
release() {  # drops the lock only if it is still ours (check-green.sh checks the owner)
  cleanup_output
  [ -z "$have_lock" ] || bash "$helper" lock-release "$$" < /dev/null
  have_lock=""
}
trap 'release' EXIT
trap 'release; exit 130' INT
trap 'release; exit 143' TERM
bash "$helper" lock-acquire "$$" "$sha" "$lock_wait" "$log" < /dev/null
lrc=$?
[ "$lrc" -eq 0 ] || { [ "$lrc" -eq 3 ] && exit 3; exit 1; }
have_lock=1

: > "$log" 2>/dev/null || fail "cannot write the log $log; set GW_CHECK_LOG to a writable file"
echo "check: log: $log"
summary=""
failed_cmd=""
failed_section=""
while IFS= read -r cmd; do
  [ -n "$cmd" ] || continue
  [ -z "$wrapper" ] || cmd="$wrapper bash -c '$(printf '%s' "$cmd" | sed "s/'/'\\\\''/g")'"
  echo "check: running '$cmd'"
  start=$SECONDS
  printf '== %s\n' "$cmd" >> "$log"
  offset="$(wc -c < "$log" | tr -d ' ')"
  if [ -n "$quiet" ]; then
    GW_PUSH_PROTECTED=false bash -c "$cmd" < /dev/null >> "$log" 2>&1
    rc=$?
  else
    # live output, also into the log; stdout and stderr stay on their own streams (two fifos, two tees)
    { fifos="$(mktemp -d "${TMPDIR:-/tmp}/gw-check-fifo.XXXXXX")" && mkfifo "$fifos/out" "$fifos/err"; } || fail "cannot create a fifo in ${TMPDIR:-/tmp}; free space or set TMPDIR to a writable folder"
    tee -a "$log" < "$fifos/out" &
    tee_out=$!
    tee -a "$log" >&2 < "$fifos/err" &
    tee_err=$!
    GW_PUSH_PROTECTED=false bash -c "$cmd" < /dev/null > "$fifos/out" 2> "$fifos/err"
    rc=$?
    # A background child of the command that kept the output open would hold the tees forever: wait for them at most
    # `checkOutputGrace` seconds, then stop them.
    waited=0
    while [ "$waited" -lt $((grace * 10)) ] && { kill -0 "$tee_out" 2>/dev/null || kill -0 "$tee_err" 2>/dev/null; }; do
      sleep 0.1
      waited=$((waited + 1))
    done
    cleanup_output
  fi
  secs=$((SECONDS - start))
  if [ "$rc" -eq 0 ]; then
    summary="$summary  ok      ${secs}s  $cmd
"
  else
    summary="$summary  FAILED  ${secs}s  $cmd (exit $rc)
"
    failed_cmd="$cmd"
    # The sections that failed are the lines `FAILED: <section>` the command prints (one per failed section); with
    # none, no section is named.
    failed_section="$(tail -c +"$((offset + 1))" "$log" | sed -n 's/^FAILED: //p' | awk '{printf "%s%s", (n++ ? ", " : ""), $0}')"
    break
  fi
done <<<"$checks"

echo "check: summary"
printf '%s' "$summary"
if [ -n "$failed_cmd" ]; then
  if [ -n "$quiet" ]; then
    echo "check: last $tail_lines lines of the failed command:"
    tail -c +"$((offset + 1))" "$log" | tail -n "$tail_lines"
  fi
  echo "check: full output: $log"
  echo "check: failed: '$failed_cmd'; fix it and run the whole check again: bash $0" >&2
  echo "CHECK FAILED: $failed_cmd${failed_section:+ (failed: $failed_section)}" | tee -a "$log"
  exit 1
fi

finish_ok() {  # finish_ok <message>: the CHECK line is always the last one
  echo "$1"
  echo "CHECK ok: nothing failed" | tee -a "$log"
  exit 0
}
if [ -z "$key" ]; then
  if [ "${GW_CHECK_CACHE:-}" = "0" ]; then
    finish_ok "check: all green (not recorded for the pre-push: the cache is off; to record it: bash $0)"
  else
    finish_ok "check: all green (not recorded for the pre-push: the cache is unavailable, see above; after fixing it: bash $0)"
  fi
fi
tree_after="$(bash "$helper" worktree-tree 2>/dev/null)" || tree_after=""
if [ "$tree_after" != "$tree_before" ]; then
  finish_ok "check: all green, but the work tree changed during the run (${tree_before:0:7} -> ${tree_after:0:7}); not recorded, so the next push runs the check again. To record it: bash $0"
fi
bash "$helper" add "$key" < /dev/null
if bash "$helper" has "$key" > /dev/null 2>&1; then
  finish_ok "check: all green on tree ${tree_before:0:7}; the next push of this same tree will skip the check (to run it anyway: GW_CHECK_CACHE=0 git push)"
else
  finish_ok "check: all green, but it could not be recorded (see above); the next push will run the check again"
fi
