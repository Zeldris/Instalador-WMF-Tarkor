#!/usr/bin/env python3
# galivelop-workflow v0.5.0
"""Hand-off log rules. The branch-row rules need `"logRows": true` in .claude/gw.json (a no-op otherwise); the
size and "Done" rules of `check`, and the `done` subcommand, work on any log.

The log (config `log`) has a state table with one row per branch, labelled "<anything> · `<branch>`" (for example
"| **Task in progress · `claude/topic`** | text |"). Two accounts writing in the same cell ended in two tasks and two
contradicting "Next" lines, so each branch writes only in its own row and the row stays short.

  handoff.py check [FILE] [--date YYYY-MM-DD] [--strict]
                                                 with logRows: rows well formed, one per branch, <= 600 characters;
                                                 with --date, the "Updated" row is not older than that day; a "Task
                                                 in progress" row with no `branch` fails even if the other rows are
                                                 fine. On any log: every value cell of the state table (first
                                                 "Estado actual" / "Current state" section) <= 800 characters, and
                                                 the "Hecho (5 últimas)" / "Done (last 5)" section has <= 5 items,
                                                 numbered 1..n, each on its own line ("N. "). These last rules only
                                                 print `WARNING: ...` and exit 0; with --strict they fail (exit 1)
  handoff.py done TEXT [FILE] [--date YYYY-MM-DD]
                                                 insert "1. <date> — TEXT" at the top of the Done section (date
                                                 default: today), renumber, drop items beyond 5 (a multi-line item
                                                 moves whole), leave the rest of the file byte for byte; exit 1 if
                                                 the section is missing
  handoff.py own-row COMMIT BRANCH [--shared]   fail if COMMIT changes another branch's row or a shared row of the
                                                 state table ("Updated" and "Tests" are free); --shared, or
                                                 BITACORA_COMPARTIDA=1 / GW_SHARED_LOG=1, allows it
  handoff.py own-row --staged                   the same between HEAD and the index, for the branch being committed on
                                                 (the pre-commit hook, so the failure comes before the commit, not at
                                                 the push); passes at once if the log is not staged or is new, on a
                                                 detached HEAD (WARNING) and while a merge, cherry-pick or rebase is closing
  handoff.py set-row TEXT [--branch BRANCH]     rewrite the text of BRANCH's row (default: the current branch) without
                                                 closing it; fails, and writes nothing, if the row is missing, TEXT is
                                                 empty or has a newline, or it passes 600 characters
  handoff.py closed BASE SHA                    every task closed in the plan between BASE and SHA ("- [x] **ID**"
                                                 or struck through) is also recorded in the "Done" section of SHA's
                                                 log: struck through there, or named on a line that starts with a date
  handoff.py closed --staged                    the same between HEAD and the index (the pre-commit hook); passes at
                                                 once if no plan file is staged, and while a merge, cherry-pick or
                                                 rebase is being closed (the pre-push checks those)
  handoff.py in-progress BASE SHA               WARNING only: a task marked 🚧 that the commits name, whose plan
                                                 entry did not change (it may still say "Next: X" with X done)
  handoff.py close-row BRANCH [--text TEXT]     rewrite BRANCH's row as "merged, branch finished" (last commit
                                                 before the PR, so main does not inherit a stale "Next")
  handoff.py clash REV OTHER... [--warn]        fail if REV and an OTHER both open a plan entry (an unindented
                                                 "- …ID" / "| ID", done or not) for an id their merge base does not
                                                 have, with different titles (two tasks that took the same id; the
                                                 same title on both sides is the same task, brought over); --warn
                                                 only prints WARNING and exits 0, and skips an OTHER with no common
                                                 history. The title is the text after the id up to ":", ".", "(",
                                                 "—", "✅" or "|", markup and case ignored
  handoff.py clash --merge M [--tip T]          fail if merge commit M kept both tasks of a clash between its two
                                                 parents and T (default M) still has both titles under that id
  handoff.py clash --merging                    the same for the merge being concluded (HEAD, MERGE_HEAD and the
                                                 index; the pre-commit hook); passes when no merge is in progress

Common options: --root PATH (default: from this script's folder, via config.py), --plan PATH (repeatable; a file or a
folder with the plan/roadmap; env GW_PLAN, ':'-separated; config `plan`), --id-regex REGEX (task ids; env GW_TASK_ID;
config `taskId`; default
`[A-Z]{2,5}-\\d+[a-z]?`). Without a plan, `closed` and `in-progress` have nothing to compare and pass.
Exit 0 ok, 1 rule broken (each message ends with the command that fixes it), 2 bad usage or config.
Python 3.8+, stdlib only.
"""
import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as gwconfig  # noqa: E402

LIMIT = 600
CELL_LIMIT = 800  # a value cell of the state table (any log, not only logRows)
DONE_ITEMS = 5  # items kept in the Done section
INDEX = ""  # a "rev" for show()/plan_files(): the staged version
FREE_ROWS = {"Actualizado", "Tests", "Updated"}  # shared rows every commit may touch
DEFAULT_ID = r"[A-Z]{2,5}-\d+[a-z]?"
ROW = re.compile(r"^\|\s*\*\*(?P<label>.+?) · `(?P<branch>[^`]+)`\*\*\s*\|(?P<text>.*)\|\s*$")
STATE_HEADING = re.compile(r"^##\s+(Estado actual|Current state|Status)\b.*$", re.M | re.I)
DONE_HEADING = re.compile(r"^##\s+(Hecho|Done)\b.*$", re.M | re.I)
# The task's compaction budget, as the gw-selector skill has the log carry it (read by recover.py --state):
# "Compaction budget: 2" (English) or "Presupuesto de compactaciones: 2" (Spanish), anywhere in the branch's row
# (logRows) or in the log's state section. Text after the number ("(superado: 6)") is free.
BUDGET = re.compile(r"(?:Compaction budget|Presupuesto de compactaciones)\s*:\s*(\d+)", re.I)
TASK_ROW = re.compile(r"^\|\s*\*\*(Tarea en curso|Task in progress)\b.*?\*\*\s*\|", re.I)
ITEM_START = re.compile(r"^(\d+)\.(?:\s|$)")
GLUED_ITEM = re.compile(r"(?<=[^\s\d])(?<!\d\.)\d{1,2}\. \d{4}-\d{2}-\d{2}")  # "…).3. 2026-10-25 — …", not "v1.2. 2026-10-25"
PLACEHOLDER = re.compile(r"^\d+\.\s+_\((?:fecha|date)\b")  # the template's example item
CELL_SPLIT = re.compile(r"(?<!\\)\|")
LIST_ITEM = re.compile(r"^\s*(?:[-*]|\d+\.)\s")
DATE_LINE = re.compile(r"^\s*(?:[-*]|\d+\.)?\s*(?:\*\*|`|\[)?\s*\d{4}-\d{2}-\d{2}\b")
RANGE = r"\s*(?:…|\.\.\.|–|—|\ba\b|\bto\b)\s*"
TITLE_END = re.compile(r"\s*(?::(?:\s|$)|\.(?:\s|$)|\(|—|✅|\|)")
CLOSED_TEXT = {"es": "Al fusionarse, rama terminada: no queda nada pendiente en ella.",
               "en": "Merged, branch finished: nothing is pending on it."}


class Usage(Exception):
    pass


def task_id_pattern(config, explicit=None):
    """The task id pattern: `explicit` (--id-regex), else $GW_TASK_ID, else the config's `taskId`, else DEFAULT_ID.
    Shared with commit-message.py so both read the ids the same way."""
    return explicit or os.environ.get("GW_TASK_ID") or config.get("taskId") or DEFAULT_ID


def entry_regex(id_src):
    """The regex that tells a line opens a task entry (a table row `| D1 |` or a list item `- D1 …`, with or without a
    checkbox, bold, backticks or strike-through): group `id` is the task id, `box` the checkbox, `strike` the `~~`.
    `id_src` is the id pattern as a non-capturing group. Shared with commit-message.py (valid `Refs:` ids)."""
    return re.compile(rf"[-|]\s*(?:\[(?P<box>[ xX])\]\s*)?(?P<strike>~~)?\s*(?:\*\*)?`?(?P<id>{id_src})")


class Ctx:
    def __init__(self, args):
        try:
            self.config = gwconfig.load(args.root)
        except gwconfig.ConfigError as exc:
            raise Usage(f"{exc}; fix it: python3 {HERE / 'config.py'} validate")
        self.root = self.config["_root"]
        self.log = self.config["log"]
        plans = args.plan or [p for p in os.environ.get("GW_PLAN", "").split(":") if p] or list(self.config.get("plan") or [])
        self.plans = plans
        pattern = task_id_pattern(self.config, args.id_regex)
        try:
            re.compile(pattern)
            pattern = gwconfig.non_capturing(pattern)  # `(INS|FLU)-\d+` must not make findall return groups
            self.id = re.compile(pattern)
        except re.error as exc:
            raise Usage(f"--id-regex / GW_TASK_ID is not a valid regex ({exc}); fix it and rerun")
        except gwconfig.ConfigError as exc:
            raise Usage(f"--id-regex / GW_TASK_ID: {exc}; fix it and rerun")
        self.id_src = f"(?:{pattern})"
        self.sep = rf"(?:{RANGE}|\s*(?:,|\by\b|\band\b)\s*)"
        self.closed_box = re.compile(rf"^\s*[-*]\s*\[[xX]\]\s*(?:\*\*)?`?(?P<id>{self.id_src})", re.M)
        self.entry = entry_regex(self.id_src)
        self._titles, self._blob_titles = {}, {}

    def git(self, *a):
        return subprocess.run(["git", "-C", str(self.root), *a], capture_output=True, text=True)

    def ids(self, text):
        return [m.group(0) for m in self.id.finditer(text)]

    def struck_ids(self, text):
        """Ids a struck-through text closes: those that open each `~~…~~` (ranges expanded). A strike followed by an
        arrow is a task moved elsewhere, not closed. Multi-line strikes count (re.S)."""
        found = set()
        for m in re.finditer(r"~~(.*?)~~(\s*→)?", text, re.S):
            if m.group(2):
                continue
            span = re.sub(r"[*`]", "", m.group(1))
            head = re.match(rf"\s*({self.id_src}(?:{self.sep}{self.id_src})*)", span)
            if not head:
                continue
            run = head.group(1)
            found |= set(self.ids(run))
            for a, b in re.findall(rf"({self.id_src}){RANGE}({self.id_src})", run):
                (pa, na), (pb, nb) = a.rsplit("-", 1), b.rsplit("-", 1)
                if pa == pb and na.isdigit() and nb.isdigit() and int(na) < int(nb):
                    found |= {f"{pa}-{n}" for n in range(int(na), int(nb) + 1)}
        return found

    def closed_ids(self, text):
        return self.struck_ids(text) | {m.group("id") for m in self.closed_box.finditer(text)}

    def plan_files(self, rev):
        """Plan/roadmap files at `rev` (a plan entry may be a folder); rev INDEX = the staged ones."""
        out = []
        for p in self.plans:
            r = self.git("ls-files", "--", p) if rev == INDEX else self.git("ls-tree", "-r", "--name-only", rev, "--", p)
            out += [f for f in r.stdout.splitlines() if f.endswith(".md")]
        return sorted(set(out))

    def show(self, rev, path):
        r = self.git("show", f"{rev}:{path}")  # INDEX ("") gives ":path", the staged version
        return r.stdout if r.returncode == 0 else ""

    def plan_blobs(self, rev):
        """{path: blob sha} of the plan files at `rev` (INDEX = the staged ones)."""
        out = {}
        for p in self.plans:
            r = self.git("ls-files", "-s", "--", p) if rev == INDEX else self.git("ls-tree", "-r", rev, "--", p)
            for line in r.stdout.splitlines():
                meta, _, path = line.partition("\t")  # "mode sha stage\tpath" / "mode type sha\tpath"
                if path.endswith(".md"):
                    out[path] = meta.split()[1 if rev == INDEX else 2]
        return out

    def titles(self, rev):
        """Task id -> set of titles of the plan entries that open it at `rev`: unindented lines that `entry` matches,
        done or not (cached by rev and by blob: several revs share most plan files)."""
        if rev not in self._titles:
            res = {}
            for blob in self.plan_blobs(rev).values():
                if blob not in self._blob_titles:
                    found = {}
                    for line in self.git("cat-file", "blob", blob).stdout.splitlines():
                        m = self.entry.match(line)
                        if m:
                            rest = re.sub(r"\[[ xX]\]|[*`~]", "", line[m.end("id"):]).lstrip(" ·:—–-|")
                            found.setdefault(m.group("id"), set()).add(" ".join(TITLE_END.split(rest, 1)[0].split()).casefold())
                    self._blob_titles[blob] = found
                for i, t in self._blob_titles[blob].items():
                    res.setdefault(i, set()).update(t)
            self._titles[rev] = res
        return self._titles[rev]

    def entries(self, text):
        """Open plan entries: id -> text from the line that opens it to the next unindented line. Struck and
        checked entries are not kept."""
        res, cur = {}, None
        for line in text.splitlines():
            if line[:1] in (" ", "\t") and cur:
                res[cur] += "\n" + line
                continue
            m = self.entry.match(line)
            cur = m.group("id") if m and not m.group("strike") and (m.group("box") or " ") == " " else None
            if cur:
                res[cur] = line
        return res


def compaction_budget(text):
    """The compaction budget a log text fixes for the task (int), or None when it has none."""
    text = text or ""
    st = STATE_HEADING.search(text)  # the state section only (the whole text without one, or a branch's row)
    m = BUDGET.search(text[st.end():].split("\n## ", 1)[0] if st else text)
    return int(m.group(1)) if m else None


def state_rows(text):
    """Rows `| **Key** | text |` of the state table (the section after the state heading; the whole file when it has
    none): key (branch rows keep "label · branch") -> list of texts."""
    m = STATE_HEADING.search(text)
    section = text[m.end():].split("\n## ", 1)[0] if m else text
    rows = {}
    for line in section.splitlines():
        r = re.match(r"\|\s*\*\*(.+?)\*\*\s*\|(.*)\|\s*$", line)
        if r:
            rows.setdefault(r.group(1).replace("`", "").strip(), []).append(r.group(2).strip())
    return rows


def foreign_rows(before, after, branch):
    b, a = state_rows(before), state_rows(after)
    return [k for k in sorted(a.keys() | b.keys())
            if a.get(k) != b.get(k) and not k.endswith(f" · {branch}") and k not in FREE_ROWS]


def log_at(ctx, rev):
    return ctx.show(rev, ctx.log)


def section_lines(text, heading):
    """Lines under the first `heading` match, up to the next `## ` heading (None if the heading is missing)."""
    m = heading.search(text)
    return text[m.end():].split("\n## ", 1)[0].split("\n")[1:] if m else None


def long_cells(text):
    """(label, size) of each value cell of the state table with more than CELL_LIMIT characters."""
    found = []
    for line in section_lines(text, STATE_HEADING) or []:
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in CELL_SPLIT.split(line.strip())[1:-1]]
        if len(cells) < 2 or all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue
        label = cells[0].replace("*", "").replace("`", "").strip()
        found += [(label, len(c)) for c in cells[1:] if len(c) > CELL_LIMIT]
    return found


def done_problems(text, add, recheck):
    """Messages about the Done section: items not on their own line, numbering not 1..n, more than DONE_ITEMS.
    `add` is the command that adds an entry (and renumbers), `recheck` the one that checks the log again."""
    lines = section_lines(text, DONE_HEADING)
    if lines is None:
        return []
    out, numbers = [], []
    for line in lines:
        m = ITEM_START.match(line)
        if m:
            numbers.append(int(m.group(1)))
        glued = GLUED_ITEM.search(line)
        if glued:
            out.append(f"an item is glued to the end of another one (\"…{line[max(glued.start() - 15, 0):glued.end() + 10]}…\"); "
                       f"put each item on its own line, as \"N. \", then rerun: {recheck}")
    if numbers and numbers != list(range(1, len(numbers) + 1)):
        out.append("the Done items are numbered " + ", ".join(map(str, numbers)) + "; number them 1..n in order "
                   f"(the next entry renumbers them: {add})")
    if len(numbers) > DONE_ITEMS:
        out.append(f"the Done section has {len(numbers)} items (limit {DONE_ITEMS}); delete the oldest ones, the history "
                   f"is in git (the next entry drops them: {add})")
    return out


def cmd_check(ctx, args):
    path = Path(args.file) if args.file else ctx.root / ctx.log
    me = f"python3 {HERE / 'handoff.py'}"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        message = f"cannot read {path} ({exc}); create the log or fix `log` in .claude/gw.json, and save it as UTF-8"
        if ctx.config.get("logRows") or args.strict:
            raise Usage(message)
        print(f"WARNING: handoff: {message}")  # the module is off: an unreadable log must not block the commit
        return 0
    soft = [f"a cell of the state table (\"{label}\") has {size} characters (limit {CELL_LIMIT}); shorten it and move what "
            f"is done to the Done section: {me} done \"<text>\"" for label, size in long_cells(text)]
    soft += done_problems(text, f"{me} done \"<text>\"", f"{me} check {path} --strict")
    problems = rows_problems(ctx, args, text.splitlines()) if ctx.config.get("logRows") else []
    if args.strict:
        problems += soft
    else:
        for w in soft:
            print(f"WARNING: handoff: {w}")
    if args.at == "push":  # the commit already exists: the fix is a new commit
        return report(problems, f"edit {ctx.log} and make a new commit with the fix: git add {ctx.log} && git commit")
    return report(problems, f"edit {ctx.log}, stage it (git add {ctx.log}) and run the commit again: git commit")


def rows_problems(ctx, args, lines):
    problems = []
    if args.date:
        found = next((m.group(1) for m in (re.match(r"\|\s*\*\*(?:Actualizado|Updated)\*\*\s*\|\s*[`*]*(\d{4}-\d{2}-\d{2})", l)
                                           for l in lines) if m), None)
        if not found:
            problems.append("the \"Updated\" row is missing; add \"| **Updated** | YYYY-MM-DD |\" with today's date")
        elif found < args.date:
            problems.append(f"\"Updated\" says {found} and the commit is from {args.date}; set today's date in that row")
    rows = [l for l in lines if re.match(r"^\|\s*\*\*.* · `", l)]
    branches = []
    if not rows:
        problems.append("there is no row \"| **<label> · `<branch>`** | … |\"; add one for this branch")
    for line in lines:  # a "task in progress" row with no branch, whatever the other rows are
        if TASK_ROW.match(line) and not ROW.match(line) and line not in rows:
            problems.append(f"task row without a branch, it must be \"| **{TASK_ROW.match(line).group(1)} · `<branch>`** "
                            f"| … |\": {line[:80]}")
    for line in rows:
        m = ROW.match(line)
        if not m:
            problems.append(f"malformed branch row, it must be \"| **<label> · `<branch>`** | … |\": {line[:80]}")
            continue
        branches.append(m.group("branch"))
        size = len(m.group("text").strip())
        if size > LIMIT:
            problems.append(f"row of {m.group('branch')} has {size} characters (limit {LIMIT}); "
                            "move what is done to the Done section and shorten the row")
    for b in sorted({b for b in branches if branches.count(b) > 1}):
        problems.append(f"two rows for {b}; keep one per branch")
    return problems


def report(problems, fix):
    for p in problems:
        print(f"handoff: {p}")
    if problems:
        print(f"handoff: fix: {fix}")
    return 1 if problems else 0


def current_branch(ctx):
    """The checked-out branch, or "" on a detached HEAD."""
    return ctx.git("symbolic-ref", "--short", "-q", "HEAD").stdout.strip()


def cmd_own_row(ctx, args):
    if args.shared or os.environ.get("BITACORA_COMPARTIDA") or os.environ.get("GW_SHARED_LOG"):
        return 0
    if args.staged:
        staged = ctx.git("diff", "--cached", "--name-only", "--", ctx.log)
        if staged.returncode != 0:
            print(f"handoff: cannot read the staged changes ({staged.stderr.strip() or 'git diff failed'}); fix the repo and "
                  "commit again: git status")
            return 1
        if not staged.stdout.strip() or closing_other_side(ctx) or squash_in_progress(ctx):
            return 0
        branch = current_branch(ctx)
        if not branch:
            print("handoff: WARNING: detached HEAD, so there is no own row to check at commit time; the pre-push checks it "
                  "(check out a branch: git switch <branch>)", file=sys.stderr)
            return 0
        if ctx.git("cat-file", "-e", f"HEAD:{ctx.log}").returncode != 0:
            return 0  # the log is being created (a fresh project, or a repo's first commit): every row is new
        head = ctx.git("show", f"HEAD:{ctx.log}")
        if head.returncode != 0:
            print(f"handoff: cannot read {ctx.log} at HEAD ({head.stderr.strip() or 'git show failed'}); fix the repo and "
                  "commit again: git status")
            return 1
        before, after = head.stdout, log_at(ctx, INDEX)
        fix = (f"unstage the log (git restore --staged {ctx.log}) or undo that edit; if it is on purpose, commit AND push "
               "with the variable: GW_SHARED_LOG=1 git commit, then GW_SHARED_LOG=1 git push (the pre-push checks the "
               "commit again)")
    else:
        branch = args.branch
        parent = ctx.git("rev-parse", "--verify", "-q", f"{args.commit}^").stdout.strip()
        before, after = (log_at(ctx, parent) if parent else ""), log_at(ctx, args.commit)
        fix = "If it is on purpose (closing a PR, a shared row), push with: BITACORA_COMPARTIDA=1 git push"
    bad = foreign_rows(before, after, branch)
    for key in bad:
        print(f"handoff: the commit changes the row \"{key}\", which is not {branch}'s; each branch writes only in its own "
              f"row. {fix}")
    return 1 if bad else 0


def squash_in_progress(ctx):
    """True after `git merge --squash`, which leaves SQUASH_MSG instead of MERGE_HEAD: the rows come from the other side."""
    path = Path(ctx.git("rev-parse", "--git-path", "SQUASH_MSG").stdout.strip())
    return (path if path.is_absolute() else ctx.root / path).exists()


def closing_other_side(ctx):
    """True while a merge, cherry-pick or rebase is being closed: its closures come from the other side."""
    for head in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REBASE_HEAD"):
        path = Path(ctx.git("rev-parse", "--git-path", head).stdout.strip())
        if (path if path.is_absolute() else ctx.root / path).exists():
            return True
    return False


def cmd_closed(ctx, args):
    if not ctx.plans:
        return 0
    if args.staged:
        if not ctx.git("diff", "--cached", "--name-only", "--", *ctx.plans).stdout.strip() or closing_other_side(ctx):
            return 0
        args.base, args.sha = "HEAD", INDEX
    files = ctx.plan_files(args.sha) + ctx.plan_files(args.base)
    before, after = [], []
    for f in sorted(set(files)):
        before.append(ctx.show(args.base, f))
        after.append(ctx.show(args.sha, f))
    new = ctx.closed_ids("\n".join(after)) - ctx.closed_ids("\n".join(before))
    protected = ctx.config["protectedBranch"]
    for f in sorted(set(files)):  # already closed on the protected branch: it comes with a merge of it, not this branch's
        on_main = ctx.git("show", f"refs/remotes/origin/{protected}:{f}")
        if on_main.returncode == 0:
            new -= ctx.closed_ids(on_main.stdout)
    if not new:
        return 0
    text = log_at(ctx, args.sha)
    m = DONE_HEADING.search(text)
    done = text[m.end():].split("\n## ", 1)[0] if m else ""
    # recorded = struck through in "Done", or named in an entry that starts with a date, its indented continuation
    # lines included (an id that is merely mentioned, or listed unstruck, does not count)
    listed = ctx.struck_ids(done)
    dated = False
    for line in done.splitlines():
        if DATE_LINE.match(line):
            dated = True
        elif not (dated and line[:1].isspace() and line.strip() and not LIST_ITEM.match(line)):
            dated = False
        if dated:
            listed |= set(ctx.ids(line))
    missing = sorted(new - listed)
    for t in missing:
        print(f"handoff: {t} is closed in the plan; list it in the \"Done\" section of {ctx.log}")
    if missing and args.staged:
        print(f"handoff: fix: edit {ctx.log}, stage it (git add {ctx.log}) and commit again")
    elif missing:
        print(f"handoff: fix: edit {ctx.log} and make a new commit with the fix: git add {ctx.log} && git commit")
    return 1 if missing else 0


def commit_of(ctx, rev):
    sha = ctx.git("rev-parse", "-q", "--verify", f"{rev}^{{commit}}").stdout.strip()
    if not sha:
        raise Usage(f"{rev} is not a commit in this clone; fetch it: git fetch origin")
    return sha


def clashes(ctx, a, b):
    """{id: (titles at a, titles at b)} of the ids both open and their merge base does not, with different titles.
    None if a and b have no common history (a shallow clone, unrelated branches)."""
    base = ctx.git("merge-base", a, b).stdout.strip()
    if not base:
        return None
    ta, tb, t0 = ctx.titles(a), ctx.titles(b), ctx.titles(base)
    return {i: (ta[i], tb[i]) for i in sorted(ta.keys() & tb.keys()) if i not in t0 and ta[i] != tb[i]}


def free_id(ctx, revs, taken):
    """The next id after the highest one with `taken`'s prefix that any of `revs` opens."""
    prefix = taken.rsplit("-", 1)[0]
    top = 0
    for rev in revs:
        for i in ctx.titles(rev):
            head, _, num = i.rpartition("-")
            m = re.match(r"\d+", num)
            if head == prefix and m:
                top = max(top, int(m.group(0)))
    return f"{prefix}-{top + 1}"


def quote(titles):
    return " / ".join(f"\"{t}\"" for t in sorted(titles))


def cmd_clash(ctx, args):
    if not ctx.plans:
        return 0
    if args.merging or args.merge:
        if args.merging:
            path = Path(ctx.git("rev-parse", "--git-path", "MERGE_HEAD").stdout.strip())
            path = path if path.is_absolute() else ctx.root / path
            if not path.exists():
                return 0
            p1, p2, tip = "HEAD", path.read_text().split()[0], INDEX
            fix = "renumber this branch's task in the plan (and wherever it is named), then: git add -A && git commit"
        else:
            m = commit_of(ctx, args.merge)
            parents = ctx.git("rev-parse", f"{m}^1", f"{m}^2").stdout.split()
            if len(parents) != 2:
                return 0  # not a merge
            p1, p2 = parents
            tip = commit_of(ctx, args.tip) if args.tip else m
            fix = "renumber this branch's task in the plan (and wherever it is named) in a new commit: git commit -a"
        found = clashes(ctx, p1, p2) or {}
        bad = [i for i, (t1, t2) in found.items() if (t1 | t2) <= ctx.titles(tip).get(i, set())]
        for i in bad:
            t1, t2 = found[i]
            print(f"handoff: the merge keeps two different tasks with the id {i}: {quote(t1)} on this branch and "
                  f"{quote(t2)} on the merged one; give this branch's a free id ({free_id(ctx, [p1, p2], i)})")
        if bad:
            print(f"handoff: fix: {fix}")
        return 1 if bad else 0
    rev, bad = commit_of(ctx, args.revs[0]), []
    for other in args.revs[1:]:
        if args.warn and not ctx.git("rev-parse", "-q", "--verify", f"{other}^{{commit}}").stdout.strip():
            continue
        found = clashes(ctx, rev, commit_of(ctx, other))
        if found is None:
            if args.warn:
                continue
            raise Usage(f"{args.revs[0]} and {other} have no common history here; fetch more of it: git fetch --deepen=200 origin")
        for i, (ta, tb) in found.items():
            bad.append(i)
            print(f"{'WARNING: ' if args.warn else ''}handoff: {i} is a new task on this branch ({quote(ta)}) and on "
                  f"{other} ({quote(tb)}); give yours a free id ({free_id(ctx, [rev, other], i)}) or, if it is the "
                  "same task, the same title on both")
    if bad and not args.warn:
        print("handoff: fix: renumber the task in the plan (and wherever it is named), then: git commit -a")
    return 1 if bad and not args.warn else 0


def cmd_in_progress(ctx, args):
    if not ctx.plans:
        return 0
    log = ctx.git("log", "--no-merges", "--format=%B", f"{args.base}..{args.sha}").stdout
    named = set(ctx.ids(log))
    if not named:
        return 0
    before, after = {}, {}
    for f in ctx.plan_files(args.sha):
        for rev, dest in ((args.base, before), (args.sha, after)):
            for i, t in ctx.entries(ctx.show(rev, f)).items():
                dest.setdefault(i, set()).add(t)
    for t in sorted(i for i in named if any("🚧" in e for e in after.get(i, ())) and after[i] == before.get(i)):
        print(f"warning: the commits name {t}, in progress (🚧), and its plan entry did not change; if it moved on or "
              f"something else is pending, write it there (edit the entry of {t} and commit)")
    return 0


def split_blank(block):
    """(content, trailing blank lines) of a list of lines."""
    n = len(block)
    while n and not block[n - 1].strip():
        n -= 1
    return block[:n], block[n:]


def cmd_done(ctx, args):
    path = Path(args.file) if args.file else ctx.root / ctx.log
    text = " ".join(args.text.split())
    if not text:
        raise Usage("TEXT is empty; give the entry: handoff.py done \"what was closed\"")
    try:
        raw = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Usage(f"cannot read {path} ({exc}); create the log or fix `log` in .claude/gw.json")
    lines = re.findall(r"[^\n]*\n|[^\n]+", raw)  # keeps each line ending: the rest of the file stays byte for byte
    head = next((i for i, l in enumerate(lines) if DONE_HEADING.match(l.rstrip("\r\n"))), None)
    if head is None:
        print(f"handoff: {path} has no \"## Hecho\" / \"## Done\" section; add the line \"## Done (last {DONE_ITEMS})\" "
              f"to it and rerun: python3 {HERE / 'handoff.py'} done \"{text}\" {path}")
        return 1
    eol = "\r\n" if lines[head].endswith("\r\n") else "\n"
    if not lines[head].endswith("\n"):
        lines[head] += eol
    end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    pre, items, post = [], [], []  # lines before the first item; each item = its first line + continuation lines;
    for line in lines[head + 1:end]:  # post = from an unindented paragraph after a blank line on, kept as it is
        bare = line.rstrip("\r\n")
        if post:
            post.append(line)
        elif ITEM_START.match(bare):
            items.append([line])
        elif items and bare.strip() and not bare[0].isspace() and not items[-1][-1].strip():
            post.append(line)
        elif items:
            items[-1].append(line)
        else:
            pre.append(line)
    entry = f"1. {args.date} — {text}{eol}"
    parts = [split_blank(i) for i in items]
    closing = parts[-1][1] if parts else []  # blank lines that close the section
    parts = [p for p in parts if not PLACEHOLDER.match(p[0][0])]  # the template's example item goes away
    if parts:
        gap = parts[0][1] if len(parts) > 1 else []  # blank lines the log keeps between items
        tail = closing
        kept = [[entry]] + [p[0] for p in parts[:DONE_ITEMS - 1]]
        body = list(pre)
        for n, block in enumerate(kept):
            if n:
                body += gap
            body += [re.sub(r"^\d+\.", f"{n + 1}.", block[0], count=1)] + block[1:]
        body += tail
        dropped = max(len(parts) + 1 - DONE_ITEMS, 0)
    else:
        content, tail = split_blank(pre)
        tail = closing or tail
        if content and not content[-1].endswith("\n"):
            content[-1] += eol
        body = content + [eol, entry] + (tail or ([eol] if end < len(lines) else []))
        dropped = 0
    lines[head + 1:end] = body + post
    path.write_bytes("".join(lines).encode("utf-8"))
    print(f"handoff: entry added to the Done section of {path}" + (f" ({dropped} oldest dropped)" if dropped else "")
          + "; commit it with the rest of the work")
    return 0


def rewrite_row(ctx, branch, text):
    """Replace the text of `branch`'s row in the log file. Returns the number of rows found; writes only if exactly 1."""
    path = ctx.root / ctx.log
    try:
        with open(path, encoding="utf-8", newline="") as f:  # Path.read_text(newline=) is Python 3.13+
            raw = f.read()
    except OSError as exc:
        raise Usage(f"cannot read {path} ({exc}); fix `log` in .claude/gw.json")
    eol = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.split(eol)
    hit = 0
    for i, line in enumerate(lines):
        m = ROW.match(line)
        if m and m.group("branch") == branch:
            lines[i] = f"| **{m.group('label')} · `{branch}`** | {text} |"
            hit += 1
    if hit == 1:
        with open(path, "w", encoding="utf-8", newline="") as f:  # Path.write_text(newline=) is Python 3.10+
            f.write(eol.join(lines))
    return hit


def cmd_close_row(ctx, args):
    text = args.text or CLOSED_TEXT.get(ctx.config["language"], CLOSED_TEXT["en"])
    hit = rewrite_row(ctx, args.branch, text)
    if hit != 1:
        print(f"handoff: found {hit} rows for {args.branch}, expected 1; add the row first: edit {ctx.log}")
        return 1
    print(f"handoff: row of {args.branch} closed in {ctx.log}; commit it: git commit -am 'Close the log row of {args.branch}'")
    return 0


def cmd_set_row(ctx, args):
    branch = args.branch or current_branch(ctx)
    if not branch:
        raise Usage("detached HEAD, so there is no branch whose row to write; name it: handoff.py set-row TEXT --branch <branch>")
    text = args.text.strip()
    if not text or "\n" in text or "\r" in text:
        raise Usage("TEXT must be one non-empty line (a table cell); write the row text on a single line")
    text = re.sub(r"(?<!\\)\|", r"\\|", text)
    if len(text) > LIMIT:
        print(f"handoff: the text has {len(text)} characters (limit {LIMIT}); shorten it, or move what is done to the Done "
              f"section: python3 {HERE / 'handoff.py'} done \"<text>\"")
        return 1
    hit = rewrite_row(ctx, branch, text)
    if hit != 1:
        print(f"handoff: found {hit} rows for {branch}, expected 1; add the row first: edit {ctx.log}")
        return 1
    print(f"handoff: row of {branch} updated in {ctx.log} ({len(text)} characters); commit it together with the work")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root")
    p.add_argument("--plan", action="append")
    p.add_argument("--id-regex")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("file", nargs="?")
    c.add_argument("--date")
    c.add_argument("--strict", action="store_true")
    c.add_argument("--at", choices=("commit", "push"), default="commit",
                   help="where it runs: at commit time (the commit does not exist yet) or at push time (it does)")
    d = sub.add_parser("done")
    d.add_argument("text")
    d.add_argument("file", nargs="?")
    d.add_argument("--date")
    o = sub.add_parser("own-row")
    o.add_argument("commit", nargs="?")
    o.add_argument("branch", nargs="?")
    o.add_argument("--shared", action="store_true")
    o.add_argument("--staged", action="store_true")
    s = sub.add_parser("closed")
    s.add_argument("base", nargs="?")
    s.add_argument("sha", nargs="?")
    s.add_argument("--staged", action="store_true")
    s = sub.add_parser("in-progress")
    s.add_argument("base")
    s.add_argument("sha")
    k = sub.add_parser("clash")
    k.add_argument("revs", nargs="*")
    k.add_argument("--warn", action="store_true")
    k.add_argument("--merge")
    k.add_argument("--tip")
    k.add_argument("--merging", action="store_true")
    r = sub.add_parser("close-row")
    r.add_argument("branch")
    r.add_argument("--text")
    w = sub.add_parser("set-row")
    w.add_argument("text")
    w.add_argument("--branch")
    args = p.parse_args(argv)
    if args.cmd == "own-row" and (args.staged == (args.commit is not None) or (args.commit is None) != (args.branch is None)):
        print("handoff: own-row takes COMMIT BRANCH, or --staged alone; run: handoff.py own-row --staged", file=sys.stderr)
        return 2
    if args.cmd == "closed" and (bool(args.staged) == (args.sha is not None) or (args.base is None) != (args.sha is None)):
        print("handoff: closed takes BASE SHA, or --staged alone; run: handoff.py closed --staged", file=sys.stderr)
        return 2
    if args.cmd == "clash" and not ((args.merging and not (args.revs or args.merge or args.tip or args.warn))
                                    or (args.merge and not (args.revs or args.warn or args.merging))
                                    or (len(args.revs) >= 2 and not (args.merge or args.tip or args.merging))):
        print("handoff: clash takes REV OTHER... [--warn], --merge M [--tip T], or --merging alone; run: "
              "handoff.py clash HEAD origin/main", file=sys.stderr)
        return 2
    if getattr(args, "date", None):
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
                raise ValueError(args.date)
            datetime.date.fromisoformat(args.date)
        except ValueError:
            print(f"handoff: --date must be YYYY-MM-DD and a real date, not \"{args.date}\"; fix it and rerun", file=sys.stderr)
            return 2
    try:
        try:
            ctx = Ctx(args)
        except Usage as exc:
            if not ((args.cmd in ("closed", "own-row") and args.staged) or (args.cmd == "clash" and args.merging)):
                raise
            # A commit may be the one that fixes (or breaks) the config: the pre-push fails closed on it instead.
            what = {"closed": "\"Done\"", "own-row": "own-row"}.get(args.cmd, "task-id clash")
            print(f"handoff: WARNING: skipping the {what} check of this commit: {exc}", file=sys.stderr)
            return 0
        if args.cmd == "done":
            args.date = args.date or datetime.date.today().isoformat()
        elif not ctx.config.get("logRows") and args.cmd != "check":
            if args.cmd == "set-row":
                print("handoff: logRows is off in .claude/gw.json, so there are no branch rows and nothing was written; "
                      "enable it: set \"logRows\": true in .claude/gw.json, then rerun set-row")
                return 1
            return 0  # the branch-row module is off: nothing to check (`check` still reads the size and Done rules)
        return {"check": cmd_check, "done": cmd_done, "own-row": cmd_own_row, "closed": cmd_closed,
                "in-progress": cmd_in_progress, "close-row": cmd_close_row, "set-row": cmd_set_row, "clash": cmd_clash}[args.cmd](ctx, args)
    except Usage as exc:
        print(f"handoff: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
