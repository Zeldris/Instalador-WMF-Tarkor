#!/usr/bin/env bash
# galivelop-workflow v0.9.0
# Pushes a branch with retries and says "pushed" only when the remote really has the commit (D94).
#   bash push.sh [--wip] [<branch>]     (default: the current branch)
#  - E84 `--wip`: pushes a branch whose head commit subject starts with `WIP:` without waiting for the check (the
#    pre-push hook lets it through and records it in <git dir>/gw-wip-pushes), so a long red stretch is not left
#    unpushed. Never to the protected branch (`protectedBranch`) and never a head without `WIP:`: it fails first, with
#    the reason and nothing pushed (the hook judges it again). Everything else (retries, the remote confirmation) is the same.
#  - Runs `git push -u origin <branch>`; its output is shown and also classified when it fails.
#  - A transient failure (network, timeouts, RPC, early EOF, HTTP 5xx) is retried after each delay of `pushRetryDelays`
#    (seconds; default 2, 4, 8, 16). Anything else (a hook rejection, non-fast-forward, 403, authentication) fails at
#    once, with the reason and the command that fixes it.
#  - Success = `git ls-remote origin refs/heads/<branch>` equals the local commit of the branch (HEAD when it is the
#    current one). Exit 0 only then, also when the push exited non-zero but the remote already has it; a push that
#    said OK with a different remote is a failure.
#  - Each `git ls-remote` is limited to `pushLsRemoteTimeout` seconds (default 30; 0 = no limit): a hung network counts
#    as "cannot read origin" instead of blocking for ever (no `timeout` binary needed: macOS lacks it). It runs in its
#    own process group (`set -m`), and a timeout, Ctrl-C, TERM or the exit kill that whole group: git and the transport
#    under it (git-remote-https, ssh), so no hung helper is left behind.
#  - Exit 0 pushed; 1 push failed; 2 usage or a missing datum (no branch, detached HEAD without argument, no origin,
#    unreadable config), all before pushing.
# Bash 3.2 compatible. Root from this script's path, never from $CLAUDE_PROJECT_DIR or the current directory.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
die() { echo "push: $1" >&2; exit "${2:-2}"; }
q() { printf '%q' "$1"; }  # a path or branch in a suggested command, quoted (the root may have spaces)
self="bash $(q "$0")"
wip=0
if [ "${1:-}" = "--wip" ]; then wip=1; shift; fi
[ $# -le 1 ] || die "usage: $self [--wip] [<branch>]"
# Git exports GIT_DIR (and friends) to hooks; with it set `rev-parse --show-toplevel` answers $here, not the root.
root="$(unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE; git -C "$here" rev-parse --show-toplevel 2>/dev/null)" || {
  die "$here is not inside a git repository; reinstall the workflow: /gw-update"; }
cd "$root" || exit 2
config="$here/config.py"

branch="${1:-}"
if [ -z "$branch" ]; then
  branch="$(git symbolic-ref --short -q HEAD)" || branch=""
  [ -n "$branch" ] || die "detached HEAD and no branch given; check out the branch or pass it: $self <branch>"
fi
want="$(git rev-parse --verify -q "refs/heads/$branch^{commit}")" || want=""
[ -n "$want" ] || die "there is no local branch '$branch'; create it or pass an existing one: $self <branch>"
git remote get-url origin >/dev/null 2>&1 || die "the repository has no remote 'origin'; add it: git remote add origin <url>"
# `config.py get` validates the whole config (the schema keeps both keys non-negative integers): one message for any
# invalid config, with the command that says what is wrong.
{ delays="$(python3 "$config" --root "$root" get pushRetryDelays 2>/dev/null)" &&
  lstimeout="$(python3 "$config" --root "$root" get pushLsRemoteTimeout 2>/dev/null)"; } ||
  { [ "$wip" -eq 1 ] && delays="$(python3 "$config" default pushRetryDelays 2>/dev/null)" &&  # E84: a red WIP may break its gw.json
    lstimeout="$(python3 "$config" default pushLsRemoteTimeout 2>/dev/null)" &&
    echo "push: warning: .claude/gw.json is invalid; the WIP push uses the default retry settings (fix it: python3 $(q "$config") --root $(q "$root") validate)" >&2; } ||
  die "invalid config (.claude/gw.json); see what is wrong and fix it: python3 $(q "$config") --root $(q "$root") validate"
retry="$self $([ "$wip" -eq 1 ] && echo '--wip ')$(q "$branch")"
if [ "$wip" -eq 1 ]; then
  protected="$(python3 "$config" --root "$root" get protectedBranch 2>/dev/null)" || protected=""  # unreadable: the hook judges it
  [ -z "$protected" ] || [ "$branch" != "$protected" ] ||
    die "--wip never pushes to the protected branch ($protected); push a working branch with --wip, or follow the main-branch rules of AGENTS.md" 1
  subject="$(git log -1 --format=%s "$want")"
  case "$subject" in
    "WIP:"*) ;;
    *) die "--wip needs the head commit of '$branch' to start with 'WIP:' (it is '$subject'); amend its message, or wait for the check and push without --wip: $self $(q "$branch")" 1 ;;
  esac
  export GW_PUSH_WIP=1
else
  unset GW_PUSH_WIP  # a stray value must not skip the hook's check on a normal push
fi
out="$(mktemp "${TMPDIR:-/tmp}/gw-push.XXXXXX")" || die "cannot create a temp file; free space and retry"

lsout="$out.ls"
ls_pid=""  # the running ls-remote: its pid is also its process group (set -m)
stop_ls() {
  [ -n "$ls_pid" ] || return 0
  kill -TERM -- "-$ls_pid" 2>/dev/null
  wait "$ls_pid" 2>/dev/null
  ls_pid=""
}
trap 'stop_ls; rm -f "$out" "$lsout"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
timed_out=0
# `git ls-remote` limited to $lstimeout seconds: run it in the background and poll (bash 3.2, no `timeout` binary).
# `set -m` gives the job its own process group, so a timeout or an interrupt kills git and its transport together; it
# also keeps the terminal's Ctrl-C from reaching the job, which is why the INT/TERM/EXIT traps stop it.
limited_ls_remote() {
  local ticks=0 max=$((lstimeout * 10)) start=$SECONDS rc
  timed_out=0
  set -m
  git ls-remote origin "refs/heads/$branch" >"$lsout" 2>/dev/null </dev/null &
  ls_pid=$!
  set +m
  while kill -0 "$ls_pid" 2>/dev/null; do
    # Ticks undercount on a loaded machine (each `sleep 0.1` takes longer), so wall time ($SECONDS, whole seconds:
    # a difference over the limit means at least that many seconds really passed) stops it too.
    if [ "$lstimeout" -gt 0 ] && { [ "$ticks" -ge "$max" ] || [ $((SECONDS - start)) -gt "$lstimeout" ]; }; then
      stop_ls
      timed_out=1
      return 124
    fi
    sleep 0.1
    ticks=$((ticks + 1))
  done
  wait "$ls_pid"; rc=$?
  ls_pid=""
  return "$rc"
}
remote_got=""
# remote_got = the sha of the branch on origin (empty when absent); non-zero when ls-remote fails or times out
read_remote() {
  remote_got=""
  limited_ls_remote || return 1
  remote_got="$(awk 'NR==1 {print $1}' "$lsout")"
}
# 0 = origin has the commit, 1 = it answered with something else, 2 = it could not be read
remote_state() {
  read_remote || return 2
  [ "$remote_got" = "$want" ] && return 0
  return 1
}
unreadable_note() {
  [ "$timed_out" -eq 1 ] && echo "push: git ls-remote origin took over ${lstimeout}s and was stopped (pushLsRemoteTimeout in .claude/gw.json; 0 = no limit)" >&2
  return 0
}

# Only the lines git, the transport and the remote write are classified: the output of the pre-push hook that
# passed (its own `pre-push:` lines, the tests it ran) must not decide anything.
git_lines='^(error|fatal|remote|hint|warning): |^ ! |^curl |^ssh: |^kex_|^Connection |^Failed to connect|^OpenSSL|^gnutls|^Could not resolve'
# Not transient even if another line looks like it: a rejection by the remote or a refused access (408 is transient).
permanent=' ! \[(rejected|remote rejected)\]|fetch first|non-fast-forward|hook declined|returned error: 40[0-79]|HTTP/?[0-9.]* 40[0-79]|Authentication failed|Permission denied \(|could not read Username|protected branch'
transient='Could not resolve host|Temporary failure in name resolution|Network is unreachable|Couldn.t connect to server|Failed to connect|Connection (was )?(reset|refused|timed out|closed)|Operation timed out|RPC failed|early EOF|unexpected disconnect|remote end hung up|kex_exchange_identification|SSL_ERROR_SYSCALL|SSL_read|gnutls_handshake|Internal Server Error|Bad Gateway|Service Unavailable|Gateway Time-?out|Request Timeout|error: 5[0-9][0-9]|error: 408|HTTP/?[0-9.]* (5[0-9][0-9]|408)|HTTP code (5[0-9][0-9]|408)'

attempt=0
rest="$delays"
while :; do
  attempt=$((attempt + 1))
  if [ "$wip" -eq 1 ]; then  # E84: only this branch (push.followTags or a push refspec must not add tags: the hook refuses them)
    git push -u --no-follow-tags origin "refs/heads/$branch:refs/heads/$branch" 2>&1 | tee "$out"
  else
    git push -u origin "$branch" 2>&1 | tee "$out"
  fi
  code="${PIPESTATUS[0]}"
  remote_state; state=$?
  [ "$state" -eq 2 ] && [ "$code" -ne 0 ] && unreadable_note  # the push failed too: say why origin could not be read
  if [ "$state" -eq 2 ] && [ "$code" -eq 0 ]; then
    # The push said OK but the check itself failed (a blip): retry only the check, with the same delays.
    for d in $delays; do
      echo "push: cannot read origin yet; checking again in ${d}s" >&2
      sleep "$d"
      remote_state; state=$?
      [ "$state" -ne 2 ] && break
    done
    unreadable_note
    [ "$state" -ne 2 ] || die "git push said OK but origin cannot be read to confirm it; check the network and the remote: git ls-remote origin refs/heads/$branch" 1
  fi
  if [ "$state" -eq 0 ]; then
    if [ "$code" -ne 0 ]; then  # the push failed late but the remote has it: leave what -u would have left
      git fetch -q origin "$branch" >/dev/null 2>&1 && git branch -q --set-upstream-to="origin/$branch" "$branch" >/dev/null 2>&1 ||
        echo "push: warning: could not update origin/$branch or its upstream; run: git fetch origin $branch && git branch --set-upstream-to=origin/$branch $branch" >&2
    fi
    echo "push: ok: origin/$branch is at $want"
    exit 0
  fi
  if [ "$code" -eq 0 ]; then
    die "git push said OK but origin/$branch is not at $want (remote: ${remote_got:-absent}); check the remote and retry: git ls-remote origin refs/heads/$(q "$branch") && $retry" 1
  fi
  lines="$(grep -E "$git_lines" "$out" | grep -v '^pre-push:')"
  if printf '%s\n' "$lines" | grep -Eiq "$permanent" || ! printf '%s\n' "$lines" | grep -Eiq "$transient"; then
    echo "push: failed and not retrying: the error is not a transient network one (read the git output above)." >&2
    if printf '%s\n' "$lines" | grep -Eiq 'non-fast-forward|fetch first|\[rejected\]'; then
      echo "push: the remote has commits you lack; bring them in and push again: git fetch origin $branch && git merge --no-edit origin/$branch && $retry" >&2
    elif printf '%s\n' "$lines" | grep -Eiq 'returned error: 40[0-9]|HTTP/?[0-9.]* 40[0-9]|Authentication failed|Permission denied|could not read Username'; then
      echo "push: access was refused; check the credentials or permissions for origin: git remote -v" >&2
    else
      echo "push: a hook or the remote rejected it; read its output above, fix that and run again: $retry" >&2
    fi
    exit 1
  fi
  delay="$(printf '%s\n' "$rest" | sed -n 1p)"
  if [ -z "$delay" ]; then
    die "transient failure and the $attempt attempt(s) are used up (pushRetryDelays); check the network and run again: $retry" 1
  fi
  rest="$(printf '%s\n' "$rest" | sed 1d)"
  echo "push: transient failure (attempt $attempt); retrying in ${delay}s" >&2
  sleep "$delay"
done
