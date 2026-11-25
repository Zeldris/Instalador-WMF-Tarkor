#!/usr/bin/env python3
# galivelop-workflow v0.9.0
"""The questions file (C1-C3, C10): the questions the agent has for the user, one entry each, kept in the file of
`questions.path` in .claude/gw.json (default docs/questions.md) so they are not asked again in every iteration.

  questions.py add [--refs ID] [--rec TEXT]... QUESTION...   append questions (ids Q-<n> follow the highest one);
                                                 --rec is given once per question, or never
  questions.py list [--all] [--refs ID]          the open questions in full (--all: every state)
  questions.py count [--refs ID]                 the number of open questions (nothing else is printed)
  questions.py answer "5. a, 6. ok"              write each answer under its number, with today's date
  questions.py accept-risk Q-5 | --refs ID       state accepted-risk (with the date) for one open question or for
                                                 all the open ones of a task
  questions.py notice                            what session-start.sh shows: the whole list when there are open
                                                 questions that were never shown, else only "N open questions (path)"

Format (stable; a script reads and rewrites it, so keep it): text before the first heading is free; each question is
a `## Q-<n>` heading followed by `- Field: value` lines, each on one line:

  ## Q-12
  - Refs: B4                     the task it comes from (ids separated by commas)
  - Status: open                 open | answered | accepted-risk
  - Asked: 2026-11-17
  - Question: ...
  - Recommendation: ...          optional
  - Answer: ...                  written by `answer`
  - Answered: 2026-11-17         the date of the answer (`Accepted:` for accepted-risk)

Lines the script does not know are kept as they are. Every command fails closed (exit 1, nothing written) on an
unknown number, a state that does not allow the change, or a file it cannot parse. Reusable by other scripts:
read_entries, open_entries, open_for_task, questions_file. The mark of what `notice` already showed lives in the git
dir (gw/questions-shown), so it is per clone and never committed.
"""
import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as gwconfig  # noqa: E402

STATES = ("open", "answered", "accepted-risk")
HEADER = ("# Questions\n\n"
          "Questions for the user, one entry each; `python3 .claude/gw/scripts/questions.py` reads and rewrites this\n"
          "file (format: header of scripts/questions.py). Answer by number: `questions.py answer \"5. a, 6. ok\"`.\n\n")
HEADING = re.compile(r"^## (Q-(\d+))\s*$")
FIELD = re.compile(r"^- ([A-Za-z]+): ?(.*)$")


class QuestionsError(Exception):
    pass


class Entry:
    """One question: its number and the raw lines under its heading (unknown lines survive a rewrite)."""

    def __init__(self, number, lines):
        self.number = number
        self.lines = lines

    @property
    def id(self):
        return f"Q-{self.number}"

    def get(self, field, default=""):
        for line in self.lines:
            m = FIELD.match(line)
            if m and m.group(1) == field:
                return m.group(2).strip()
        return default

    def set(self, field, value):
        new = f"- {field}: {value}"
        for i, line in enumerate(self.lines):
            m = FIELD.match(line)
            if m and m.group(1) == field:
                self.lines[i] = new
                return
        end = len(self.lines)
        while end > 0 and not self.lines[end - 1].strip():
            end -= 1
        self.lines.insert(end, new)

    @property
    def status(self):
        return self.get("Status")

    @property
    def refs(self):
        return [r.strip() for r in self.get("Refs").split(",") if r.strip()]

    def render(self):
        body = list(self.lines)
        while body and not body[-1].strip():
            body.pop()
        return "\n".join([f"## {self.id}"] + body) + "\n"


def questions_file(root=None):
    """(path, root): the questions file of the project at `root` (config `questions.path`) and the root itself;
    raises ConfigError."""
    root = gwconfig.find_root(root)
    cfg = gwconfig.load(root)
    return Path(root) / gwconfig.questions_path(cfg), Path(root)


def parse(text):
    """(header text, [Entry]); raises QuestionsError on a status that is not one of STATES or a repeated id."""
    header, entries, current = [], [], None
    for line in text.splitlines():
        m = HEADING.match(line)
        if m:
            current = Entry(int(m.group(2)), [])
            entries.append(current)
        elif current is not None:
            current.lines.append(line)
        else:
            header.append(line)
    seen = set()
    for e in entries:
        if e.number in seen:
            raise QuestionsError(f"{e.id} appears twice in the questions file; remove one of them by hand")
        seen.add(e.number)
        if e.status not in STATES:
            raise QuestionsError(f"{e.id} has Status '{e.status}', not one of {', '.join(STATES)}; fix it by hand "
                                 f"in the questions file")
    head = "\n".join(header).rstrip("\n")
    return (head + "\n\n" if head else ""), entries


def read_entries(path):
    """The entries of the questions file at `path` (a missing file has none). Raises QuestionsError when the file
    cannot be read or parsed (bad UTF-8, a Status that is not valid, a repeated id): a caller that guards something
    with it (the restrictive mode, C4) must fail closed, that is block, not treat the error as "no questions"."""
    return load_all(path)[1]


def open_entries(path):
    return [e for e in read_entries(path) if e.status == "open"]


def open_for_task(path, task_id):
    """The open questions that name `task_id` in their Refs, compared exactly (what the restrictive mode, C4, asks
    for). A question without Refs belongs to no task, so it blocks none. Raises QuestionsError like read_entries."""
    return [e for e in open_entries(path) if task_id in e.refs]


def write(path, header, entries):
    """Atomic: a temporary file next to it, renamed over it; the temporary one is removed when anything fails."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (header or HEADER) + "\n".join(e.render() for e in entries)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise QuestionsError(f"cannot write {path} ({exc}); check its permissions and rerun the command")


class locked:
    """Context manager: an flock on <git dir>/gw/questions.lock, so two writers (subagents) do not overwrite each
    other; waits `handoff.lockWait` seconds (the config key of handoff.py's lock), then fails. Without fcntl or a
    file system that has no flock, it goes without."""

    def __init__(self, wait):
        self.wait, self.fd = wait, None

    def __enter__(self):
        try:
            import fcntl
            import errno
            import time
            mark = mark_file()
            if mark is None:
                return self
            lock = mark.with_name("questions.lock")
            lock.parent.mkdir(parents=True, exist_ok=True)
            self.fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o644)
            end = time.monotonic() + self.wait
            while True:
                try:
                    fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except OSError as exc:
                    if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):
                        return self
                    if time.monotonic() >= end:
                        os.close(self.fd)
                        self.fd = None
                        raise QuestionsError(f"another questions.py command holds the lock for {self.wait}s; wait "
                                             f"for it or raise handoff.lockWait in .claude/gw.json, and rerun")
                    time.sleep(0.1)
        except ImportError:
            return self
        except OSError:
            return self

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
        return False


def load_all(path):
    path = Path(path)
    if not path.is_file():
        return "", []
    try:
        return parse(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # ValueError: UnicodeDecodeError
        raise QuestionsError(f"cannot read {path} ({exc}); fix the file or its permissions and check it: "
                             f"questions.py count")


def one_line(text):
    return " ".join(str(text).split())


def today():
    return datetime.date.today().isoformat()


def show(e):
    lines = [f"{e.id}  [{e.status}]  Refs: {e.get('Refs') or '-'}", f"  {e.get('Question')}"]
    if e.get("Recommendation"):
        lines.append(f"  Rec.: {e.get('Recommendation')}")
    if e.get("Answer"):
        lines.append(f"  Answer ({e.get('Answered') or e.get('Accepted')}): {e.get('Answer')}")
    elif e.status == "accepted-risk":
        lines.append(f"  Risk accepted on {e.get('Accepted')}")
    return "\n".join(lines)


def parse_answers(text, known=None):
    """"5. a, 6. ok" -> [(5, "a"), (6, "ok")]. The first marker is a number (or Q-number) with . : or ) at the start;
    a later one starts after a newline or a semicolon (any form), or after a comma only as `<n>.` and only when <n>
    is in `known` (the open question numbers; None = any): so "5. pick 1, 2) or 3" is one answer, and a comma
    inside an answer followed by "<n>." of an open question can be told apart by using ; or a new line instead."""
    stripped = text.strip()
    marker = re.compile(r"(?:^|[;\n])\s*(?:Q-)?(\d+)\s*[.:)]\s*|(?:,)\s*(\d+)\s*\.\s+")
    found = []
    for m in marker.finditer(stripped):
        number = int(m.group(1) or m.group(2))
        if m.group(2) and known is not None and number not in known:
            continue
        found.append((m, number))
    if not found or found[0][0].start() != 0:
        raise QuestionsError(f"cannot read the answers '{text}'; write them as \"5. a, 6. ok\" (number, dot, answer)")
    out = []
    for i, (m, number) in enumerate(found):
        end = found[i + 1][0].start() if i + 1 < len(found) else len(stripped)
        answer = one_line(stripped[m.end():end]).rstrip(",;").strip()
        if not answer:
            raise QuestionsError(f"the answer to {number} is empty; write it after the dot: \"{number}. ok\"")
        out.append((number, answer))
    return out


def number_of(token):
    m = re.fullmatch(r"(?:Q-)?(\d+)", token.strip())
    if not m:
        raise QuestionsError(f"'{token}' is not a question id; use Q-<n> (list them: questions.py list)")
    return int(m.group(1))


def refs_of(text):
    """The Refs value of `add`: task ids separated by commas, on one line; anything else fails."""
    ids = [r for r in re.split(r"\s*,\s*", one_line(text or "")) if r]
    if not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", r) for r in ids):
        raise QuestionsError(f"--refs '{one_line(text)}' is not a list of task ids; write them like --refs B4 or "
                             f"--refs B4,B5")
    return ", ".join(ids)


def cmd_add(args, path):
    refs = refs_of(args.refs)
    header, entries = load_all(path)
    texts = [one_line(q) for q in args.questions]
    if not texts or not all(texts):
        raise QuestionsError("no question text; add one: questions.py add --refs <id> --rec <text> \"<question>\"")
    recs = [one_line(r) for r in (args.rec or [])]
    if recs and len(recs) != len(texts):
        raise QuestionsError(f"{len(recs)} --rec for {len(texts)} questions; give one --rec per question, or none")
    nxt = max([e.number for e in entries] + [0]) + 1
    for i, text in enumerate(texts):
        lines = [f"- Refs: {refs}".rstrip(), "- Status: open", f"- Asked: {today()}", f"- Question: {text}"]
        if recs:
            lines.append(f"- Recommendation: {recs[i]}")
        entries.append(Entry(nxt + i, lines))
        print(f"Q-{nxt + i}")
    write(path, header, entries)
    return 0


def cmd_list(args, path):
    entries = read_entries(path)
    if not args.all:
        entries = [e for e in entries if e.status == "open"]
    if args.refs:
        entries = [e for e in entries if args.refs in e.refs]
    if not entries:
        print("no open questions" if not args.all else "no questions")
        return 0
    print("\n\n".join(show(e) for e in entries))
    if not args.all and not args.refs:
        mark_shown(max(e.number for e in entries))
    return 0


def cmd_count(args, path):
    entries = open_entries(path)
    if args.refs:
        entries = [e for e in entries if args.refs in e.refs]
    print(len(entries))
    return 0


def cmd_answer(args, path):
    header, entries = load_all(path)
    by_number = {e.number: e for e in entries}
    pairs = parse_answers(" ".join(args.text), {e.number for e in entries if e.status == "open"})
    for number, _ in pairs:
        e = by_number.get(number)
        if e is None:
            raise QuestionsError(f"Q-{number} does not exist; list the open ones: questions.py list")
        if e.status != "open":
            raise QuestionsError(f"Q-{number} is already {e.status}; only an open question can be answered")
    if len({n for n, _ in pairs}) != len(pairs):
        raise QuestionsError("a number is answered twice; answer each question once")
    for number, answer in pairs:
        e = by_number[number]
        e.set("Status", "answered")
        e.set("Answer", answer)
        e.set("Answered", today())
        print(f"Q-{number} answered")
    write(path, header, entries)
    return 0


def cmd_accept_risk(args, path):
    header, entries = load_all(path)
    if bool(args.id) == bool(args.refs):
        raise QuestionsError("name one question or one task: questions.py accept-risk Q-5, or accept-risk --refs <id>")
    if args.id:
        number = number_of(args.id)
        chosen = [e for e in entries if e.number == number]
        if not chosen:
            raise QuestionsError(f"Q-{number} does not exist; list the open ones: questions.py list")
        if chosen[0].status != "open":
            raise QuestionsError(f"Q-{number} is already {chosen[0].status}; only an open question can be accepted")
    else:
        chosen = [e for e in entries if e.status == "open" and args.refs in e.refs]
        if not chosen:
            raise QuestionsError(f"task {args.refs} has no open questions; list them: questions.py list --refs "
                                 f"{args.refs}")
    for e in chosen:
        e.set("Status", "accepted-risk")
        e.set("Accepted", today())
        print(f"{e.id} accepted-risk")
    write(path, header, entries)
    return 0


ROOT = None  # the project root, set by main(); the git dir of the mark is looked up from it


def mark_file():
    r = subprocess.run(["git", "-C", str(ROOT or "."), "rev-parse", "--git-path", "gw/questions-shown"], capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")})
    return (Path(ROOT or ".") / r.stdout.strip()).resolve() if r.returncode == 0 and r.stdout.strip() else None


def read_mark(mark):
    try:
        return int(mark.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError, AttributeError):
        return 0


def mark_shown(number, mark=None):
    mark = mark or mark_file()
    if mark is None:
        return
    try:
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text(f"{number}\n", encoding="utf-8")
    except OSError:
        pass  # the worst case is showing the list once more


def cmd_notice(args, path, root):
    opened = open_entries(path)
    if not opened:
        return 0
    rel = os.path.relpath(path, root)
    mark = mark_file()
    top = max(e.number for e in opened)
    if top > read_mark(mark):
        print(f"{len(opened)} open questions ({rel}); answer by number: questions.py answer \"<n>. <answer>\"")
        print("\n\n".join(show(e) for e in opened))
        mark_shown(top, mark)
    else:
        print(f"{len(opened)} open questions ({rel})")
    return 0


def build_parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", help="the project's root (default: the one config.py finds)")
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("add")
    a.add_argument("--refs", default="")
    a.add_argument("--rec", action="append")
    a.add_argument("questions", nargs="+")
    ls = sub.add_parser("list")
    ls.add_argument("--all", action="store_true")
    ls.add_argument("--refs")
    c = sub.add_parser("count")
    c.add_argument("--refs")
    an = sub.add_parser("answer")
    an.add_argument("text", nargs="+")
    r = sub.add_parser("accept-risk")
    r.add_argument("id", nargs="?")
    r.add_argument("--refs")
    sub.add_parser("notice")
    return p


def main(argv=None):
    parser = build_parser()
    # `add --rec r1 "q1" --rec r2 "q2"` (each --rec next to its question, as grilling writes it): argparse leaves the
    # questions after the first --rec unparsed, so they are taken back in order; anything else unknown still fails.
    args, extra = parser.parse_known_args(argv)
    if extra:
        if args.command != "add" or any(x.startswith("-") for x in extra):
            parser.error(f"unrecognized arguments: {' '.join(extra)}")
        args.questions += extra
    global ROOT
    try:
        path, root = questions_file(args.root)
        ROOT = root
        if args.command == "notice":
            return cmd_notice(args, path, root)
        run = {"add": cmd_add, "list": cmd_list, "count": cmd_count, "answer": cmd_answer,
               "accept-risk": cmd_accept_risk}[args.command]
        if args.command in ("add", "answer", "accept-risk"):
            with locked(gwconfig.handoff(gwconfig.load(root))["lockWait"]):
                return run(args, path)
        return run(args, path)
    except (QuestionsError, gwconfig.ConfigError) as exc:
        print(f"questions: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
