#!/usr/bin/env python3
# galivelop-workflow v0.6.0
"""Stop hook: do not let Claude finish with commits that are not pushed, or with changes the log does not mention.

"What is not pushed does not exist" (AGENTS.md) is the workflow's most important rule and, until this hook, only the
agent remembered it. It blocks the stop when:

  a. the current branch has commits its upstream does not (`git rev-list @{u}..HEAD`); with no upstream, commits no
     remote branch has (`git rev-list HEAD --not --remotes`). The reason names `git push -u origin <branch>`. On the
     protected branch (`protectedBranch`) it does not: AGENTS.md says a push there needs the user's confirmation and
     the three phases, so Claude cannot fix it alone and a block would only make it push without asking. There it is a
     warning to the user (`systemMessage`: the commits are not pushed, and pushing needs their confirmation), never
     a block;
     While the workflow's pre-push hook is pushing this very HEAD (markers `gw-push-in-progress.<pid>` in this worktree's git dir:
     a live pid, under an hour old, the current HEAD sha among the local shas it lists) it does not block either: a
     second push would race the first, so it is a warning that says to wait and check `git status -sb`. A marker of
     another branch or of an older HEAD (commits made after the push started), dead, old, empty or unreadable
     blocks as before;
     While a check of the workflow holds the lock `<git common dir>/gw/check.lock` (a symlink to "pid|start|sha|log",
     written by check-green.sh lock-acquire; the pid alive with that same start time) it does not block either: the
     check ends by itself and a push now would race it, so it is a one-line notice with the check's log. Only a lock whose sha is this
     worktree's HEAD (12 hex, with or without -dirty) silences it; one of another commit or worktree adds a note and blocks.
     A lock that is dead, reused by another process, malformed or missing counts as absent and blocks as before;
     D88: while background subagents of this session still run (read from the transcript the hook's stdin names in
     `transcript_path`, see running_subagents) it does not block either: it is a one-line notice to wait for them and
     push after (format of that transcript: observed 2026-11-11 in real Claude Code 2.1.322 transcripts, undocumented).
     A start older than `stopSubagentMaxAge` seconds is ignored. Background Bash commands are not counted (a dev server could silence the reminder for good). Any
     trouble reading the transcript means "none running", so the block stays;
  b. the working tree has changes (`git status`, untracked files included, but not untracked paths under
     `.claude/worktrees/`, where Claude Code keeps its isolated worktrees, nor the token ledger `metrics.ledger`,
     which the metrics.py Stop hook rewrites on every stop) and the log (`log` in .claude/gw.json) is
     not among them. The reason says to commit the log, updated, in the same commit as the work.

Output format (https://code.claude.com/docs/en/hooks.md, "Stop decision control"): a block is a JSON object on stdout
with exit 0, `{"decision": "block", "reason": "..."}`; Claude Code feeds `reason` back to Claude as the explanation
for why it should continue ("`reason` ... Tells Claude why it should continue"). The page also documents exit 2 with
the reason on stderr as equivalent; JSON is used because the same exit-0 answer can carry `systemMessage`
("Warning message shown to the user"), which is what the warnings below use.

No loop: when stdin says `stop_hook_active` is true (Claude Code is already continuing because of a stop hook) it
exits 0 silently, as the page asks ("Check this value ... to avoid blocking on a condition that will never resolve").

It is a reminder, not a gate. Without git, without a valid config, with a git command that fails or with a stdin it
cannot read it never blocks: it exits 0 and shows the user a `systemMessage` that names `python3 <here>/doctor.py`.
The same for a repository with no remote (there is nothing to push to).

Project root: config.find_root (the script's own repo when it holds .claude/gw.json, else the project the hook runs
in), so it works from the plugin's scripts/ and from a project's .claude/gw/scripts/. Python 3.8+ standard library only.
"""
import datetime
import glob
import json
import os
import posixpath
import re
import select
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, HERE)
import config  # noqa: E402

GIT_TIMEOUT = None  # main() sets the config values (stopGitTimeout, stopPushMarkerMaxAge); None: the schema default
PUSH_MARKER = "gw-push-in-progress"  # written by templates/githooks/pre-push while it runs
CHECK_LOCK = os.path.join("gw", "check.lock")  # under the git common dir; written by check-green.sh lock-acquire
PUSH_MARKER_MAX_AGE = None  # seconds: an older marker is a push that died without cleaning up
WORKTREES_PREFIX = ".claude/worktrees/"


class GitError(Exception):
    pass


def git(root, *args, check=True):
    """(returncode, stdout) of `git -C root ...`; with check, a failure raises GitError naming the command."""
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=GIT_TIMEOUT or config.schema_default("stopGitTimeout"))
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(f"git {args[0]} could not run ({exc})")
    if check and r.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {(r.stderr or r.stdout).strip() or 'exit ' + str(r.returncode)}")
    return r.returncode, r.stdout


def read_event():
    """The hook's JSON object from stdin, or None when there is none (nothing arrives, not JSON, not an object)."""
    if sys.stdin is None or sys.stdin.isatty():
        return None
    try:
        ready, _, _ = select.select([sys.stdin], [], [], config.hook_stdin_wait())
        if not ready:
            return None
        data = json.loads(sys.stdin.read())
    except (OSError, ValueError, TypeError):  # no select on this stream, closed stdin, empty or invalid JSON
        return None
    return data if isinstance(data, dict) else None


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def unpushed(root):
    """(branch, count, where) of the commits the current branch has that nowhere else has; None when there is
    nothing to push or nothing to compare with (detached HEAD, no commits). Raises GitError."""
    rc, branch = git(root, "symbolic-ref", "-q", "--short", "HEAD", check=False)
    branch = branch.strip()
    if rc != 0 or not branch:
        return None  # detached HEAD: no branch to push
    if git(root, "rev-parse", "-q", "--verify", "HEAD", check=False)[0] != 0:
        return None  # no commits yet
    rc, upstream = git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False)
    if rc == 0 and upstream.strip():
        upstream = upstream.strip()
        count = int(git(root, "rev-list", "--count", f"{upstream}..HEAD")[1].strip() or 0)
        where = f"not on {upstream}"
    else:
        if not git(root, "remote")[1].strip():
            raise GitError("this repository has no remote, so there is nothing to push to")
        count = int(git(root, "rev-list", "--count", "HEAD", "--not", "--remotes")[1].strip() or 0)
        where = "no upstream branch, and not on any remote branch"
    return (branch, count, where) if count else None


def push_in_progress(root):
    """The branch name of the push of the current HEAD that the workflow's pre-push hook is running right now, else None.

    Each push keeps `gw-push-in-progress.<pid>` in this worktree's git dir (not shared with other worktrees): line 1 its
    pid, then one "<local sha> <local branch>" line per ref it pushes. A marker counts only with a live pid
    (PermissionError: another user's process is alive too), an mtime under PUSH_MARKER_MAX_AGE seconds old, and the
    current HEAD sha among its shas: a push of another branch, or of an older HEAD, does not carry what is unpushed
    here. Anything else (unreadable, garbage, dead pid, old, other sha) is skipped; with no marker left, None."""
    try:
        gitdir = git(root, "rev-parse", "--git-dir")[1].strip()  # per worktree; relative to root in the main checkout
        head = git(root, "rev-parse", "-q", "--verify", "HEAD^{commit}")[1].strip()
        markers = sorted(glob.glob(os.path.join(glob.escape(os.path.join(str(root), gitdir)), PUSH_MARKER + ".*")))
    except (GitError, OSError, ValueError):
        return None
    for marker in markers:
        found = _marker_branch(marker, head)
        if found is not None:
            return found
    return None


def _ps(field, pid):
    """`ps -o <field>= -p pid` with the spaces squeezed, or "" (gone, or no ps)."""
    try:
        r = subprocess.run(["ps", "-o", field + "=", "-p", str(pid)], capture_output=True, text=True, timeout=10,
                           env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        return ""
    return " ".join(r.stdout.split())


def check_in_progress(root):
    """(pid, log, sha) of the live check that holds the E20 lock `<git common dir>/gw/check.lock`, else None.

    The lock is a symlink whose target is "pid|process start|sha|log" (check-green.sh lock-acquire). Liveness is
    judged as check-green.sh `proc_is` does: the pid is not a zombie and its current start time (`ps -o lstart=`, or
    "?" when ps cannot tell but the process exists) equals the lock's non-empty start. Anything else (missing, dead,
    reused pid, malformed, any error reading it) is None, so the hook falls back to blocking."""
    try:
        common = git(root, "rev-parse", "--git-common-dir")[1].strip()
        target = os.readlink(os.path.join(str(root), common, CHECK_LOCK))
    except (GitError, OSError, ValueError):
        return None
    pid_text, start, sha, log = (target.split("|", 3) + ["", "", "", ""])[:4]
    if not pid_text.isdigit() or not 0 < int(pid_text) < 2 ** 31:
        return None
    pid = int(pid_text)
    try:
        os.kill(pid, 0)
    except PermissionError:
        pass  # another user's process is alive too
    except (OSError, OverflowError, ValueError):
        return None
    if _ps("stat", pid).startswith("Z") or not start:
        return None
    if (_ps("lstart", pid) or "?") != start:
        return None
    return pid, log, sha


def running_subagents(path, tail_bytes, max_age=0, now=None):
    """The ids of the background subagents of this session that have not reported back yet (D88), as a sorted list.

    The transcript format below is internal to Claude Code and undocumented: observed 2026-11-11 in real session
    transcripts (Claude Code 2.1.322). `path` is the hook's `transcript_path` (JSONL). Only its last `tail_bytes`
    bytes are read (a long session's transcript is huge; 0 turns the look off), and a first line the tail cut in the
    middle is dropped. In file order:
      - start: the tool_result of an `Agent` tool_use with `input.run_in_background: true` whose text STARTS with
        "Async agent launched successfully." gives the id in its first `agentId: <id>` line;
      - end: a `<task-notification>` with `<task-id>` and any `<status>` but `running`. It arrives as a `user` entry
        (`origin.kind` "task-notification", or no origin) or, when the main agent is mid-turn, as an `attachment`
        entry whose `attachment.type` is `queued_command` and whose `prompt` starts with it; a user entry with another
        `origin.kind` (pasted text) does not count;
      - restart: a `SendMessage` tool_use whose `input.to` is an id already seen, unless its tool_result says
        `is_error` (the agent was not resumable).
    With `max_age` > 0 a start older than that many seconds (the entry's `timestamp`; `now` is for tests) is ignored:
    an agent that died without notifying (container restart, resumed in another session) must not silence the push
    reminder for good. On any trouble (no path, unreadable, bad size, odd lines) the answer is [], that is, none
    running: the caller then keeps blocking on unpushed commits (the hook fails closed); it never raises."""
    if not path or not isinstance(path, str) or not isinstance(tail_bytes, int) or tail_bytes <= 0:
        return []
    try:
        with open(path, "rb") as f:
            size = f.seek(0, os.SEEK_END)
            start = max(0, size - tail_bytes)
            f.seek(max(0, start - 1))  # one byte before: tells whether the tail begins at a line start
            data = f.read(size - max(0, start - 1))
    except (OSError, ValueError, OverflowError, MemoryError):
        return []
    lines = data.split(b"\n")
    if start > 0:
        lines = lines[1:]  # data[0] is the byte before the tail: either "\n" (empty first piece) or a cut line
    now = time.time() if now is None else now
    state = {}  # id -> epoch of its last start/restart (None: unknown), or False once it ended
    background, pending = set(), {}  # Agent tool_use ids in background; SendMessage tool_use id -> (target, before)
    for raw in lines:
        if b"agentId" not in raw and b"task-notification" not in raw and b"SendMessage" not in raw \
                and b"run_in_background" not in raw and b"is_error" not in raw:
            continue  # cheap filter: most lines are none of these
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        stamp = _epoch(entry.get("timestamp"))
        att = entry.get("attachment")
        if entry.get("type") == "attachment" and isinstance(att, dict) and att.get("type") == "queued_command":
            _notified(att.get("prompt"), state)
            continue
        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list):
            continue
        origin = entry.get("origin")
        for item in content:
            if not isinstance(item, dict):
                continue
            kind, inp = item.get("type"), item.get("input")
            if kind == "tool_use" and isinstance(inp, dict):
                if item.get("name") == "Agent" and inp.get("run_in_background") is True:
                    background.add(item.get("id"))
                elif item.get("name") == "SendMessage" and isinstance(inp.get("to"), str) and inp["to"] in state:
                    pending[item.get("id")] = (inp["to"], state[inp["to"]])
                    state[inp["to"]] = stamp
            elif kind == "tool_result":
                ident = item.get("tool_use_id")
                if ident in pending:
                    if item.get("is_error") is True:  # the agent could not be resumed: back to what it was
                        state[pending[ident][0]] = pending[ident][1]
                elif ident in background:
                    text = _text_of(item.get("content"))
                    found = re.match(r"Async agent launched successfully\.[^\n]*\nagentId:\s*([A-Za-z0-9_-]+)", text)
                    if found:
                        state[found.group(1)] = stamp
            elif kind == "text" and entry.get("type") == "user":
                if not isinstance(origin, dict) or origin.get("kind") == "task-notification":
                    _notified(item.get("text"), state)
    return sorted(i for i, at in state.items()
                  if at is not False and not (max_age > 0 and at is not None and now - at > max_age))


def _notified(text, state):
    """Mark ended in `state` the id of a `<task-notification>` text whose status is not `running`."""
    if isinstance(text, str) and text.lstrip().startswith("<task-notification>"):
        ident = re.search(r"<task-id>\s*([A-Za-z0-9_-]+)\s*</task-id>", text)
        status = re.search(r"<status>\s*(\w+)\s*</status>", text)
        if ident and status and status.group(1) != "running":
            state[ident.group(1)] = False


def _epoch(stamp):
    """Seconds since the epoch of an ISO-8601 `timestamp` ("2026-11-03T23:09:25.870Z"), or None."""
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _text_of(content):
    """The text of a tool_result's content (a string, or a list of {"type": "text", "text": ...})."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and isinstance(c.get("text"), str))
    return ""


def _same_tree_head(root, lock_sha):
    """True when the lock's sha (`<hex>` or `<hex>-dirty`, check.sh's name for a run: HEAD abbreviated, which may be
    longer than 12 in a big repository) names this worktree's HEAD. D76: the full shas are compared, so an
    abbreviation that matches two commits cannot pass for HEAD."""
    sha = lock_sha[:-6] if lock_sha.endswith("-dirty") else lock_sha
    if len(sha) < 7 or any(c not in "0123456789abcdef" for c in sha):
        return False
    try:
        head = git(root, "rev-parse", "--verify", "-q", "HEAD")[1].strip()
        named = git(root, "rev-parse", "--verify", "-q", sha + "^{commit}")[1].strip()
    except GitError:
        return False
    return bool(head) and named == head


def _marker_branch(marker, head):
    """The branch a live, recent marker file lists for `head`, else None."""
    try:
        age = time.time() - os.stat(marker).st_mtime
        with open(marker, encoding="utf-8") as f:
            lines = f.read(4096).splitlines()
        pid_text = lines[0].strip() if lines else ""
        if not pid_text.isdigit() or not (-300 < age < (PUSH_MARKER_MAX_AGE or config.schema_default("stopPushMarkerMaxAge"))):
            return None
        pid = int(pid_text)
        if pid < 1:
            return None  # kill(0, 0) would signal the whole process group
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None
        except PermissionError:
            pass
        for line in lines[1:]:
            fields = line.split()
            if fields and fields[0] == head:
                return " ".join(fields[1:])
        return None
    except (OSError, ValueError, IndexError):
        return None


def changed_paths(root, ignore=()):
    """The set of paths `git status` lists (untracked files included; both sides of a rename). Raises GitError.
    Untracked paths under `.claude/worktrees/` (Claude Code's isolated worktrees live there) do not count, nor
    does any path in `ignore` (normalized repo-relative paths: the token ledger, which metrics.py rewrites on every
    stop)."""
    out = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")[1]
    entries = out.split("\0")
    paths, i = set(), 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        if entry.startswith("?? ") and posixpath.normpath(entry[3:]).startswith(WORKTREES_PREFIX):
            continue
        if posixpath.normpath(entry[3:]) not in ignore:
            paths.add(posixpath.normpath(entry[3:]))
        if entry[0] in "RC" or entry[1] in "RC":  # `-z` puts the origin of a rename in the next entry
            if i < len(entries) and entries[i]:
                paths.add(posixpath.normpath(entries[i]))
            i += 1
    return paths


def main():
    global GIT_TIMEOUT, PUSH_MARKER_MAX_AGE
    doctor = f"python3 {os.path.join(HERE, 'doctor.py')}"
    warns, blocks, notes = [], [], []

    event = read_event()
    if event is None:  # without stop_hook_active it could loop, so it only warns
        print(json.dumps({"systemMessage": f"before-stop.py could not read the hook JSON on stdin, so it checked "
                                           f"nothing; Claude may stop. Diagnose the setup with: {doctor}"}))
        return 0
    if event.get("stop_hook_active") is True:
        return 0  # Claude is already continuing because of a stop hook: let it stop, never loop

    cfg = None
    try:
        cfg = config.load(config.find_root())
    except config.ConfigError as exc:
        warns.append(str(exc).strip().splitlines()[0] if str(exc).strip() else "no usable config")
    if cfg is not None:
        root = cfg["_root"]
        log = posixpath.normpath(cfg["log"])
        GIT_TIMEOUT = cfg["stopGitTimeout"]
        PUSH_MARKER_MAX_AGE = cfg["stopPushMarkerMaxAge"]
        severity = config.stop_severity(cfg)
        # stopSeverity: "block" stops the session, "warn" only says it in the closing message
        unpushed_to = blocks if severity["unpushed"] == "block" else notes
        log_to = blocks if severity["logRequired"] == "block" else notes
        try:
            found = unpushed(root)
            if found:
                branch, count, where = found
                if branch == cfg["protectedBranch"]:
                    notes.append(f"Branch '{branch}' is the protected branch and has {plural(count, 'commit')} not "
                                 f"pushed ({where}). They are not pushed: pushing to it needs the user's "
                                 f"confirmation and the three phases of the workflow (code review, environment, "
                                 f"close), so Claude has not pushed them.")
                else:
                    pushing = push_in_progress(root)
                    checking = check_in_progress(root) if pushing is None else None
                    if checking is not None and _same_tree_head(root, checking[2]):
                        notes.append(f"A check of this commit is running (pid {checking[0]}, log {checking[1] or '-'}); "
                                     f"branch '{branch}' has {plural(count, 'commit')} not pushed ({where}) until it "
                                     f"ends. Do not push meanwhile: wait for CHECK ok, then push: git push -u origin "
                                     f"{branch}")
                    elif pushing is None and (agents := running_subagents(
                            event.get("transcript_path"), cfg["stopTranscriptBytes"],
                            cfg["stopSubagentMaxAge"])):
                        notes.append(f"{plural(len(agents), 'background subagent')} of this session "
                                     f"{'is' if len(agents) == 1 else 'are'} still running ({', '.join(agents)}); "
                                     f"branch '{branch}' has {plural(count, 'commit')} not pushed ({where}). Wait for "
                                     f"the subagent{'' if len(agents) == 1 else 's'} to report and push after: git "
                                     f"push -u origin {branch}")
                        if checking is not None:
                            notes.append(f"A check of another commit or worktree is running (pid {checking[0]}, log "
                                         f"{checking[1] or '-'}, sha {checking[2] or '-'}); it does not cover this "
                                         f"HEAD.")
                    elif pushing is None:
                        unpushed_to.append(f"Branch '{branch}' has {plural(count, 'commit')} not pushed ({where}). What is "
                                      f"not pushed does not exist for the next session; push it now: git push -u "
                                      f"origin {branch}")
                        if checking is not None:  # a check of another commit or worktree: it does not push this one
                            notes.append(f"A check of another commit or worktree is running (pid {checking[0]}, log "
                                         f"{checking[1] or '-'}, sha {checking[2] or '-'}); it does not cover this "
                                         f"HEAD.")
                    else:
                        notes.append(f"A push of this commit is in progress (the pre-push hook is running"
                                     f"{' for ' + pushing if pushing else ''}); branch '{branch}' has "
                                     f"{plural(count, 'commit')} not pushed ({where}) until it ends. Do not push "
                                     f"again: wait for it and check git status -sb afterwards.")
        except GitError as exc:
            warns.append(str(exc))
        try:
            paths = changed_paths(root, {posixpath.normpath(config.metrics(cfg)["ledger"])})
            if paths and log not in paths:
                log_to.append(f"The working tree has {plural(len(paths), 'uncommitted change')} and the log ({log}) "
                              f"is not among them. Update the log (what is done, what is left, the next step) and "
                              f"commit it in the same commit as the work: git add {log} <files> && git commit")
        except GitError as exc:
            warns.append(str(exc))

    answer = {}
    if blocks:
        answer.update(decision="block", reason="\n".join(blocks))
    messages = list(notes)
    if warns:
        messages.append(f"before-stop.py could not check everything ({'; '.join(warns)}); it is a reminder, so "
                        f"Claude may stop. Diagnose the setup with: {doctor}")
    if messages:
        answer["systemMessage"] = " ".join(messages)
    if answer:
        print(json.dumps(answer))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # a reminder must never fail the turn: say what broke and let Claude stop
        print(json.dumps({"systemMessage": f"before-stop.py failed ({type(exc).__name__}: {exc}); Claude may stop. "
                                           f"Diagnose the setup with: python3 {os.path.join(HERE, 'doctor.py')}"}))
        sys.exit(0)
