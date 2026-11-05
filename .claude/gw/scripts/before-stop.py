#!/usr/bin/env python3
# galivelop-workflow v0.5.0
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
  b. the working tree has changes (`git status`, untracked files included, but not untracked paths under
     `.claude/worktrees/`, where Claude Code keeps its isolated worktrees) and the log (`log` in .claude/gw.json) is
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
import glob
import json
import os
import posixpath
import select
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, HERE)
import config  # noqa: E402

STDIN_WAIT = 3.0
GIT_TIMEOUT = 30
PUSH_MARKER = "gw-push-in-progress"  # written by templates/githooks/pre-push while it runs
PUSH_MARKER_MAX_AGE = 3600  # seconds: an older marker is a push that died without cleaning up
WORKTREES_PREFIX = ".claude/worktrees/"


class GitError(Exception):
    pass


def git(root, *args, check=True):
    """(returncode, stdout) of `git -C root ...`; with check, a failure raises GitError naming the command."""
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=GIT_TIMEOUT)
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
        ready, _, _ = select.select([sys.stdin], [], [], STDIN_WAIT)
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


def _marker_branch(marker, head):
    """The branch a live, recent marker file lists for `head`, else None."""
    try:
        age = time.time() - os.stat(marker).st_mtime
        with open(marker, encoding="utf-8") as f:
            lines = f.read(4096).splitlines()
        pid_text = lines[0].strip() if lines else ""
        if not pid_text.isdigit() or not (-300 < age < PUSH_MARKER_MAX_AGE):
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


def changed_paths(root):
    """The set of paths `git status` lists (untracked files included; both sides of a rename). Raises GitError.
    Untracked paths under `.claude/worktrees/` (Claude Code's isolated worktrees live there) do not count."""
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
        paths.add(posixpath.normpath(entry[3:]))
        if entry[0] in "RC" or entry[1] in "RC":  # `-z` puts the origin of a rename in the next entry
            if i < len(entries) and entries[i]:
                paths.add(posixpath.normpath(entries[i]))
            i += 1
    return paths


def main():
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
                    if pushing is None:
                        blocks.append(f"Branch '{branch}' has {plural(count, 'commit')} not pushed ({where}). What is "
                                      f"not pushed does not exist for the next session; push it now: git push -u "
                                      f"origin {branch}")
                    else:
                        notes.append(f"A push of this commit is in progress (the pre-push hook is running"
                                     f"{' for ' + pushing if pushing else ''}); branch '{branch}' has "
                                     f"{plural(count, 'commit')} not pushed ({where}) until it ends. Do not push "
                                     f"again: wait for it and check git status -sb afterwards.")
        except GitError as exc:
            warns.append(str(exc))
        try:
            paths = changed_paths(root)
            if paths and log not in paths:
                blocks.append(f"The working tree has {plural(len(paths), 'uncommitted change')} and the log ({log}) "
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
