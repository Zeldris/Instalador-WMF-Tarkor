#!/usr/bin/env python3
# galivelop-workflow v0.9.0
"""The task record (C11): the contract of a task (`<taskRecord.path>/<id>.md`) and its decision log, one file per
entry in the folder `<taskRecord.path>/<id>/` that nobody edits afterwards.

  python3 task.py [--root PATH] new <id> [--title TEXT]            create the contract from the template
  python3 task.py [--root PATH] log <id> --agent <skill|session>   create a decision log entry (commit marker pending)
  python3 task.py [--root PATH] resolve <id>                       list the entries with the commit that added each
  python3 task.py [--root PATH] new <id> --related <old>         a new requirement of <old> (C13): both get `Related:`
  python3 task.py [--root PATH] deviations [--task <id>]           list the deviations log (scope-guard.py, C13)
  python3 task.py [--root PATH] current [<id> | --clear]           the current task: with <id> write the mark, with
                                                                   --clear remove it, alone print the current one

The current task (C4, C5; docs/design/I-lifecycle.md) is the id in a branch named `agent/<id>-...` and, if the branch
names none, the per-clone mark `gw/current-task` in the git dir (`git rev-parse --git-path`, so each linked worktree has
its own and it is never committed), which `new <id>` writes only when it created the record and there was no mark (it never switches a
marked task), `current <id>` writes (config-guard.py asks first) and
`handoff.py close-row <id>` removes when it names that id. questions-guard.py and scope-guard.py read it with
current_task(); `current` prints that same id (nothing when there is none).

The shape the commit-msg hook (commit-message.py, with `taskRecord.enabled`) asks for lives here too: entry_errors and
contract_errors. The commit of an entry is NOT written into the file (that would dirty the tree after the commit, or
need a second commit): the header keeps `taskRecord.pendingMarker` and `resolve` reads the commit with
`git log --diff-filter=A` on that file, which also survives a rebase or a squash. The templates in
templates/<lang>/task.md and task-entry.md are the same text this script writes (a test pins it).
Exit 0 ok, 1 refused (each message ends with the command that fixes it). Python 3.8+, stdlib only.
"""
import argparse
import datetime
import json
import os
import posixpath
import re
import secrets
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as gwconfig  # noqa: E402

SEP = " · "  # the middle dot the entry header uses
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
SLUG = re.compile(r"[a-z0-9][a-z0-9-]*")
OPEN_QUESTIONS = {"es": "Preguntas abiertas: van a {ref}, no aqu\u00ed.",
                  "en": "Open questions: add them to {ref}, not here."}
QUESTIONS_DEFAULT = "docs/questions.md"  # the `questions.path` key of C1, when that key exists in the config
PLACEHOLDER = re.compile(r"(?:\s|\u2014|-|\*|\[[ xX]\])*")  # a body of only dashes and empty checkboxes says nothing
ACCEPTANCE = "Acceptance"  # the section whose empty body is a checkbox; the config may rename it, the template keeps it


class Refused(Exception):
    pass


def questions_ref(config, root, base):
    """How the contract names the questions file: a relative link when the file exists (md-links.py would flag a link to a
    file that does not), plain code otherwise."""
    given = config.get("questions")
    target = given.get("path") if isinstance(given, dict) and isinstance(given.get("path"), str) else QUESTIONS_DEFAULT
    if root is not None and (Path(root) / target).is_file():
        return f"[{target}]({posixpath.relpath(target, base)})"
    return f"`{target}`"


def contract_text(config, task_id, title=None, root=None):
    tr = gwconfig.task_record(config)
    lang = "es" if gwconfig.languages(config)["docs"]["primary"] == "es" else "en"
    head = f"# {task_id}{SEP}{title or ('<título>' if lang == 'es' else '<title>')}"
    parts = [head]
    for name in tr["sections"]:
        parts.append(f"## {name}\n\n" + ("- [ ] —" if name == ACCEPTANCE else "—"))
    parts.append(OPEN_QUESTIONS[lang].format(ref=questions_ref(config, root, tr["path"])))
    return "\n\n".join(parts) + "\n"


def entry_text(config, task_id, agent, date):
    tr = gwconfig.task_record(config)
    parts = [f"# {date}{SEP}{agent}{SEP}{tr['pendingMarker']}{SEP}{task_id}"]
    parts += [f"## {name}\n\n—" for name in tr["logSections"]]
    return "\n\n".join(parts) + "\n"


def sections_of(text):
    """[(heading, body)] of the `## ` sections of a Markdown text, outside code fences."""
    out, fence = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fence = not fence
        if not fence and line.startswith("## "):
            out.append([line[3:].strip(), []])
        elif out:
            out[-1][1].append(line)
    return [(h, "\n".join(b).strip()) for h, b in out]


def contract_errors(text, config):
    """Why `text` is not a contract of the task record (the `sections`, each heading once and in order); [] if it is."""
    wanted = gwconfig.task_record(config)["sections"]
    found = [h.lower() for h, _ in sections_of(text)]
    missing = [w for w in wanted if w.lower() not in found]
    if missing:
        return [f"no `## {missing[0]}` section (taskRecord.sections: {', '.join(wanted)})"]
    order = [h for h in found if h in [w.lower() for w in wanted]]
    if order != [w.lower() for w in wanted]:
        return [f"the sections are not in the order {', '.join(wanted)}, or one is repeated"]
    bodies = {h.lower(): body for h, body in sections_of(text)}
    for name in (wanted[0], ACCEPTANCE):  # the goal and the acceptance criteria are the contract: they cannot be the template
        if name in wanted and PLACEHOLDER.fullmatch(bodies.get(name.lower(), "")):
            return [f"the `## {name}` section is empty or still the template; write it (the other sections may stay \u2014)"]
    return []


def entry_errors(text, task_id, config):
    """Why `text` is not a decision log entry for `task_id` (form only); [] if it is."""
    tr = gwconfig.task_record(config)
    first = next((l for l in text.splitlines() if l.strip()), "")
    parts = first[2:].split(SEP) if first.startswith("# ") else []
    if len(parts) != 4 or not DATE.fullmatch(parts[0].strip()) or not parts[1].strip():
        return [f"the first line is not `# <date>{SEP}<skill or session>{SEP}<commit>{SEP}<id>`: {first!r}"]
    commit = parts[2].strip()
    if commit != tr["pendingMarker"] and not re.fullmatch(r"[0-9a-f]{7,64}", commit):
        return [f"the commit field is {commit!r}, not `{tr['pendingMarker']}` or a sha"]
    if parts[3].strip() != task_id:
        return [f"the header names the id {parts[3].strip()!r}, not {task_id!r}"]
    found = {h.lower(): body for h, body in sections_of(text)}
    for name in tr["logSections"]:
        if not found.get(name.lower()):
            return [f"no non-empty `## {name}` section (taskRecord.logSections: {', '.join(tr['logSections'])}; "
                    f"write — when there is nothing to say)"]
    first_name = tr["logSections"][0]
    if PLACEHOLDER.fullmatch(found[first_name.lower()]):
        return [f"the `## {first_name}` section is only \u2014 or still the template; say why (the others may stay \u2014)"]
    return []


def _config(root):
    try:
        config = gwconfig.load(root)
    except gwconfig.ConfigError as exc:
        raise Refused(f"cannot read .claude/gw.json ({exc}); fix it: python3 {HERE / 'config.py'} validate")
    return config, Path(config["_root"]), gwconfig.task_record(config)


def check_id(config, task_id):
    import handoff
    pattern = handoff.task_id_pattern(config)
    if not re.fullmatch(pattern, task_id or ""):
        raise Refused(f"{task_id!r} does not have the shape of taskId ({pattern}); use the id of a roadmap row, e.g. C11")


def write_new(root, rel, text):
    path = root / rel
    if path.exists():
        raise Refused(f"{rel} exists already; edit it, or for a new decision log entry: python3 {HERE / 'task.py'} log <id> --agent <skill|session>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(rel)


BRANCH_PREFIX = "agent/"
MARK = "gw/current-task"


GIT_TIMEOUT = 10.0  # seconds a git call may take (like config-guard.py's GIT_TIMEOUT); questions-guard.py runs these on every edit


class GitStuck(Exception):
    """A git call took more than GIT_TIMEOUT: the caller cannot tell the current task (questions-guard.py fails closed)."""


def _git(root, *argv):
    """stdout of `git -C root ...` without the GIT_* variables a git hook exports, or None when it fails; raises GitStuck
    when git hangs (an index.lock, a network file system)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        r = subprocess.run(["git", "-C", str(root), *argv], capture_output=True, text=True, env=env,
                           stdin=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise GitStuck(f"`git {argv[0]}` took more than {GIT_TIMEOUT:.0f}s")
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def current_mark(root):
    """The file of the current-task mark in the git dir of the worktree at `root`, or None outside git."""
    out = _git(root, "rev-parse", "--git-path", MARK)
    return (Path(root) / out).resolve() if out else None


def branch_task(root, config):
    """The id in a branch named `agent/<id>-<topic>` (or `agent/<id>`), checked against taskId; else None."""
    import handoff
    branch = _git(root, "symbolic-ref", "--short", "-q", "HEAD") or ""
    m = re.match(rf"{re.escape(BRANCH_PREFIX)}({handoff.task_id_pattern(config)})(?=-|$)", branch)
    return m.group(1) if m else None


def mark_task(root, config):
    """The id in the mark, or None when there is no mark or it does not hold a valid id."""
    import handoff
    mark = current_mark(root)
    try:
        text = mark.read_text(encoding="utf-8").strip() if mark else ""
    except (OSError, UnicodeDecodeError):
        return None
    return text if text and re.fullmatch(handoff.task_id_pattern(config), text) else None


def current_task(root, config):
    """(id, source): the current task and where it came from ("branch" or "mark"); (None, None) when there is none.
    The branch beats the mark."""
    found = branch_task(root, config)
    if found:
        return found, "branch"
    found = mark_task(root, config)
    return (found, "mark") if found else (None, None)


def write_mark(root, task_id):
    mark = current_mark(root)
    if mark is None:
        raise Refused(f"{root} is not a git repository, so there is no git dir for the current-task mark; run it inside the "
                      f"project: python3 {HERE / 'task.py'} current {task_id}")
    mark.parent.mkdir(parents=True, exist_ok=True)
    mark.write_text(task_id + "\n", encoding="utf-8")


def clear_mark(root, task_id=None):
    """Remove the current-task mark (only when it names `task_id`, if given); handoff.py close-row <id> calls it."""
    mark = current_mark(root)
    if mark is None or not mark.exists():
        return
    try:
        if task_id is None or mark.read_text(encoding="utf-8").strip() == task_id:
            mark.unlink()
    except (OSError, UnicodeDecodeError):
        pass


FILES = "Files"
RELATED = re.compile(r"^Related:\s*(.*)$", re.M)
DEVIATIONS = "gw/deviations.jsonl"
GLOB = re.compile(r"[*?\[]")


def files_of(text):
    """The paths the `## Files` section of a contract names in backticks (C13), as repo-relative posix patterns: a
    trailing `/`, `…` or `...` is a folder prefix, `*`, `?` and `[...]` are globs (fnmatch, `*` crosses folders).
    Tokens with spaces (commands), absolute paths and `..` are skipped. None when there is no `## Files` section."""
    body = next((b for h, b in sections_of(text) if h.lower() == FILES.lower()), None)
    if body is None:
        return None
    out = []
    for token in re.findall(r"`([^`\n]+)`", body):
        token = token.strip().replace("\\", "/")
        if not token or re.search(r"\s", token) or token.startswith("/") or re.match(r"^[A-Za-z]:/", token):
            continue
        token = re.sub(r"/?(…|\.\.\.)$", "/", token)
        while token.startswith("./"):
            token = token[2:]
        if token and ".." not in token.split("/"):
            out.append(token)
    return out


def in_files(rel, patterns):
    """Whether the repo-relative posix path `rel` is named by one of `patterns` (files_of): equal, under a folder it
    names (with or without the trailing `/`), or matched by a glob."""
    import fnmatch
    for pattern in patterns:
        bare = pattern.rstrip("/")
        if rel == bare or (bare and rel.startswith(bare + "/")):
            return True
        if GLOB.search(pattern) and fnmatch.fnmatchcase(rel, pattern):
            return True
    return False


def related_of(text):
    """The ids of the `Related:` lines of a contract (a new requirement became another task, C13)."""
    return [i for line in RELATED.findall(text) for i in re.split(r"[,\s]+", line) if i]


def deviations_file(root):
    """`<git common dir>/gw/deviations.jsonl` of the repository at `root` (shared by its worktrees), or None."""
    out = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(out) / DEVIATIONS if out else None


def log_deviation(root, task_id, path, action, rule="scope"):
    """Append one JSON line {ts, task, path, rule, action} to the deviations log (the retro reads the repeats); a log
    that cannot be written is skipped (it is a record, not a guard)."""
    target = deviations_file(root)
    if target is None:
        return
    line = {"ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "task": task_id,
            "path": path, "rule": rule, "action": action}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_deviations(root, task_id=None):
    """The entries of the deviations log (only `task_id`'s when given); unreadable lines are skipped."""
    target = deviations_file(root)
    out = []
    try:
        lines = target.read_text(encoding="utf-8").splitlines() if target and target.is_file() else []
    except (OSError, UnicodeDecodeError):
        lines = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and (task_id is None or item.get("task") == task_id):
            out.append(item)
    return out


def add_related(root, rel, other):
    """Add `Related: <other>` under the title of the contract at `rel` (once)."""
    path = Path(root) / rel
    text = path.read_text(encoding="utf-8")
    if other in related_of(text):
        return
    head, sep, rest = text.partition("\n")
    path.write_text(f"{head}\n\nRelated: {other}{sep}{rest}" if sep else f"{text}\n\nRelated: {other}\n",
                    encoding="utf-8")


def resolve(root, rel):
    r = subprocess.run(["git", "-C", str(root), "log", "--diff-filter=A", "--format=%h", "-1", "--", rel],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip() if r.returncode == 0 else ""


def run(args):
    config, root, tr = _config(args.root)
    if args.command == "current":
        return run_current(args, config, root)
    if args.command == "deviations":
        for item in read_deviations(root, args.task):
            print(f"{item.get('ts', '?')}  {item.get('task', '?')}  {item.get('rule', '?')}  {item.get('action', '?')}  "
                  f"{item.get('path', '?')}")
        return
    check_id(config, args.id)
    base = tr["path"].strip("/")
    if args.command == "new":
        if args.related:
            check_id(config, args.related)
            if not (root / base / f"{args.related}.md").is_file():
                raise Refused(f"{base}/{args.related}.md does not exist, so it cannot link {args.id}; create it first: "
                              f"python3 {HERE / 'task.py'} new {args.related}")
        write_new(root, f"{base}/{args.id}.md", contract_text(config, args.id, args.title, root))
        if args.related:  # a new requirement is another task (C13): both records name each other
            add_related(root, f"{base}/{args.id}.md", args.related)
            add_related(root, f"{base}/{args.related}.md", args.id)
        held = mark_task(root, config)
        if held is None:  # never switches a task already marked: that is `current <id>`, which config-guard asks about
            write_mark(root, args.id)
        elif held != args.id:
            print(f"task: the current task stays {held} (its mark); to switch, the user runs: python3 {HERE / 'task.py'} "
                  f"current {args.id}", file=sys.stderr)
    elif args.command == "log":
        agent = args.agent.strip().lower()
        if not SLUG.fullmatch(agent) or names_a_model(agent, config):
            raise Refused(f"--agent {args.agent!r} must be a skill name or `session` (letters, digits, hyphens), never a model; "
                          f"e.g.: python3 {HERE / 'task.py'} log {args.id} --agent session")
        date = args.date or datetime.date.today().isoformat()
        if not DATE.fullmatch(date):
            raise Refused(f"--date {date!r} is not YYYY-MM-DD; fix it: python3 {HERE / 'task.py'} log {args.id} --agent {agent}")
        token = secrets.token_hex(4)[:7]
        write_new(root, f"{base}/{args.id}/{date}-{agent}-{token}.md", entry_text(config, args.id, agent, date))
    else:
        folder = root / base / args.id
        for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
            rel = path.relative_to(root).as_posix()
            print(f"{resolve(root, rel) or tr['pendingMarker']}  {rel}")


def run_current(args, config, root):
    if args.clear and args.id:
        raise Refused(f"give an id or --clear, not both: python3 {HERE / 'task.py'} current --clear")
    if args.clear:
        clear_mark(root)
        return
    if args.id:
        check_id(config, args.id)
        write_mark(root, args.id)
        branch = branch_task(root, config)
        if branch and branch != args.id:
            print(f"task: the branch names {branch}, which beats the mark; the current task stays {branch}",
                  file=sys.stderr)
        return
    found = current_task(root, config)[0]
    if found:
        print(found)


def names_a_model(agent, config):
    """Whether `agent` names a model or provider, by the rule of the Agent trailer (commit-message.py, with the
    project's agentModelNames and agentModelShapes)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("commit_message", HERE / "commit-message.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        return module.names_a_model(agent, module.model_rules(config))
    except module.Reject as exc:
        raise Refused(str(exc))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="project path (default: see config.py)")
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="create the contract <path>/<id>.md")
    new.add_argument("id")
    new.add_argument("--title")
    new.add_argument("--related", metavar="ID", help="the task whose new requirement this is: both records get a "
                     "`Related:` line (C13)")
    log = sub.add_parser("log", help="create a decision log entry in <path>/<id>/")
    log.add_argument("id")
    log.add_argument("--agent", required=True, help="the skill that works the task, or `session`")
    log.add_argument("--date", help="YYYY-MM-DD (default: today)")
    res = sub.add_parser("resolve", help="list the entries of <id> with the commit that added each")
    res.add_argument("id")
    dev = sub.add_parser("deviations", help="list the deviations log (<git common dir>/gw/deviations.jsonl, C13)")
    dev.add_argument("--task", help="only this task's entries")
    cur = sub.add_parser("current", help="print the current task, or set (<id>) or remove (--clear) the mark")
    cur.add_argument("id", nargs="?")
    cur.add_argument("--clear", action="store_true")
    args = parser.parse_args(argv)
    try:
        run(args)
    except GitStuck as exc:
        print(f"task: {exc}; check the repository (git status) and run it again", file=sys.stderr)
        return 1
    except Refused as exc:
        print(f"task: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
