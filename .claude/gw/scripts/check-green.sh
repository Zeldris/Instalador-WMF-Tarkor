#!/usr/bin/env bash
# galivelop-workflow v0.6.0
# Cache of "the project's `check` already passed": lets the pre-push (and scripts/check.sh) skip a check that already
# ran green on the same tree with the same commands and wrapper, less than `checkReuseTtl` (24 h) ago. One line per success,
# "<epoch> <key>", in <git common dir>/gw-check-green (shared by linked worktrees), the last `checkReuseKeep` (50) kept.
#   printf '%s\n' "$checks" | bash check-green.sh key <tree-sha> <wrapper> [<inputs-hash>]   # prints the key
#   printf '%s\n' "$paths" | bash check-green.sh inputs [<dir>]   # E23: hash of the content of the files listed (checkCacheInputs,
#                                       # relative to <dir>, the checkout or the worktree where the check runs; ignored files the check reads, e.g. .claude/gw.local.json)
#                                       # to pass as <inputs-hash>: a changed file is another key. A missing file hashes as
#                                       # absent, a path outside the repo (leading / or ..) as invalid (never opened); symlinks are followed (content hashed);
#                                       # a folder, broken link or unreadable file fails (exit 1: no key). No paths:
#                                       # prints nothing, and `key` is then the key records had before E23.
#   bash check-green.sh worktree-tree   # the tree the working copy would commit after `git add -A` (real index untouched);
#                                       # fails when that tree may not be what a check sees (assume-unchanged or
#                                       # skip-worktree entries, sparse checkout, a modified submodule)
#   bash check-green.sh has <key>       # exit 0 and the age in minutes if recorded < `checkReuseTtl` ago; any problem is a miss (1)
#   bash check-green.sh epoch <key>     # exit 0 and the epoch (seconds) of the newest line for the key if recorded < `checkReuseTtl` ago
#   bash check-green.sh add <key> [<epoch>]  # records the key now (or at <epoch>, to inherit the age of the green it derives
#                                       # from); best effort (a write failure warns and exits 0)
#   bash check-green.sh lock-acquire <owner-pid> <sha> <wait-seconds> <log>
#                                       # takes <git common dir>/gw/check.lock for <owner-pid> (E20), a symlink whose target
#                                       # is "pid|process start|sha|log" (so the take is atomic and the owner verifiable);
#                                       # exit 0 taken, 3 another live check holds it (names pid/sha/log) after waiting
#                                       # <wait-seconds>, 1 cannot. A lock whose process is gone, or whose pid now belongs
#                                       # to another process (different start time), is discarded.
#                                       # E40: once taken, the check-<sha>.log files beside it beyond the newest `checkLogKeep` go.
#   bash check-green.sh lock-release <owner-pid>   # removes the lock only if <owner-pid> owns it
# GW_CHECK_CACHE=0 makes `has` always miss. Bash 3.2 compatible. Root from this script's path, never from the cwd.
set -uo pipefail
FORMAT="gw-check-cache 1"
here="$(cd "$(dirname "$0")" && pwd)"
# Git exports GIT_DIR (and friends) to hooks, also in a linked worktree; with GIT_DIR set `rev-parse --show-toplevel`
# answers $here, not the repo root.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
root="$(unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE; git -C "$here" rev-parse --show-toplevel 2>/dev/null)" || {
  echo "check-green: $here is not inside a git repository; reinstall the workflow: /gw-update" >&2; exit 1; }
cd "$root" || exit 1

cfg_number() {  # cfg_number <key>: the key's value from .claude/gw.json (the default when unset); fails on an invalid config
  local v
  v="$(python3 "$here/config.py" --root "$root" get "$1" 2>/dev/null)" || return 1
  case "$v" in '' | *[!0-9]*) return 1 ;; esac
  echo "$v"
}

usage() {
  echo "check-green: $1; usage: bash $0 key <tree-sha> <wrapper> [<inputs-hash>] | inputs [<dir>] | worktree-tree | has <key> | epoch <key> | add <key> [<epoch>] | lock-acquire <pid> <sha> <wait> <log> | lock-release <pid>" >&2
  exit 2
}
valid_key() {  # a git object name: 40 (sha-1) or 64 (sha-256) lowercase hex digits
  case "$1" in *[!0-9a-f]*) return 1 ;; esac
  [ "${#1}" -eq 40 ] || [ "${#1}" -eq 64 ]
}
cache_file() {  # absolute path of the cache file, or fail
  local common
  common="$(git rev-parse --git-common-dir 2>/dev/null)" && common="$(cd "$common" 2>/dev/null && pwd)" && [ -n "$common" ] || return 1
  printf '%s/gw-check-green\n' "$common"
}

cmd_key() {
  [ "$#" -ge 1 ] || usage "key needs a tree sha"
  local tree="$1" wrapper="${2:-}" inputs="${3:-}" commands
  commands="$(cat)"
  # Every part is on its own labelled line, so a change in any of them changes the key. The inputs line exists only when
  # there are inputs: an old record (no such line) never equals the key of a tree that has them, so it is a miss (fail closed).
  if [ -n "$inputs" ]; then
    printf '%s\ntree %s\nwrapper %s\ninputs %s\ncommands\n%s\n' "$FORMAT" "$tree" "$wrapper" "$inputs" "$commands" | git hash-object --stdin
  else
    printf '%s\ntree %s\nwrapper %s\ncommands\n%s\n' "$FORMAT" "$tree" "$wrapper" "$commands" | git hash-object --stdin
  fi
}
cmd_inputs() {  # [<dir>]; paths on stdin, one per line; prints one hash of their content, or nothing when there are none
  local base="${1:-$root}" path full lines="" h c1 c2
  # <dir> is where the check really runs: the checkout or a temporary worktree of this repository (it may lack the ignored files).
  { c1="$(git -C "$base" rev-parse --git-common-dir 2>/dev/null)" && c1="$(cd "$base" && cd "$c1" && pwd -P)" \
    && c2="$(git rev-parse --git-common-dir 2>/dev/null)" && c2="$(cd "$c2" && pwd -P)" && [ "$c1" = "$c2" ]; } \
    || { echo "check-green: '$base' is not a work tree of this repository, so its inputs cannot be hashed; pass the checkout or a worktree of it" >&2; return 1; }
  base="$(cd "$base" && pwd)" || return 1
  while IFS= read -r path || [ -n "$path" ]; do
    [ -n "$path" ] || continue
    case "$path" in
      /* | .. | ../* | */../* | */..) lines="$lines"$'\n'"invalid $path" ; continue ;;  # outside the repo: never opened, but it changes the key
    esac
    full="$base/$path"
    if [ -f "$full" ]; then  # follows symlinks (also in folders of the path): the content the check reads
      h="$(git hash-object --no-filters --stdin < "$full" 2>/dev/null)" || h=""
      [ -n "$h" ] || { echo "check-green: cannot read input '$path' in $base, so the green cannot be keyed; fix its permissions or remove it from checkCacheInputs in .claude/gw.json" >&2; return 1; }
      lines="$lines"$'\n'"file $path $h"
    elif [ -e "$full" ] || [ -L "$full" ]; then  # a folder, a broken link, a device: not content we can key
      echo "check-green: input '$path' in $base is not a readable file (a folder, a broken link?), so the green cannot be keyed; fix it or remove it from checkCacheInputs in .claude/gw.json" >&2
      return 1
    else
      lines="$lines"$'\n'"absent $path"
    fi
  done
  [ -z "$lines" ] || printf '%s\n' "$lines" | git hash-object --stdin
}
hidden_entry() {  # the first index entry git does not compare with the disk (assume-unchanged, skip-worktree), or fail
  local listing
  listing="$(git ls-files -v 2>/dev/null)" || return 1
  # `ls-files -v` tags assume-unchanged entries with a lowercase letter and skip-worktree ones (sparse checkout) with S.
  printf '%s\n' "$listing" | { LC_ALL=C grep -m 1 '^[a-zS] ' || true; } | cut -c 3-
}
dirty_submodule() {  # the first submodule (gitlink) with new commits or changes inside, or fail
  local rec path
  git ls-files -s -z 2>/dev/null | while IFS= read -r -d '' rec; do
    case "$rec" in 160000\ *) ;; *) continue ;; esac
    path="${rec#*$'\t'}"
    if [ -n "$(git status --porcelain --ignore-submodules=none -- "$path" 2>/dev/null)" ]; then
      printf '%s\n' "$path"
      break
    fi
  done
}

tmp_add=""   # the temp file of add, global for the same reason
tmp_tree=""  # the temp dir of worktree-tree: global, because the EXIT trap runs after the function is gone
cmd_worktree_tree() {
  local tmp idx hidden sub
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/gw-check-tree.XXXXXX")" || {
    echo "check-green: cannot create a temp dir in ${TMPDIR:-/tmp}; free space and retry: bash $0 worktree-tree" >&2; return 1; }
  tmp_tree="$tmp"
  trap 'rm -rf "$tmp_tree"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  trap 'exit 129' HUP
  idx="$(git rev-parse --git-path index 2>/dev/null)" || {
    echo "check-green: cannot locate the git index; check the repository: git rev-parse --git-path index" >&2; return 1; }
  # No index yet (a repo with no add or commit): an index file that does not exist is an empty one for git.
  if [ -f "$idx" ]; then
    # -p keeps the index's mtime: git re-reads the files changed in the same second it was written (racy git); a
    # newer copy would trust their size and mtime and stage the old content.
    cp -p "$idx" "$tmp/index" || {
      echo "check-green: cannot copy the git index $idx; check permissions and space: cp -p $idx $tmp/index" >&2; return 1; }
  fi
  GIT_INDEX_FILE="$tmp/index" git add -A >/dev/null 2>&1 || {
    echo "check-green: cannot stage a copy of the work tree; reproduce it with: git add -A --dry-run" >&2; return 1; }
  # The tree must be what a check of the work tree sees: git add -A skips the files git does not look at (the
  # copy keeps the real index's flags).
  hidden="$(GIT_INDEX_FILE="$tmp/index" hidden_entry)" || {
    echo "check-green: cannot list the index entries; check the repository: git ls-files -v" >&2; return 1; }
  if [ -n "$hidden" ]; then
    echo "check-green: '$hidden' is assume-unchanged or skip-worktree (sparse checkout?), so the staged tree may not be what the check sees; clear the flags to use the cache: git update-index --no-assume-unchanged --no-skip-worktree -- '$hidden'" >&2
    return 1
  fi
  sub="$(dirty_submodule)"
  if [ -n "$sub" ]; then
    echo "check-green: submodule '$sub' has new commits or changes inside, so the staged tree may not be what the check sees; commit or discard them to use the cache: git -C '$sub' status" >&2
    return 1
  fi
  GIT_INDEX_FILE="$tmp/index" git write-tree 2>/dev/null || {
    echo "check-green: cannot write the tree of the work tree; reproduce it with: git add -A --dry-run && git write-tree" >&2; return 1; }
}

lookup_epoch() {  # lookup_epoch <key>: prints the epoch of the newest line for the key if it is younger than `checkReuseTtl`, else fails
  [ "${GW_CHECK_CACHE:-}" != "0" ] || return 1
  valid_key "$1" || return 1
  local file now epoch k age found="" ttl
  ttl="$(cfg_number checkReuseTtl)" || return 1  # `checkReuseTtl` seconds: an invalid config is a miss (fail closed)
  file="$(cache_file)" || return 1
  [ -f "$file" ] || return 1
  now="$(date +%s)" || return 1
  case "$now" in '' | *[!0-9]*) return 1 ;; esac
  while read -r epoch k _rest; do  # the newest line for the key wins
    [ "${k:-}" = "$1" ] || continue
    case "$epoch" in '' | *[!0-9]*) continue ;; esac
    found="$epoch"
  done 2>/dev/null < "$file"
  [ -n "$found" ] || return 1
  age=$((now - found))
  [ "$age" -ge 0 ] && [ "$age" -lt "$ttl" ] || return 1  # in the future (clock change) or too old
  echo "$found"
}
cmd_has() {
  [ "$#" -eq 1 ] || usage "has needs a key"
  local found now
  found="$(lookup_epoch "$1")" || return 1
  now="$(date +%s)" || return 1
  echo $(((now - found) / 60))
}
cmd_epoch() {
  [ "$#" -eq 1 ] || usage "epoch needs a key"
  lookup_epoch "$1"
}

cmd_add() {
  { [ "$#" -ge 1 ] && [ "$#" -le 2 ]; } || usage "add needs a key and optionally an epoch"
  valid_key "$1" || usage "'$1' is not a git object name"
  local file now tmp keep
  keep="$(cfg_number checkReuseKeep)" || { echo "check-green: warning: cannot read checkReuseKeep, check not recorded; fix .claude/gw.json: python3 $here/config.py validate" >&2; return 0; }
  file="$(cache_file)" || { echo "check-green: warning: cannot locate the git dir, check not recorded; check the repository: git rev-parse --git-common-dir" >&2; return 0; }
  now="$(date +%s)" || { echo "check-green: warning: cannot read the clock, check not recorded; check it: date +%s" >&2; return 0; }
  if [ -n "${2:-}" ]; then
    case "$2" in *[!0-9]*) usage "'$2' is not an epoch" ;; esac
    now="$2"
  fi
  [ ! -d "$file" ] || { echo "check-green: warning: $file is a directory, check not recorded; remove it: rm -r $file" >&2; return 0; }
  tmp="$(mktemp "$file.XXXXXX" 2>/dev/null)" || { echo "check-green: warning: cannot write next to $file, check not recorded; make its folder writable: ls -ld ${file%/*}" >&2; return 0; }
  tmp_add="$tmp"
  trap 'rm -f "$tmp_add"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  trap 'exit 129' HUP
  if {
    if [ -f "$file" ]; then  # drop older lines of the same key, keep the last `checkReuseKeep` - 1
      awk -v key="$1" '$2 != key' "$file" 2>/dev/null | tail -n $((keep - 1))
    fi
    printf '%s %s\n' "$now" "$1"
  } > "$tmp" 2>/dev/null && mv -f "$tmp" "$file" 2>/dev/null; then
    :
  else
    rm -f "$tmp"
    echo "check-green: warning: cannot update $file, check not recorded; free space or fix its permissions: ls -l $file" >&2
  fi
  return 0
}

lock_file() {  # absolute path of the lock, creating <git common dir>/gw, or fail
  local common
  common="$(git rev-parse --git-common-dir 2>/dev/null)" && common="$(cd "$common" 2>/dev/null && pwd)" && [ -n "$common" ] || return 1
  mkdir -p "$common/gw" 2>/dev/null || return 1
  printf '%s/gw/check.lock\n' "$common"
}
proc_start() {  # the start time of a process as ps prints it ("?" if ps cannot tell but the process exists); empty if gone
  local out
  out="$(LC_ALL=C ps -o lstart= -p "$1" 2>/dev/null | sed 's/^ *//; s/ *$//; s/  */ /g')"
  if [ -z "$out" ]; then  # D76: a process of another user is alive too (kill -0 fails with EPERM, as before-stop.py accepts)
    case "$(kill -0 "$1" 2>&1)" in
      "") out="?" ;;
      *[Nn]ot\ permitted* | *EPERM*) out="?" ;;
    esac
  fi
  printf '%s\n' "$out"
}
proc_is() {  # proc_is <pid> <start>: that very process is still running (not gone, not a zombie, not a reused pid)
  local st
  st="$(LC_ALL=C ps -o stat= -p "$1" 2>/dev/null | tr -d ' ')"
  case "$st" in Z*) return 1 ;; esac
  [ -n "$2" ] && [ "$(proc_start "$1")" = "$2" ]
}

prune_logs() {  # prune_logs <lock> <keep-log>: E40 keeps the newest `checkLogKeep` check-<sha>.log of the lock's folder (0 = all)
  local dir keep f n=0
  dir="$(dirname "$1")"
  keep="$(python3 "$here/config.py" --root "$root" get checkLogKeep 2>/dev/null)" || return 0
  case "$keep" in '' | *[!0-9]*) return 0 ;; esac
  [ "$keep" -gt 0 ] || return 0
  # ls -t lists the newest first, one per line (the folder may hold spaces; the names, check-<sha>.log, never do)
  # shellcheck disable=SC2012
  ls -1t "$dir"/check-*.log 2>/dev/null | while IFS= read -r f; do
    [ "$f" != "$2" ] || continue  # the log of the run that is starting is never pruned
    n=$((n + 1))
    [ "$n" -le "$keep" ] || rm -f "$f" 2>/dev/null
  done
  return 0
}

cmd_lock_acquire() {
  [ "$#" -eq 4 ] || usage "lock-acquire needs <owner-pid> <sha> <wait-seconds> <log>"
  local owner="$1" sha="$2" wait="$3" log="$4" lock mine cur pid rest start osha olog steal sp waited announced="" vanished=0
  case "$owner$wait" in ''|*[!0-9]*) usage "lock-acquire: pid and wait must be numbers" ;; esac
  lock="$(lock_file)" || { echo "check-green: cannot create <git common dir>/gw for the lock; make the git dir writable, e.g. chmod u+w \"\$(git rev-parse --git-common-dir)\"" >&2; return 1; }
  mine="$owner|$(proc_start "$owner")|$sha|$log"
  waited=0  # whole seconds slept: $SECONDS ticks on the second, so SECONDS+wait could give up after wait-1 s
  while :; do
    if ln -s "$mine" "$lock" 2>/dev/null; then prune_logs "$lock" "$log"; return 0; fi
    cur="$(readlink "$lock" 2>/dev/null)"
    if [ -z "$cur" ]; then
      if [ -e "$lock" ] || [ -L "$lock" ]; then  # an old-format lock (a directory) or an empty one
        echo "check-green: removing a lock in an old format: $lock" >&2
        rm -rf "$lock"
        continue
      fi
      vanished=$((vanished + 1))  # it went away between ln and readlink: try again, but not forever if ln cannot work
      [ "$vanished" -lt 5 ] || { echo "check-green: cannot create the lock $lock; make its folder writable: chmod u+w $(dirname "$lock")" >&2; return 1; }
      continue
    fi
    if [ "${cur%%|*}" = "$owner" ]; then  # already ours (a hook that checks several refs): D76 it now describes this run
      [ "$cur" = "$mine" ] && return 0
      rm -f "$lock.$owner.new"
      { ln -s "$mine" "$lock.$owner.new" 2>/dev/null && mv -f "$lock.$owner.new" "$lock" 2>/dev/null; } || {
        rm -f "$lock.$owner.new"
        echo "check-green: cannot update the lock $lock; make its folder writable: chmod u+w $(dirname "$lock")" >&2; return 1; }
      return 0
    fi
    pid="${cur%%|*}"; rest="${cur#*|}"; start="${rest%%|*}"; rest="${rest#*|}"; osha="${rest%%|*}"; olog="${rest#*|}"
    if ! proc_is "$pid" "$start"; then  # orphan: dropped under a mutex, so two stealers never judge and drop in turn
      steal="$lock.steal"
      if ! mkdir "$steal" 2>/dev/null; then
        sp="$(cat "$steal/pid" 2>/dev/null)"
        if [ -z "$sp" ]; then  # D76: a mutex with no pid is one its owner has not written yet or died before writing
          sleep 1
          sp="$(cat "$steal/pid" 2>/dev/null)"
          if [ -z "$sp" ]; then
            rm -rf "$steal"
            continue
          fi
        fi
        if [ -n "$sp" ] && ! proc_is "${sp%%|*}" "${sp#*|}"; then  # its owner died holding it
          rm -rf "$steal"
          continue
        fi
        echo "CHECK FAILED: not run, another check is replacing a stale lock (${sp:-owner unknown}); run this again in a moment. If none is running, remove the mutex: rm -rf $steal" >&2
        return 3
      fi
      printf '%s|%s\n' "$owner" "$(proc_start "$owner")" > "$steal/pid" 2>/dev/null
      # Only stealers replace a lock that exists, so while we hold the mutex it is still the one we judged unless it
      # was released: compare, then drop it.
      if [ "$(readlink "$lock" 2>/dev/null)" = "$cur" ]; then
        echo "check: discarding a stale lock (pid $pid is not running as the same process)" >&2
        rm -f "$lock"
      fi
      rm -rf "$steal"
      continue
    fi
    if [ "$waited" -ge "$wait" ]; then
      echo "CHECK FAILED: not run, another check is running (pid $pid, sha ${osha:-unknown}); wait for it and read its log ${olog:--}, or raise checkLockWait in .claude/gw.json to wait for it. If pid $pid is not a check (check: ps -p $pid -o command=), remove the lock: rm $lock" >&2
      return 3
    fi
    [ -n "$announced" ] || echo "check: waiting for the check of pid $pid (sha ${osha:-unknown}) to end (up to ${wait}s)" >&2
    announced=1
    sleep 1
    waited=$((waited + 1))
  done
}
cmd_lock_release() {
  [ "$#" -eq 1 ] || usage "lock-release needs <owner-pid>"
  local lock cur
  lock="$(lock_file)" || return 0
  cur="$(readlink "$lock" 2>/dev/null)"
  case "$cur" in "$1|"*) rm -f "$lock" ;; esac
  return 0
}

sub="${1:-}"
[ "$#" -eq 0 ] || shift
case "$sub" in
  key) cmd_key "$@" ;;
  inputs) cmd_inputs "$@" ;;
  worktree-tree) cmd_worktree_tree ;;
  has) cmd_has "$@" ;;
  epoch) cmd_epoch "$@" ;;
  add) cmd_add "$@" ;;
  lock-acquire) cmd_lock_acquire "$@" ;;
  lock-release) cmd_lock_release "$@" ;;
  *) usage "unknown subcommand '$sub'" ;;
esac
