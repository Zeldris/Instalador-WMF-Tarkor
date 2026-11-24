#!/usr/bin/env python3
# galivelop-workflow v0.9.0
"""PreToolUse hook on Edit, Write, MultiEdit and NotebookEdit (C4, C5, `modes.questions`): editing code while the current
task has open questions in the questions file (questions.py) is blocked (restrictive mode) or warned about (guide mode).

Which project, task and questions (docs/design/I-lifecycle.md, "Tarea en curso del modo restrictivo"):
  - the project is config.find_root() (this script's repo when it holds .claude/gw.json, else $CLAUDE_PROJECT_DIR or the
    current directory: a plugin install works too); the edited file (`tool_input.file_path`, or `notebook_path`, with its
    symlinks resolved; on a case-insensitive file system a path in another case is matched with samefile) belongs to it
    when its git worktree shares the project's git common dir. A file outside (another repo, the scratchpad) is allowed;
  - the worktree of the edited file gives the branch, the config (mode, taskId) and the git dir of the marks, so an
    edit in a subagent's linked worktree reads that worktree's branch;
  - the current task is task.py current_task(): the id of a branch `agent/<id>-...`, else the mark `gw/current-task` in
    that worktree's git dir (`task.py new|current <id>` write it, `handoff.py close-row <id>` removes it). No current
    task: allowed, silently (like a question without Refs, which blocks no task);
  - the questions file is the MAIN worktree's (the one of `git rev-parse --git-common-dir`; else the edited file's): the
    main session records a subagent's questions there (C10). Its open questions whose Refs name the task exactly count
    (questions.open_for_task); accepted-risk, answered and other tasks' questions do not. The commands the messages give
    carry `--root <main worktree>` when it is not the edited file's worktree;
  - the file is code when the project's `is-code.sh --list` says so (its copy in .claude/gw/scripts/, else scripts/;
    with none, the same rule in Python on the `content`, `reviewMark` and `ciLocalLog` keys). Documentation, `content`
    and the questions file itself are always allowed, before anything else is read: writing the design is not
    implementing it. A file is code also when it cannot be classified or placed (a Windows drive path on another system,
    an event it cannot read): the safe side.

What it does with open questions and a code file:
  - `modes.questions: true` (restrictive, C4): deny (permissionDecision `deny`), naming each open question (id and one
    line) and the two ways on, both the user's call (config-guard.py asks before `questions.py accept-risk` and
    `task.py current <id>|--clear`): `questions.py answer "<n>. <answer>"` or `questions.py accept-risk --refs <id>`;
  - `false` (guide, C5, the default): allow, with `additionalContext` recommending to answer them or to accept the risk,
    once per task and set of open questions (the mark `gw/questions-warned` in the git dir; a new question warns again).

Fails closed in restrictive mode: a questions file it cannot read or parse, or git hanging (task.GIT_TIMEOUT), denies
code edits with the reason and the fix; guide mode gives a one-line warning, once per reason. A .claude/gw.json that
exists but cannot be read counts as restrictive for code edits (the file itself can still be edited, to fix it); a missing
one leaves the defaults (guide mode, docs/questions.md). Not covered: code written by Bash (`sed -i`, `cat >`, `tee`,
`git apply`...): only careful.py and config-guard.py look at Bash, for what they cover. Output: nothing ("no opinion")
or one JSON object on stdout, exit 0 (https://code.claude.com/docs/en/hooks.md, PreToolUse). Python 3.8+ standard
library only.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, HERE)
import config  # noqa: E402
import questions  # noqa: E402
import task  # noqa: E402

TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
WARNED = "gw/questions-warned"
DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
POLICY = re.compile(r"^(\.claude/(gw\.json|settings\.json|gw/)|\.githooks/)")  # is-code.sh's: always code


def git(where, *argv):
    """stdout of a git call, or None when it fails; raises task.GitStuck when it hangs."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        r = subprocess.run(["git", "-C", str(where), *argv], capture_output=True, text=True, env=env,
                           stdin=subprocess.DEVNULL, timeout=task.GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise task.GitStuck(f"`git {argv[0]}` took more than {task.GIT_TIMEOUT:.0f}s")
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def read_event():
    if sys.stdin is None or sys.stdin.isatty():
        return None
    try:
        data = json.loads(sys.stdin.read())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def emit(spec):
    print(json.dumps({"hookSpecificOutput": dict({"hookEventName": "PreToolUse"}, **spec)}))


def target_path(event):
    """The edited file as an absolute path with its symlinks resolved, or None when the event names none it can place."""
    tool_input = event.get("tool_input") if isinstance(event, dict) else None
    if not isinstance(tool_input, dict):
        return None
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(raw, str) or not raw.strip():
        return None
    if os.name != "nt":
        if DRIVE.match(raw):
            return None  # a Windows drive path cannot be placed here
        raw = raw.replace("\\", "/")
    if not os.path.isabs(raw):
        cwd = event.get("cwd")
        raw = os.path.join(cwd if isinstance(cwd, str) and os.path.isabs(cwd) else os.getcwd(), raw)
    return os.path.realpath(raw)  # a symlink outside the repo to a file inside it is that file


def existing_dir(path):
    d = os.path.dirname(path)
    while d and not os.path.isdir(d):
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent
    return d or None


def common_dir(where):
    out = git(where, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return os.path.normcase(os.path.realpath(out)) if out else None


def same_dir(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def relative(path, top):
    """`path` relative to `top` (posix), or None when it is not inside. A path in another case on a case-insensitive file
    system (macOS, Windows) is matched by walking up its folders with samefile."""
    top = os.path.realpath(top)
    rel = os.path.relpath(path, top)
    if rel != os.curdir and rel != os.pardir and not rel.startswith(os.pardir + os.sep):
        return rel.replace(os.sep, "/")
    parts, d = [], path
    while True:
        parent, name = os.path.split(d)
        if same_dir(d, top):
            return "/".join(reversed(parts)) if parts else None
        if parent == d or not name:
            return None
        parts.append(name)
        d = parent


def place(path, home):
    """(worktree root, repo-relative path) of `path`; (None, None) when it is outside the project at `home`."""
    folder = existing_dir(path)
    top = git(folder, "rev-parse", "--show-toplevel") if folder else None
    if not top or common_dir(top) != common_dir(home):
        return None, None
    rel = relative(path, top)
    return (Path(top), rel) if rel else (None, None)


def main_worktree(top):
    """The main worktree of the repository at `top` (where the main session keeps the questions, C10), else `top`."""
    common = git(top, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common:
        main = os.path.dirname(os.path.realpath(common))
        found = git(main, "rev-parse", "--show-toplevel") if os.path.isdir(main) else None
        if found and same_dir(found, main):
            return Path(found)
    return Path(top)


def load(top):
    """(config, broken): the config at `top` with its defaults; a missing one gives the defaults, a broken one the
    defaults and the reason."""
    try:
        return config.load(top), None
    except Exception as exc:  # noqa: BLE001
        broken = None if not (Path(top) / ".claude" / "gw.json").is_file() else str(exc).splitlines()[0][:200]
        return {"_root": Path(top)}, broken


def is_code(rel, top, cfg):
    """True unless `rel` is content, by the project's is-code.sh (or the same rule in Python when it has none); a
    failure counts as code (the safe side)."""
    for candidate in (Path(top) / ".claude" / "gw" / "scripts" / "is-code.sh", Path(top) / "scripts" / "is-code.sh"):
        if candidate.is_file():
            try:
                r = subprocess.run(["bash", str(candidate), "--list", rel], cwd=str(top), capture_output=True, text=True,
                                   env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
                                   stdin=subprocess.DEVNULL, timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                return True
            return r.returncode != 0 or rel in r.stdout.splitlines()
    if POLICY.search(rel):
        return True
    if rel in (cfg.get("reviewMark"), cfg.get("ciLocalLog")):
        return False
    for pattern in cfg.get("content") or config.schema_default("content") or []:
        try:
            if re.search(pattern, rel):
                return False
        except re.error:
            return True
    return True


def script(name, root, top):
    """How a message names one of the workflow's scripts, with `--root` when the questions live in another worktree."""
    own = Path(root) / ".claude" / "gw" / "scripts" / name
    full = own if own.is_file() else Path(HERE) / name
    rel = os.path.relpath(str(full), str(top))
    cmd = "python3 " + (str(full) if rel.startswith(os.pardir) else rel)
    return cmd + (f" --root {root}" if not same_dir(root, top) else "")


def warned_key(task_id, entries):
    return f"{task_id}: " + ",".join(e.id for e in sorted(entries, key=lambda e: e.number))


def warn_once(top, key):
    """True the first time `key` is seen in this worktree (and records it); True also when the mark cannot be kept."""
    out = git(top, "rev-parse", "--git-path", WARNED)
    if not out:
        return True
    mark = (Path(top) / out).resolve()
    try:
        seen = mark.read_text(encoding="utf-8").splitlines() if mark.exists() else []
    except (OSError, UnicodeDecodeError):
        seen = []
    if key in seen:
        return False
    try:
        mark.parent.mkdir(parents=True, exist_ok=True)
        with open(mark, "a", encoding="utf-8") as f:
            f.write(key + "\n")
    except OSError:
        pass  # the worst case is warning once more
    return True


def stop(restrictive, top, reason, key):
    """Deny in restrictive mode; in guide mode a one-line warning, once per `key`."""
    if restrictive:
        emit({"permissionDecision": "deny", "permissionDecisionReason": f"questions-guard (restrictive mode): {reason}"})
    elif warn_once(top, key):
        emit({"additionalContext": f"questions-guard: {reason}"})


def home_root(event):
    try:
        return Path(config.find_root())
    except Exception:  # noqa: BLE001
        cwd = event.get("cwd") if isinstance(event, dict) else None
        return config.git_toplevel(cwd) if isinstance(cwd, str) and os.path.isabs(cwd) else None


def main():
    event = read_event()
    if event is not None and event.get("tool_name") not in TOOLS:
        return 0
    home = home_root(event)
    if home is None:
        return 0  # not inside a git repository: there is no task to guard
    path = target_path(event) if event is not None else None
    top, rel = (home, None) if path is None else place(path, home)
    if top is None:
        return 0  # outside the project
    cfg, broken = load(top)
    if broken and rel == ".claude/gw.json":
        return 0  # the way to fix it
    root = main_worktree(top)
    qcfg, qbroken = (cfg, None) if same_dir(root, top) else load(root)
    qcfg = cfg if qbroken else qcfg
    qfile = Path(root) / config.questions_path(qcfg)
    if rel is not None and (same_dir(path, qfile) if os.path.exists(path) else
                            os.path.normcase(path) == os.path.normcase(os.path.realpath(qfile))):
        return 0  # the questions file itself
    if rel is not None and not is_code(rel, top, cfg):
        return 0  # documentation and content
    restrictive = True if broken else bool(config.modes(cfg)["questions"])
    if broken:
        stop(True, top, f".claude/gw.json cannot be read ({broken}), so it cannot tell the mode nor the task's "
                        f"questions; fix it and check it: {script('config.py', top, top)} validate", "broken-config")
        return 0
    try:
        task_id, _ = task.current_task(top, cfg)
    except task.GitStuck as exc:
        stop(restrictive, top, f"git did not answer ({exc}), so it cannot tell the current task; check the repository "
                               f"(git status, a stale .git/index.lock) and try again", "git-stuck")
        return 0
    if not task_id:
        return 0
    q = script("questions.py", root, top)
    try:
        entries = questions.open_for_task(qfile, task_id)
    except (questions.QuestionsError, OSError, UnicodeDecodeError) as exc:
        where = os.path.relpath(qfile, str(top))
        stop(restrictive, top, f"the questions file {where} cannot be read ({exc}), so it cannot tell whether task "
                               f"{task_id} has open questions; fix the file (it can be edited), then check it: {q} list",
             f"broken: {exc}")
        return 0
    if not entries:
        return 0
    listed = "\n".join(f"  {e.id}: {questions.one_line(e.get('Question'))[:160]}" for e in entries)
    first = entries[0].number
    target = f"`{rel}`" if rel else "this file (the event named none it could read)"
    if restrictive:
        emit({"permissionDecision": "deny",
              "permissionDecisionReason": f"questions-guard (restrictive mode): task {task_id} has {len(entries)} open "
              f"question(s), so code ({target}) cannot be edited yet:\n{listed}\nAsk the user, then record the answer: "
              f"{q} answer \"{first}. <answer>\"; or, if the user decides to go on without one: {q} accept-risk "
              f"--refs {task_id}. Documentation and `content` files can still be edited."})
        return 0
    if warn_once(top, warned_key(task_id, entries)):
        emit({"additionalContext": f"questions-guard (guide mode): task {task_id} has {len(entries)} open question(s) "
              f"before implementing:\n{listed}\nRecommended: ask the user and record the answer: {q} answer "
              f"\"{first}. <answer>\"; to go on anyway, if the user decides so: {q} accept-risk --refs {task_id} (this "
              f"warning is shown once per set of open questions)."})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 (fail closed in restrictive mode; in guide mode say why)
        why = f"questions-guard.py failed ({type(exc).__name__}: {exc}); check it: python3 {os.path.join(HERE, 'questions-guard.py')}"
        try:
            cfg, broken = load(home_root(None))
            strict = bool(broken) or bool(config.modes(cfg)["questions"])
        except Exception:  # noqa: BLE001
            strict = True
        emit({"permissionDecision": "deny", "permissionDecisionReason": why} if strict else {"additionalContext": why})
        sys.exit(0)
