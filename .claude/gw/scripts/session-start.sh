#!/usr/bin/env bash
# galivelop-workflow v0.9.0
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
#     root (its .claude/settings.json may not have loaded; private-project-1 P3), and when agentSignatures is false
#     while git user.email is noreply@anthropic.com (D21).
#   - spend alert (B6): with a valid config, prints the lines of `metrics.py alert` (a model whose spend today or
#     yesterday passes metrics.alert.factor x its daily mean); its errors are dropped.
#   - worker hint (E68): with a valid config, .claude/agents/gw-worker.md and workerHint not false, one line that deals
#     sweeps and review fixes of 2 or more points to a gw-worker subagent instead of the main session.
#   - open questions (C3): with a valid config, prints `questions.py notice`: only "N open questions (path)", or the whole
#     list when some open question was never shown (mark in the git dir, gw/questions-shown); a broken questions file is a one-line warning.
#   - agent language (A12): with a valid config, "Agent language: <code>" from ~/.claude/gw.json (agentLanguage, keyed by
#     the repo's git user.email; GW_USER_CONFIG overrides the path), else languages.docs.primary; a bad file is a warning.
#   - session model (D142): with a valid config and the hook's transcript_path, prints `models.py session-check`: a
#     warning when the last gw-selector line in the transcript recommends another model family than the session's
#     (the hook's `model`, else the last assistant message); models.sessionCheck false turns it off.
#   - active modes (C7): with a valid config, prints `mode.py line` ("Modes: careful on, questions restrictive"); a broken
#     config is a one-line warning.
# Fails open: always exits 0 (a SessionStart hook cannot block); warnings go to stdout, which enters the agent's
# context, each ending with the command that fixes it.
# Project root: the git top level of this script's folder when it holds .claude/gw.json (the copy in
# .claude/gw/scripts); from the plugin cache, $CLAUDE_PROJECT_DIR, then the current
# directory (config.py, run from that root, resolves the same one). Bash 3.2 compatible.
set -uo pipefail
start_pwd="$PWD"
here="$(cd "$(dirname "$0")" && pwd)" || { echo "gw session-start: cannot find its own folder; reinstall the workflow: /gw-update"; exit 0; }
warn() { echo "gw session-start: $*"; }

input=""
if [ ! -t 0 ]; then input="$(cat 2>/dev/null || true)"; fi

toplevel() { (unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE; git -C "$1" rev-parse --show-toplevel 2>/dev/null); }
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

# --- Session opened outside the repo root (private-project-1 P3) ------------------------------------------------
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
  # a cloud session always starts in /home/user, whatever repo it works on: not a mistake to warn about (Portal P1)
  [ "${CLAUDE_CODE_REMOTE:-}" = true ] && [ "${cwd%/}" = /home/user ] && rcwd="$rroot"
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
agent_language_fallback() {
  # A12 (Q-18): without a usable project config the language comes from the user file, else en; say why.
  [ -f "$config" ] || return 0
  fb="$(python3 "$config" --root "$root" agent-language 2>/dev/null)"
  echo "Agent language: ${fb:-en}"
  warn "Agent language: the project config is unusable, so '${fb:-en}' comes from ~/.claude/gw.json or the default 'en', not from languages.docs.primary; fix the config as said above, then restart the session"
}
if [ ! -f "$root/.claude/gw.json" ]; then
  warn ".claude/gw.json is missing, so the workflow is not configured for this repo; apply it (docs/en/apply.md): /gw-init"
elif [ ! -f "$config" ]; then
  warn "the workflow scripts are incomplete ($config is missing); reinstall them: /gw-update"
elif ! errors="$(python3 "$config" --root "$root" validate 2>&1 >/dev/null)"; then
  warn "$(printf '%s' "$errors" | head -n 5 | tr '\n' ' ')— fix it and check: python3 $config --root $root validate"
else
  config_ok=1
  if [ "$(python3 "$config" --root "$root" get agentSignatures 2>/dev/null)" = false ] \
     && [ "$(git -C "$root" config --get user.email 2>/dev/null | tr '[:upper:]' '[:lower:]')" = "noreply@anthropic.com" ]; then
    warn "agentSignatures is false but git user.email is noreply@anthropic.com, so commits would go out under the agent; set the project's author before the first commit: git config user.name <name> && git config user.email <email>"
  fi
  project_version="$(python3 "$config" --root "$root" get version 2>/dev/null)"
  if [ -n "$own_version" ] && [ -n "$project_version" ] && version_lt "$project_version" "$own_version"; then
    warn ".claude/gw.json says version $project_version but the workflow copy is $own_version; bring the project up to date: /gw-update"
  fi
  if [ -f "$here/metrics.py" ]; then
    python3 "$here/metrics.py" alert --root "$root" 2>/dev/null | while IFS= read -r line; do warn "$line"; done
  fi
  lang_err="$(mktemp 2>/dev/null)" || lang_err=/dev/null
  if agent_lang="$(python3 "$config" --root "$root" agent-language 2>"$lang_err")" && [ -n "$agent_lang" ]; then
    echo "Agent language: $agent_lang"
  fi
  [ "$lang_err" = /dev/null ] || { [ ! -s "$lang_err" ] || warn "$(head -n 2 "$lang_err" | tr '\n' ' ')"; rm -f "$lang_err"; }
  if [ -f "$here/mode.py" ]; then
    if mout="$(python3 "$here/mode.py" --root "$root" line 2>&1)"; then
      [ -z "$mout" ] || printf '%s\n' "$mout"
    else
      warn "$(printf '%s' "$mout" | head -n 3 | tr '\n' ' ')- the active modes are not shown until it is fixed; check it: python3 $here/mode.py --root $root list"
    fi
  fi
  if [ -f "$root/.claude/agents/gw-worker.md" ] && [ "$(python3 "$config" --root "$root" get workerHint 2>/dev/null)" != false ]; then
    echo "Workers: deal sweeps and review fixes of 2 or more points to a gw-worker subagent (subagent_type: gw-worker, with model and effort; gw-orchestrate-dealer), not in the main session; to hide this line: \"workerHint\": false"
  fi
  if [ -f "$here/questions.py" ]; then
    if qout="$(python3 "$here/questions.py" --root "$root" notice 2>&1)"; then
      [ -z "$qout" ] || printf '%s\n' "$qout"
    else
      warn "$(printf '%s' "$qout" | head -n 3 | tr '\n' ' ')- the open questions are not shown until it is fixed; check it: python3 $here/questions.py --root $root count"
    fi
  fi
  if [ -f "$here/models.py" ] && [ -n "$input" ]; then
    # D142: the selector's recommended session model against the one the session runs on (its errors are dropped)
    hook_fields="$(printf '%s' "$input" | python3 -c 'import json,sys
try: d=json.load(sys.stdin)
except Exception: d={}
d=d if isinstance(d,dict) else {}
m=d.get("model")
m=m.get("id") if isinstance(m,dict) else m
for v in (d.get("transcript_path"), m): print(v if isinstance(v,str) else "")' 2>/dev/null)"
    transcript="$(printf '%s\n' "$hook_fields" | sed -n 1p)"
    hook_model="$(printf '%s\n' "$hook_fields" | sed -n 2p)"
    if [ -n "$transcript" ]; then
      python3 "$here/models.py" --root "$root" session-check --transcript "$transcript" --model "$hook_model" 2>/dev/null \
        | while IFS= read -r line; do warn "$line"; done
    fi
  fi
fi
[ -n "$config_ok" ] || agent_language_fallback

# run_limited <seconds> <command> <log>: runs the command with bash in its own process group (set -m), output to the
# log. A watchdog sleeps <seconds> and then marks the run as timed out, sends TERM to the group and, $kill_grace s
# later (commandKillGrace, default 5), KILL.
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
    sleep "$kill_grace"; kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null ) > /dev/null 2>&1 < /dev/null &
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
# parallel, so ordering has to live here). A command that fails or runs past GW_COMMAND_TIMEOUT seconds (else the
# commandTimeout key, default 900) is reported and stops the sequence; the stamp is not written, so the next session
# tries again. Only in cloud sessions (CLAUDE_CODE_REMOTE=true) unless installLocal is true.
install_here=""
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then install_here=1; fi
if [ -z "$install_here" ] && [ -n "$config_ok" ] && [ "$(python3 "$config" --root "$root" get installLocal 2>/dev/null)" = "true" ]; then
  install_here=1
fi
kill_grace=5
if [ -n "$install_here" ] && [ -n "$config_ok" ]; then
  installs="$(python3 "$config" --root "$root" get install 2>/dev/null)"
  setups="$(python3 "$config" --root "$root" get setup 2>/dev/null)"
  if [ -n "$installs" ] || [ -n "$setups" ]; then
    lockspecs=()
    while IFS= read -r spec; do [ -n "$spec" ] && lockspecs+=("$spec"); done <<<"$(python3 "$config" --root "$root" get installLockfiles 2>/dev/null)"
    locks=""
    if [ "${#lockspecs[@]}" -gt 0 ]; then locks="$(git ls-files -- "${lockspecs[@]}" 2>/dev/null)"; fi
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
      default_limit="$(python3 "$config" --root "$root" get commandTimeout 2>/dev/null)"
      case "$default_limit" in ''|*[!0-9]*) default_limit="$(python3 "$config" default commandTimeout 2>/dev/null)" ;; esac
      kill_grace="$(python3 "$config" --root "$root" get commandKillGrace 2>/dev/null)"
      case "$kill_grace" in ''|*[!0-9]*) kill_grace="$(python3 "$config" default commandKillGrace 2>/dev/null)" ;; esac
      limit="${GW_COMMAND_TIMEOUT:-$default_limit}"
      case "$limit" in ''|*[!0-9]*) limit="$default_limit" ;; esac
      [ "$((10#$limit))" -gt 0 ] || limit="$default_limit"   # 0 would kill every command at once
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
