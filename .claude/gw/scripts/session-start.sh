#!/usr/bin/env bash
# galivelop-workflow v0.3.0
# Claude Code SessionStart hook (startup|resume|clear): leaves the project ready to work. Idempotent.
#   - git hooks: sets core.hooksPath to .githooks when it is unset and .githooks exists; when another hook manager
#     owns the hooks (core.hooksPath elsewhere, or hooks installed in .git/hooks), it says how to chain the
#     workflow's hooks instead of overwriting anything.
#   - cloud (CLAUDE_CODE_REMOTE=true): runs the config's `install` commands and then its `setup` commands, in order,
#     only when the lockfiles (or the commands) changed since the last successful run; the hash lives in the git dir
#     (gw-install.sha). A failing or hanging command (GW_COMMAND_TIMEOUT seconds, default 900) is reported.
#     The limit is a portable bash watchdog (no `timeout` needed, so it also works on stock macOS): the command runs
#     in its own process group and, past the limit, the whole group gets TERM and, a few seconds later, KILL. A
#     process that detaches itself from the group (setsid, nohup in a new session, a daemon) can survive.
#   - warns when .claude/gw.json is missing or invalid, when its `version` is older than this copy of the workflow
#     (the `# galivelop-workflow vX.Y.Z` header of this script), and when the session was started outside the repo
#     root (its .claude/settings.json may not have loaded; VeriNews P3).
# Fails open: always exits 0 (a SessionStart hook cannot block); warnings go to stdout, which enters the agent's
# context, each ending with the command that fixes it.
# Project root: the git top level of this script's folder when it holds .claude/gw.json (the copy in
# .claude/gw/scripts); from the plugin cache, the same fallback as config.py (CLAUDE_PROJECT_DIR, then the current
# directory), only to find the repo. Bash 3.2 compatible.
set -uo pipefail
start_pwd="$PWD"
here="$(cd "$(dirname "$0")" && pwd)" || { echo "gw session-start: cannot find its own folder; reinstall the workflow: /gw-update"; exit 0; }
warn() { echo "gw session-start: $*"; }

input=""
if [ ! -t 0 ]; then input="$(cat 2>/dev/null || true)"; fi

toplevel() { git -C "$1" rev-parse --show-toplevel 2>/dev/null; }
root="$(toplevel "$here")"
if [ -z "$root" ] || [ ! -f "$root/.claude/gw.json" ]; then
  root=""
  for candidate in "${CLAUDE_PROJECT_DIR:-}" "$start_pwd"; do
    [ -n "$candidate" ] || continue
    root="$(toplevel "$candidate")" && [ -n "$root" ] && break
  done
fi
if [ -z "$root" ]; then
  warn "not inside a git repository, so the workflow is not active; open Claude Code in the project: cd <project> && claude"
  exit 0
fi
cd "$root" || exit 0
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
config="$here/config.py"

# --- Session opened outside the repo root (VeriNews P3) ---------------------------------------------------------
cwd=""
if [ -n "$input" ]; then
  cwd="$(printf '%s' "$input" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("cwd") or "")
except Exception: print("")' 2>/dev/null)"
fi
[ -n "$cwd" ] || cwd="$start_pwd"
real() { (cd "$1" 2>/dev/null && pwd -P); }
if [ -n "$cwd" ]; then
  rcwd="$(real "$cwd")"; rroot="$(real "$root")"
  case "$rcwd/" in
    "$rroot"/*) ;;
    *) warn "this session was started in $cwd, outside the repo root ($root): the repo's .claude/settings.json (hooks, env) may not have loaded; restart Claude Code from the repo: cd $root && claude" ;;
  esac
fi

# --- Git hooks --------------------------------------------------------------------------------------------------
chain_hint() {  # chain_hint <hooks dir>
  echo "chain them by adding this as the last line of $1/pre-push and $1/pre-commit (replace <hook> with the file's name): \"\$(git rev-parse --show-toplevel)/.githooks/<hook>\" \"\$@\" || exit 1"
}
if [ -d "$root/.githooks" ]; then
  current="$(git config --get core.hooksPath 2>/dev/null || true)"
  if [ -z "$current" ]; then
    gitdir_hooks="$(git rev-parse --git-path hooks 2>/dev/null || true)"
    foreign=""
    for h in pre-commit pre-push commit-msg; do
      if [ -n "$gitdir_hooks" ] && [ -x "$gitdir_hooks/$h" ]; then foreign="$foreign $h"; fi
    done
    if [ -n "$foreign" ]; then
      warn "another hook manager installed hooks in $gitdir_hooks ($foreign ); core.hooksPath left unset so they keep running, and the workflow's hooks are not active; $(chain_hint "$gitdir_hooks")"
    elif git config core.hooksPath .githooks 2>/dev/null; then
      :
    else
      warn "could not set core.hooksPath; set it by hand: git config core.hooksPath .githooks"
    fi
  elif [ "$current" != ".githooks" ] && [ "$current" != "$root/.githooks" ]; then
    warn "core.hooksPath is '$current' (another hook manager), so the workflow's pre-push and pre-commit are not active; $(chain_hint "$current")"
  fi
else
  warn "$root/.githooks is missing, so pushes are not checked; reinstall the workflow's git hooks: /gw-update"
fi

# --- Config and version -----------------------------------------------------------------------------------------
own_version="$(sed -n '2s/^# galivelop-workflow v\([0-9][0-9.]*\).*/\1/p' "$0" 2>/dev/null)"
version_lt() {  # version_lt A B: true when A < B (numeric X.Y.Z; pre-release suffixes ignored)
  local a b i x y
  a="${1%%-*}"; b="${2%%-*}"
  for i in 1 2 3; do
    x="$(echo "$a" | cut -d. -f"$i")"; y="$(echo "$b" | cut -d. -f"$i")"
    x="${x:-0}"; y="${y:-0}"
    case "$x$y" in *[!0-9]*) return 1 ;; esac
    [ "$x" -lt "$y" ] && return 0
    [ "$x" -gt "$y" ] && return 1
  done
  return 1
}
config_ok=""
if [ ! -f "$root/.claude/gw.json" ]; then
  warn ".claude/gw.json is missing, so the workflow is not configured for this repo; apply it (docs/en/apply.md): /gw-init"
elif [ ! -f "$config" ]; then
  warn "the workflow scripts are incomplete ($config is missing); reinstall them: /gw-update"
elif ! errors="$(python3 "$config" --root "$root" validate 2>&1 >/dev/null)"; then
  warn "$(printf '%s' "$errors" | head -n 5 | tr '\n' ' ')— fix it and check: python3 $config --root $root validate"
else
  config_ok=1
  project_version="$(python3 "$config" --root "$root" get version 2>/dev/null)"
  if [ -n "$own_version" ] && [ -n "$project_version" ] && version_lt "$project_version" "$own_version"; then
    warn ".claude/gw.json says version $project_version but the workflow copy is $own_version; bring the project up to date: /gw-update"
  fi
fi

# run_limited <seconds> <command> <log>: runs the command with bash in its own process group (set -m), output to the
# log. A watchdog sleeps <seconds> and then marks the run as timed out, sends TERM to the group and, 5 s later, KILL.
# Sets `timed_out` only when the watchdog fired (a command that exits 124 by itself is a plain failure). Returns the
# command's exit status.
run_limited() {
  local limit="$1" cmd="$2" log="$3" flag pid wd status
  flag="$(mktemp "${TMPDIR:-/tmp}/gw-timeout.XXXXXX")" || flag="${TMPDIR:-/tmp}/gw-timeout.$$"
  rm -f "$flag"; timed_out=""
  set -m
  bash -c "$cmd" > "$log" 2>&1 < /dev/null &
  pid=$!
  ( sleep "$limit"; : > "$flag"; kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
    sleep 5; kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null ) > /dev/null 2>&1 < /dev/null &
  wd=$!
  set +m
  wait "$pid" 2>/dev/null; status=$?
  if [ "$status" -ne 0 ] && [ -e "$flag" ]; then
    timed_out=1                       # the watchdog finishes its KILL pass on its own
  else                                # also a command that succeeded just as the watchdog fired
    kill -- "-$wd" 2>/dev/null || kill "$wd" 2>/dev/null   # command finished first: stop the watchdog and its sleeper
    wait "$wd" 2>/dev/null
  fi
  rm -f "$flag"
  return "$status"
}

# --- Cloud dependencies and setup -------------------------------------------------------------------------------
# `install` commands, then `setup` commands, one after another in this one hook (separate SessionStart hooks run in
# parallel, so ordering has to live here). A command that fails or runs past GW_COMMAND_TIMEOUT seconds (default 900)
# is reported and stops the sequence; the stamp is not written, so the next session tries again.
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ] && [ -n "$config_ok" ]; then
  installs="$(python3 "$config" --root "$root" get install 2>/dev/null)"
  setups="$(python3 "$config" --root "$root" get setup 2>/dev/null)"
  if [ -n "$installs" ] || [ -n "$setups" ]; then
    locks="$(git ls-files -- 'package-lock.json' '*/package-lock.json' 'npm-shrinkwrap.json' 'yarn.lock' '*/yarn.lock' \
      'pnpm-lock.yaml' '*/pnpm-lock.yaml' 'bun.lock' 'bun.lockb' '*/bun.lock' 'Cargo.lock' '*/Cargo.lock' \
      'poetry.lock' '*/poetry.lock' 'uv.lock' '*/uv.lock' 'Pipfile.lock' 'requirements*.txt' '*/requirements*.txt' \
      'Gemfile.lock' 'go.sum' '*/go.sum' 'composer.lock' 'pom.xml' '*/pom.xml' 2>/dev/null)"
    sum="$( { printf '%s\n' "$installs"
              if [ -n "$setups" ]; then printf 'setup:\n%s\n' "$setups"; fi
              printf '%s\n' "$locks" | while IFS= read -r f; do
                [ -n "$f" ] && [ -f "$f" ] && printf '%s %s\n' "$(git hash-object -- "$f")" "$f"
              done; } | git hash-object --stdin)"
    stamp="$(git rev-parse --git-path gw-install.sha 2>/dev/null)"
    case "$stamp" in /*) ;; *) stamp="$root/$stamp" ;; esac
    if [ -n "$sum" ] && [ "$(cat "$stamp" 2>/dev/null)" = "$sum" ]; then
      :
    else
      failed=""
      limit="${GW_COMMAND_TIMEOUT:-900}"
      case "$limit" in ''|*[!0-9]*) limit=900 ;; esac
      [ "$((10#$limit))" -gt 0 ] || limit=900   # 0 would kill every command at once
      while IFS= read -r entry; do
        [ -n "$entry" ] || continue
        kind="${entry%%:*}"; cmd="${entry#*:}"
        echo "gw session-start: running $kind command: $cmd"
        log="${TMPDIR:-/tmp}/gw-$kind.log"
        run_limited "$limit" "$cmd" "$log"
        status=$?
        if [ "$status" -ne 0 ]; then
          tail -n 10 "$log"
          why="failed"; [ -n "$timed_out" ] && why="timed out after ${limit}s"
          warn "$kind command $why: '$cmd' (log: $log); fix it, then run it by hand: $cmd"
          failed=1
          break
        fi
      done <<<"$(printf '%s\n' "$installs" | sed 's/^/install:/;/^install:$/d'; printf '%s\n' "$setups" | sed 's/^/setup:/;/^setup:$/d')"
      if [ -z "$failed" ] && [ -n "$sum" ]; then printf '%s\n' "$sum" > "$stamp" 2>/dev/null || true; fi
    fi
  fi
fi
exit 0
