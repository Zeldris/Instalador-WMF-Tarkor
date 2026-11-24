#!/usr/bin/env python3
# galivelop-workflow v0.9.0
"""Hand-off log rules. The branch-row rules need `"logRows": true` in .claude/gw.json (a no-op otherwise); the
size and "Done" rules of `check`, and the `done` subcommand, work on any log.

The log (config `log`) has a state table with one row per branch, labelled "<anything> · `<branch>`" (for example
"| **Task in progress · `claude/topic`** | text |"). Two accounts writing in the same cell ended in two tasks and two
contradicting "Next" lines, so each branch writes only in its own row and the row stays short.

  handoff.py check [FILE] [--date YYYY-MM-DD] [--strict]
                                                 with logRows: rows well formed, one per branch, <= 600 characters;
                                                 with --date, the "Updated" row is not older than that day; a "Task
                                                 in progress" row with no `branch` fails even if the other rows are
                                                 fine; and (D135) a "Task in progress" row of HEAD's log (at commit time
                                                 only, not with --at push) that is gone, not even renamed (its branch has no
                                                 row left), fails, unless the commit closes that branch (its row
                                                 says "merged, branch finished", close-row) or is a merge. On any log: every value cell of the state table (first
                                                 "Estado actual" / "Current state" section) <= 800 characters, and
                                                 the "Hecho (5 últimas)" / "Done (last 5)" section has <= 5 items,
                                                 numbered 1..n, each on its own line ("N. "). These last rules only
                                                 print `WARNING: ...` and exit 0; with --strict they fail (exit 1).
                                                 A cell over `handoff.cellHardLimit` (1600; 0 = off) fails even
                                                 without --strict (D96), naming `done` and `set-row`.
                                                 A log over `logSize` characters (config; 0 = no cap) also only warns,
                                                 even with --strict. With `pendingFile` set (config; D104): the log's
                                                 "Pendiente" / "Pending" section holds no "- " items of its own, only
                                                 a pointer line (the same soft rules: --strict fails; the pointer
                                                 carries no count, B38: `recover.py --state` counts the file). A
                                                 missing file, one with no "## Pendiente" / "## Pending" section
                                                 (`archive` needs it) or a pointer with an old "(N entradas)" count
                                                 only warn. --pending PATH reads the pending file from PATH (the
                                                 pre-push passes the pushed commit's copy; a missing PATH = no file)
  handoff.py preflight [--date YYYY-MM-DD] [--strict]
                                                 what the pre-push checks in the log, without pushing (D61): `check`
                                                 of the working copy's log with --date (default: today if the log has
                                                 uncommitted changes, else the day of the last commit that changed it,
                                                 as the pre-push takes the day of the newest commit that changes it),
                                                 and with logRows and a plan, `clash HEAD
                                                 refs/remotes/origin/<protectedBranch>`; with no such ref (a fresh
                                                 clone, no remote) the clash is skipped with a note, as the pre-push
                                                 skips it. With --strict the soft rules of `check` (the warnings)
                                                 fail too (exit 1), so one pass does the work of `check --strict`
  handoff.py move-pending [FILE]                 with `pendingFile` set: move the "- " items (and other text) of the
                                                 log's "Pendiente" / "Pending" section to the end of that file's
                                                 section of the same name (the file and the section are created when
                                                 missing), and leave in the log one pointer line with the link; only
                                                 an earlier pointer (a line that is not a list item and names the
                                                 file) is replaced, everything else moves
  handoff.py add-pending TEXT [--section HEADING]
                                                 append "- TEXT" at the end of the Pending section of `pendingFile`
                                                 (the log's own "Pendiente" / "Pending" section when unset), or at the
                                                 end of its "### HEADING" subsection (case and edge spaces ignored;
                                                 created at the end of Pending when missing); the file is created when
                                                 missing; prints one line, never the content (D95)
  handoff.py add-decision TEXT [--date YYYY-MM-DD]
                                                 append "- <date> — TEXT" at the end of the "Decisiones" / "Decisions"
                                                 section of `decisionsFile` (the log when empty; the section is created
                                                 before "Pendiente" or at the end); prints one line (D95)
  handoff.py done TEXT [FILE] [--date YYYY-MM-DD]
                                                 insert "1. <date> — TEXT" at the top of the Done section (date
                                                 default: today), renumber, drop items beyond 5 (a multi-line item
                                                 moves whole), leave the rest of the file byte for byte; exit 1 if
                                                 the section is missing
  handoff.py archive [FILE] [--dry-run] [--date YYYY-MM-DD]
                                                 move the "Pendiente" / "Pending" items (of `pendingFile` when set,
                                                 else of the log; top-level "- " bullets with
                                                 their continuation lines) whose first line names versions X.Y or
                                                 X.Y.Z, all <= the published one (`version` in .claude-plugin/
                                                 plugin.json; without it, the highest vX.Y.Z tag), to the archive file (config `logArchive`, not read at
                                                 session start) under a dated section, and leave one summary line
                                                 with the link where the first one was; an item with no version, or
                                                 "no archivar" / "do not archive" in its first line, stays. --dry-run
                                                 only prints what it would move. `check` warns when the log passes
                                                 `logSize` characters and names this command
  handoff.py own-row COMMIT BRANCH [--shared]   fail if COMMIT changes another branch's row or a shared row of the
                                                 state table ("Updated" and "Tests" are free); --shared, or
                                                 BITACORA_COMPARTIDA=1 / GW_SHARED_LOG=1, allows it
  handoff.py own-row --staged                   the same between HEAD and the index, for the branch being committed on
                                                 (the pre-commit hook, so the failure comes before the commit, not at
                                                 the push); passes at once if the log is not staged or is new, on a
                                                 detached HEAD (WARNING) and while a merge, cherry-pick or rebase is closing
  handoff.py set-row TEXT [--branch BRANCH]     rewrite the text of BRANCH's row (default: the current branch) without
                                                 closing it; fails, and writes nothing, if the row is missing, TEXT is
                                                 empty or has a newline, or it passes 600 characters; prints the
                                                 row as written and n/limit (set-row and close-row); both also set
                                                 today's date in the "Updated" row, if the log has one (D154)
  handoff.py closed BASE SHA                    every task closed in the plan between BASE and SHA ("- [x] **ID**"
                                                 or struck through) is also recorded in the "Done" section of SHA's
                                                 log: struck through there, or named on a line that starts with a date
  handoff.py closed --staged                    the same between HEAD and the index (the pre-commit hook); passes at
                                                 once if no plan file is staged, and while a merge, cherry-pick or
                                                 rebase is being closed (the pre-push checks those)
  handoff.py in-progress BASE SHA               WARNING only: a task marked 🚧 that the commits name, whose plan
                                                 entry did not change (it may still say "Next: X" with X done)
  handoff.py close-row [BRANCH] [--text TEXT]   rewrite BRANCH's row (or --branch; default: the current one) as "merged, branch finished" (last commit
                                                 before the PR, so main does not inherit a stale "Next")
  handoff.py close-row ID                       close TASK ID (C11): when ID has the shape of taskId and its task record
                                                 (`taskRecord.path`/ID.md) exists, it is a task, not a branch (the record's
                                                 existence decides; `--branch ID` always means the branch). Fails, writing
                                                 nothing and listing every reason, unless each box of `## Acceptance` is [x]
                                                 and names an existing test (`tests/test_X.py::Class[::test_y]`) or a
                                                 `== section` of the `check` commands (in backticks), and `## Verification`
                                                 holds an existing commit sha and a command (in backticks); then marks
                                                 ID's roadmap row done in every `roadmapFiles` file (the row must be
                                                 open) and prints it. An ID with no record and no branch row: create the
                                                 record, `task.py new ID`. Works without logRows; --text is for branches
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
  handoff.py next-id PREFIX [--fetch]           print the next free task id with PREFIX ("D" -> "D49", "QA-" or
                                                 "QA" -> "QA-8"): one past the highest that the plan opens in the work
                                                 tree, the index or any local or remote-tracking branch, so a new task
                                                 does not take an id another branch already took (`clash` finds that
                                                 only at the push). --fetch runs `git fetch --all` first and fails if
                                                 it fails. Also skips the ids named in `pendingFile` (D157). Works
                                                 without logRows; needs a plan

Common options: --root PATH (default: from this script's folder, via config.py), --plan PATH (repeatable; a file or a
folder with the plan/roadmap; env GW_PLAN, ':'-separated; config `plan`), --id-regex REGEX (task ids; env GW_TASK_ID;
config `taskId`; default
`[A-Z]{2,5}-\\d+[a-z]?`). Without a plan, `closed` and `in-progress` have nothing to compare and pass.
Exit 0 ok, 1 rule broken (each message ends with the command that fixes it), 2 bad usage or config.
Python 3.8+, stdlib only.
"""
import argparse
import ast
import contextlib
import datetime
import errno
import functools
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as gwconfig  # noqa: E402

# The size limits (a branch row, a state-table cell, the Done items) are the config key `handoff` (config.handoff).
INDEX = ""  # a "rev" for show()/plan_files(): the staged version
# The "Updated" row of the log: group 1 is what comes before the date, group 2 the date (check and set-row share it).
UPDATED_ROW = re.compile(r"(\|\s*\*\*(?:Actualizado|Updated)\*\*\s*\|\s*[`*]*)(\d{4}-\d{2}-\d{2})")


def today():
    """D154: today's date in LOCAL time, like the commit-msg hook's `date +%F` that `check --date` compares against
    (both follow TZ), so a row written here is never "stale" for the hook."""
    return datetime.date.today().isoformat()


FREE_ROWS = {"Actualizado", "Tests", "Updated"}  # shared rows every commit may touch
ROW = re.compile(r"^\|\s*\*\*(?P<label>.+?) · `(?P<branch>[^`]+)`\*\*\s*\|(?P<text>.*)\|\s*$")
STATE_HEADING = re.compile(r"^##\s+(Estado actual|Current state|Status)\b.*$", re.M | re.I)
DONE_HEADING = re.compile(r"^##\s+(Hecho|Done)\b.*$", re.M | re.I)
PENDING_HEADING = re.compile(r"^##\s+(Pendiente|Pending)\b.*$", re.I)
VERSION_IN_TEXT = re.compile(r"(?<![\w.])(\d+)\.(\d+)(?:\.(\d+))?(?!\w)(?!\.\d)")
KEEP_MARK = re.compile(r"no archivar|do not archive", re.I)
ARCHIVED_LINE = re.compile(r"^- \*\*(Archivado|Archived) \((\d{4}-\d{2}-\d{2})\):\*\* (\d+) ")
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
    """The task id pattern: `explicit` (--id-regex), else $GW_TASK_ID, else the config's `taskId` (its schema default when the config is a bare dict).
    Shared with commit-message.py so both read the ids the same way."""
    return explicit or os.environ.get("GW_TASK_ID") or config.get("taskId") or gwconfig.schema_default("taskId")


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


def long_cells(text, limit):
    """(label, size) of each value cell of the state table with more than `limit` characters."""
    found = []
    for line in section_lines(text, STATE_HEADING) or []:
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in CELL_SPLIT.split(line.strip())[1:-1]]
        if len(cells) < 2 or all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue
        label = cells[0].replace("*", "").replace("`", "").strip()
        found += [(label, len(c)) for c in cells[1:] if len(c) > limit]
    return found


def done_problems(text, add, recheck, limit):
    """Messages about the Done section: items not on their own line, numbering not 1..n, more than `limit`.
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
    if len(numbers) > limit:
        out.append(f"the Done section has {len(numbers)} items (limit {limit}); delete the oldest ones, the history "
                   f"is in git (the next entry drops them: {add})")
    return out


POINTER_COUNT = re.compile(r"\((\d+)\s+(?:entradas?|entry|entries)\)", re.I)
POINTER_START = re.compile(r"(?:Lo pendiente está en|Pending items live in)\s", re.I)  # the pointer's own wording
PENDING_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s")  # a top-level list item: "- ", "* ", "+ ", "1. ", "1) "


def pending_section(lines):
    """(head, end) of the "## Pendiente" / "## Pending" section in `lines` (no line ends), or (None, None)."""
    head = next((i for i, l in enumerate(lines) if PENDING_HEADING.match(l.rstrip("\r\n"))), None)
    if head is None:
        return None, None
    return head, next((i for i in range(head + 1, len(lines)) if lines[i].startswith("## ")), len(lines))


def pending_count(text):
    """Top-level items of the whole pending file `text`, in every section (B38: what `grep -n '^- '` shows), but the
    "Archivado" / "Archived" summary line."""
    return sum(1 for l in text.splitlines() if PENDING_ITEM.match(l) and not ARCHIVED_LINE.match(l))


def pending_problems(ctx, text, me, pending=None):
    """D104: with `pendingFile` set, the soft problems of the log's pending section (items kept in the log, no pointer
    line); a missing pending file, one with no pending section and a pointer with an old count are printed warnings.
    `pending` is where to read the pending file from (default: the working copy)."""
    rel = gwconfig.pending_file(ctx.config)
    if not rel:
        return []
    lines = text.splitlines()
    head, end = pending_section(lines)
    fix = f"{me} move-pending"
    if head is None:  # fail closed: the pending section is a "## Pendiente" / "## Pending" heading, nothing else
        return [f"the log has no \"## Pendiente\" / \"## Pending\" section to point to {rel} (pendingFile); add the "
                f"line \"## Pending\" to it and run: {fix}"]
    held = sum(1 for l in lines[head + 1:end] if PENDING_ITEM.match(l))
    if held:
        return [f"the log holds {held} pending item(s) under \"{lines[head].strip()}\", but they live in {rel} "
                f"(pendingFile); move them there: {fix}"]
    pointer = [l for l in lines[head + 1:end] if l.strip()]
    if not pointer:
        return [f"the log's \"{lines[head].strip()}\" section has no pointer line to {rel} (pendingFile); "
                f"write it: {fix}"]
    if any(POINTER_COUNT.search(l) for l in pointer):  # B38: one count, in one place (recover.py --state)
        print(f"WARNING: handoff: the log's pending pointer still carries a count (\"(N entradas)\" / \"(N entries)\"), "
              f"which nothing keeps up to date; drop it: {fix}")
    target = Path(pending) if pending is not None else ctx.root / rel
    try:
        found = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
    except OSError:
        found = None
    if found is None:
        print(f"WARNING: handoff: the pending file {rel} (pendingFile) does not exist; create it: {fix}")
    elif pending_section(found.splitlines())[0] is None:
        print(f"WARNING: handoff: the pending file {rel} (pendingFile) has no \"## Pendiente\" / \"## Pending\" "
              f"section, which `archive` needs; add it: {fix}")
    return []


CLOSED_ID_EXEMPT = re.compile(r"(?:\bver|\bsee|\bsee also|\brelated|\brevisi[oó]n|\breview)[*`]*\s*:?\s*[*`]*$", re.I)


def inside_parenthesis(before):
    """Q-39: whether the id that follows `before` sits inside an open parenthesis of its entry ("(B42, D3)"), even
    when the parenthesis opened on an earlier line."""
    return before.count("(") > before.count(")")


def closed_roadmap_ids(ctx, roadmap_path=None):
    """The ids of the rows of the first `roadmapFiles` file whose status starts with its `done` word, as a set; empty
    without roadmapFiles. `roadmap_path`: read the file from this path instead (the pushed one)."""
    import roadmap
    files = gwconfig.roadmap_files(ctx.config)
    path = (Path(roadmap_path) if roadmap_path is not None else ctx.root / files[0]["path"]) if files and files[0].get("done") else None
    if not path or not path.is_file():
        return set()
    done = files[0]["done"].lower()
    out = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        spans = roadmap.cells(line)
        if not spans or len(spans) < 3:
            continue
        key = line[spans[0][0]:spans[0][1]].strip(" *`~")
        if ctx.id.fullmatch(key) and roadmap.status_of(line).lower().startswith(done):
            out.add(key)
    return out


def closed_id_problems(ctx, pending=None, roadmap=None):
    """D177: with `pendingClosedIdCheck` (default true), one soft problem per open entry (`- [ ]`, with its indented
    continuation lines) of the pending file that cites an id whose roadmap row is closed, as if it were still to do.
    Exempt: an entry that starts with `Related: <id>`, an id written right after ver / see / see also / related /
    revisión / review (with an optional colon) and an id inside a parenthesis ("(B42, D3)", Q-39): those point at the
    closed task on purpose."""
    rel = gwconfig.pending_file(ctx.config)
    if not rel or not ctx.config.get("pendingClosedIdCheck", True):
        return []
    target = Path(pending) if pending is not None else ctx.root / rel
    try:
        found = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
        closed = closed_roadmap_ids(ctx, roadmap) if found else set()
    except (OSError, ImportError):
        return []
    if not closed:
        return []
    entries, cur = [], None
    for line in found.splitlines():
        if re.match(r"\s*- \[ \]", line):
            cur = [line]
            entries.append(cur)
        elif cur is not None and line.startswith((" ", "\t")) and line.strip():
            cur.append(line)
        else:
            cur = None
    out = []
    for entry in entries:
        text = "\n".join(entry)
        body = re.sub(r"^\s*- \[ \]\s*", "", text)
        body = re.sub(r"^[*`\s]*\d+(?:\.\d+)*[*`\s]*·\s*", "", body)  # a version prefix ("`0.10` · ")
        if re.match(rf"[*`]*related\s*:", body, re.I):
            continue
        for m in ctx.id.finditer(text):
            if (m.group(0) in closed and (m.start() == 0 or not text[m.start() - 1].isalnum())
                    and not CLOSED_ID_EXEMPT.search(text[:m.start()]) and not inside_parenthesis(text[:m.start()])):
                out.append(f"the open pending entry \"{entry[0].strip()[:70]}\" in {rel} cites {m.group(0)}, whose roadmap row "
                           f"is closed; close the entry, or write \"see {m.group(0)}\" / start it with \"Related: "
                           f"{m.group(0)}\" if the mention is on purpose (pendingClosedIdCheck in .claude/gw.json)")
                break
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
    sizes = gwconfig.handoff(ctx.config)
    hard = sizes["cellHardLimit"]  # D96: the warning alone got ignored (a cell reached 10 115 characters)
    cells = long_cells(text, min(sizes["cellLimit"], hard) if hard > 0 else sizes["cellLimit"])
    over = [(label, size) for label, size in cells if 0 < hard < size]
    soft = [f"a cell of the state table (\"{label}\") has {size} characters (limit {sizes['cellLimit']}); shorten it and move what "
            f"is done to the Done section: {me} done \"<text>\"" for label, size in cells
            if size > sizes["cellLimit"] and (label, size) not in over]
    hard_problems = [f"a cell of the state table (\"{label}\") has {size} characters, over the hard cap (handoff.cellHardLimit "
                     f"= {hard}; it fails even without --strict); move what is closed to the Done section: {me} done "
                     f"\"<text>\", then shorten the cell (a branch row: {me} set-row \"<short text>\" --branch <branch>; "
                     f"any other cell: edit {ctx.log})" for label, size in over]
    soft += done_problems(text, f"{me} done \"<text>\"", f"{me} check {path} --strict", sizes["doneItems"])
    soft += pending_problems(ctx, text, me, args.pending)
    soft += closed_id_problems(ctx, args.pending, getattr(args, "roadmap", None))
    cap = gwconfig.log_size(ctx.config)
    if cap > 0 and len(text) > cap:  # a warning only: it never fails the commit, not even with --strict
        if gwconfig.pending_file(ctx.config):  # `archive` works on pendingFile: it cannot shrink the log
            print(f"WARNING: handoff: the log has {len(text)} characters (cap logSize = {cap}); shorten it by hand (move "
                  f"what is done out of the state table: {me} done \"<text>\"; the pending items live in "
                  f"{gwconfig.pending_file(ctx.config)}, `archive` does not touch the log)")
        else:
            print(f"WARNING: handoff: the log has {len(text)} characters (cap logSize = {cap}); archive the items of "
                  f"published versions: {me} archive")
    problems = rows_problems(ctx, args, text.splitlines()) if ctx.config.get("logRows") else []
    if ctx.config.get("logRows"):
        for key, line in lost_task_rows(ctx, args, text):
            problems.append(f"the \"Task in progress\" row of {key} is gone from the state table compared with the previous "
                            f"log ({line[:60]}); restore it (git show HEAD:{ctx.log}) and, if the branch is "
                            f"finished, close it with: {me} close-row --branch {key}")
    problems += hard_problems
    if args.strict:
        problems += soft
    else:
        for w in soft:
            print(f"WARNING: handoff: {w}")
    if args.at == "push":  # the commit already exists: the fix is a new commit
        return report(problems, f"edit {ctx.log} and make a new commit with the fix: git add {ctx.log} && git commit")
    return report(problems, f"edit {ctx.log}, stage it (git add {ctx.log}) and repeat the same commit: git commit -m \"...\"")


def task_row_keys(text):
    """{key: line} of the "Task in progress" rows: the branch when the row has one (a renamed label is the same row),
    else the label."""
    out = {}
    for line in text.splitlines():
        m = TASK_ROW.match(line)
        if m:
            r = ROW.match(line)
            out[r.group("branch") if r else m.group(1).lower()] = line
    return out


def lost_task_rows(ctx, args, text):
    """D135: the "Task in progress" rows of HEAD's log that `text` no longer has, unless the commit closes their branch
    (close-row keeps the row, with the closed text) or is a merge. Commit time only: at push the pre-push checks the tip
    as a file, and a later commit may put the row back."""
    if (args.at == "push" or closing_other_side(ctx) or squash_in_progress(ctx)
            or os.environ.get("BITACORA_COMPARTIDA") or os.environ.get("GW_SHARED_LOG")):
        return []
    rev = "HEAD"
    if ctx.git("rev-parse", "--verify", "-q", rev).returncode != 0:
        return []  # the first commit: nothing before it
    if ctx.git("cat-file", "-e", f"{rev}:{ctx.log}").returncode != 0:
        return []  # the log is being created
    before = task_row_keys(ctx.show(rev, ctx.log))
    after = set(task_row_keys(text)) | {m.group("branch") for m in map(ROW.match, text.splitlines()) if m}  # any label
    closed = tuple(CLOSED_TEXT.values())
    return [(k, line) for k, line in sorted(before.items())
            if k not in after and ROW.match(line) and not any(c in line for c in closed)]  # no branch / closed: nothing to lose


def rows_problems(ctx, args, lines):
    problems = []
    limit = gwconfig.handoff(ctx.config)["rowLimit"]
    if args.date:
        found = next((m.group(2) for m in map(UPDATED_ROW.match, lines) if m), None)
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
        if size > limit:
            problems.append(f"row of {m.group('branch')} has {size} characters (limit {limit}); "
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
    """True while a merge, cherry-pick, revert or rebase is being closed: its closures come from the other side."""
    for head in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REBASE_HEAD", "REVERT_HEAD"):
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
        print(f"handoff: fix: python3 {HERE / 'handoff.py'} done '{t}: <what was done>'")
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


ID_NUMBER = re.compile(r"(?P<sep>-?)(?P<num>\d+)[a-z]?")


def id_prefix(taken):
    """The prefix of a task id, without its separator: "INS-3" -> "INS", "D12" -> "D", "QA-7b" -> "QA"."""
    m = re.match(r"(.*?)-?\d+[a-z]?$", taken)
    return m.group(1) if m else taken


def free_id(ctx, revs, taken, ids=(), sep=None):
    """The next id after the highest one with `taken`'s prefix that any of `revs` (or `ids`) opens, with the separator
    those ids use ("INS-4", "D49"); with none of them, `sep` (default: the one `taken` has)."""
    prefix = taken[:-1] if taken.endswith("-") else id_prefix(taken)
    top = 0
    if sep is None:
        sep = "-" if taken[len(prefix):].startswith("-") else ""
    for i in [i for rev in revs for i in ctx.titles(rev)] + list(ids):
        m = ID_NUMBER.fullmatch(i[len(prefix):]) if i.startswith(prefix) else None
        if m and int(m.group("num")) >= top:
            top, sep = int(m.group("num")), m.group("sep")
    return f"{prefix}{sep}{top + 1}"


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


def worktree_ids(ctx):
    """Ids the plan files in the work tree open (saved, not yet staged or committed)."""
    found = set()
    for p in ctx.plans:
        path = ctx.root / p
        files = sorted(path.rglob("*.md")) if path.is_dir() else [path] if path.is_file() else []
        for f in files:
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                m = ctx.entry.match(line)
                if m:
                    found.add(m.group("id"))
    return found


def pending_ids(ctx):
    """D157: ids named in the pending file (`pendingFile`), so next-id never proposes one already used there."""
    rel = gwconfig.pending_file(ctx.config)
    path = ctx.root / rel if rel else None
    if not path or not path.is_file():
        return set()
    text = path.read_text(encoding="utf-8", errors="replace")
    return {m.group(0) for m in re.finditer(rf"(?<![A-Za-z0-9_]){ctx.id_src}", text)}  # "abcD99" is not D99; works for ids starting with a non-word char


def cmd_next_id(ctx, args):
    if not ctx.plans:
        raise Usage("no plan to read task ids from; set `plan` in .claude/gw.json or pass --plan PATH")
    if args.fetch:
        r = ctx.git("fetch", "-q", "--all", "--prune")
        if r.returncode:
            print(f"handoff: git fetch failed, so the remote branches may be stale ({r.stderr.strip()}); fix the "
                  "network or the remote and rerun, or run without --fetch to use the branches already fetched")
            return 1
    refs = [r for r in ctx.git("for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes").stdout.split()
            if not r.endswith("/HEAD")]
    revs = refs + ([INDEX] if ctx.git("rev-parse", "-q", "--verify", "HEAD").stdout.strip() else [])
    prefix = args.prefix
    sep = "-" if prefix.endswith("-") or (ctx.id.fullmatch(f"{prefix}-1") and not ctx.id.fullmatch(f"{prefix}1")) else ""
    used = worktree_ids(ctx) | pending_ids(ctx)
    nxt = free_id(ctx, revs, prefix, used, sep)
    if not ctx.id.fullmatch(nxt):
        known = {id_prefix(i) for i in used | {i for rev in revs for i in ctx.titles(rev)}}
        known = sorted(k for k in known if ctx.id.fullmatch(f"{k}1") or ctx.id.fullmatch(f"{k}-1"))
        seen = (f"the prefixes this plan accepts: {', '.join(known)}; for example: handoff.py next-id {known[0]}"
                if known else "no id in the plan matches that pattern")
        raise Usage(f"{nxt} does not match the task id pattern ({ctx.id.pattern}); {seen}. If the plan's ids follow "
                    "another pattern, pass --id-regex REGEX (or set `taskId` in .claude/gw.json)")
    print(nxt)
    return 0


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
    text = re.sub(r"^\d{4}-\d{2}-\d{2}\s*[—–-]\s*", "", text)  # the entry gets its date below: never twice
    done_items = gwconfig.handoff(ctx.config)["doneItems"]
    if not text:
        raise Usage("TEXT is empty; give the entry: handoff.py done \"what was closed\"")
    try:
        raw = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Usage(f"cannot read {path} ({exc}); create the log or fix `log` in .claude/gw.json")
    lines = re.findall(r"[^\n]*\n|[^\n]+", raw)  # keeps each line ending: the rest of the file stays byte for byte
    head = next((i for i, l in enumerate(lines) if DONE_HEADING.match(l.rstrip("\r\n"))), None)
    if head is None:
        print(f"handoff: {path} has no \"## Hecho\" / \"## Done\" section; add the line \"## Done (last {done_items})\" "
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
        kept = [[entry]] + [p[0] for p in parts[:done_items - 1]]
        body = list(pre)
        for n, block in enumerate(kept):
            if n:
                body += gap
            body += [re.sub(r"^\d+\.", f"{n + 1}.", block[0], count=1)] + block[1:]
        body += tail
        dropped = max(len(parts) + 1 - done_items, 0)
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


def published_version(ctx):
    """The published version as (text, (major, minor, patch)): the highest `vX.Y.Z` tag of the repo or, without one,
    `version` of .claude-plugin/plugin.json at the root (the workflow repo). The tag goes first because the workflow
    repo bumps plugin.json before the release is published (D89)."""
    path = ctx.root / ".claude-plugin" / "plugin.json"
    fix = (f"archive needs the published version: tag the last release (git tag vX.Y.Z; git fetch --tags if it is "
           f"only on the remote) or create {path} with a \"version\" key, then rerun: "
           f"python3 {HERE / 'handoff.py'} archive")
    tags = ctx.git("tag", "--list", "v[0-9]*")
    found = [(tuple(int(g or 0) for g in m.groups()), m.group(0)) for m in
             (VERSION_IN_TEXT.fullmatch(t.strip()[1:]) for t in (tags.stdout if tags.returncode == 0 else "")
              .splitlines()) if m]
    if found:
        best = max(found)
        return best[1], best[0]
    if not path.exists():
        raise Usage(f"no vX.Y.Z tag in the repo and no {path}; {fix}")
    try:
        version = json.loads(path.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, AttributeError) as exc:
        raise Usage(f"cannot read the version from {path} ({exc}); {fix}")
    m = VERSION_IN_TEXT.fullmatch(version.strip()) if isinstance(version, str) else None
    if not m:
        raise Usage(f"{path} has no valid \"version\" (X.Y.Z); {fix}")
    return version, (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def archivable(first_line, published):
    """True when the item's first line names at least one version and every one is <= published (X.Y counts as X.Y.0)."""
    if KEEP_MARK.search(first_line) or ARCHIVED_LINE.match(first_line):
        return False
    found = [(int(a), int(b), int(c or 0)) for a, b, c in VERSION_IN_TEXT.findall(first_line)]
    return bool(found) and all(v <= published for v in found)


def cmd_archive(ctx, args):
    on_pending = not args.file and bool(gwconfig.pending_file(ctx.config))
    log_name = args.file or gwconfig.pending_file(ctx.config) or ctx.log
    path = Path(args.file) if args.file else ctx.root / log_name
    archive = ctx.root / gwconfig.log_archive(ctx.config)
    cap = 0 if on_pending else gwconfig.log_size(ctx.config)  # logSize caps the log
    me = f"python3 {HERE / 'handoff.py'}"
    try:
        raw = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        if on_pending:  # B38: the file it reads is the pending file, not the log
            raise Usage(f"cannot read {path} ({exc}); create the pending file ({me} move-pending), fix `pendingFile` "
                        "in .claude/gw.json, or save it as UTF-8")
        raise Usage(f"cannot read {path} ({exc}); create the log or fix `log` in .claude/gw.json")
    version, published = published_version(ctx)
    lines = re.findall(r"[^\n]*\n|[^\n]+", raw)
    head = next((i for i, l in enumerate(lines) if PENDING_HEADING.match(l.rstrip("\r\n"))), None)
    if head is None:
        how = f" (or run {me} move-pending, which adds it)" if on_pending else ""
        print(f"handoff: {path} has no \"## Pendiente\" / \"## Pending\" section; add the line \"## Pending\" to it"
              f"{how} and rerun: {me} archive" + ("" if on_pending else f" {path}"))
        return 1
    english = lines[head].split()[1].lower().startswith("pending")
    eol = "\r\n" if lines[head].endswith("\r\n") else "\n"
    end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    pre, items = [], []  # lines before the first bullet; each item = [its lines, the blank lines after it]
    for line in lines[head + 1:end]:
        bare = line.rstrip("\r\n")
        if bare.startswith("- "):
            items.append([[line], []])
        elif not items:
            pre.append(line)
        elif not bare.strip():
            items[-1][1].append(line)
        else:
            items[-1][0] += items[-1][1] + [line]
            items[-1][1] = []
    moved = [i for i, (body, _) in enumerate(items) if archivable(body[0].rstrip("\r\n"), published)]

    def shown(size):
        return f"{size} characters (cap {cap if cap else 'none'})"

    if not moved:
        print(f"handoff: nothing to archive in {path}: no Pending item names only versions <= {version}; "
              f"the log has {shown(len(raw.replace(chr(13) + chr(10), chr(10))))}")
        return 0
    prior = next((i for i, (body, _) in enumerate(items) if ARCHIVED_LINE.match(body[0])), None)
    count = len(moved) + (int(ARCHIVED_LINE.match(items[prior][0][0]).group(3)) if prior is not None else 0)
    try:
        link = Path(os.path.relpath(archive, path.resolve().parent)).as_posix()
    except ValueError:  # another drive on Windows: no relative path
        link = archive.as_posix()
    if english:
        summary = (f"- **Archived ({args.date}):** {count} item(s) of versions already published (≤ {version}) in "
                   f"[{archive.name}]({link})")
    else:
        summary = (f"- **Archivado ({args.date}):** {count} elemento(s) de versiones ya publicadas (≤ {version}) en "
                   f"[{archive.name}]({link})")
    kept, placed = [], prior is not None
    for i, (body, blanks) in enumerate(items):
        if i in moved:
            if not placed:
                kept.append([[summary + eol], blanks])
                placed = True
            elif i == len(items) - 1 and kept:
                kept[-1][1] = blanks  # the section's closing blank lines survive
            continue
        if i == prior:
            body = [summary + eol] + body[1:]
        kept.append([body, blanks])
    new = "".join(lines[:head + 1] + pre + [l for body, blanks in kept for l in body + blanks] + lines[end:])
    size = len(new.replace("\r\n", "\n"))
    if args.dry_run:
        print(f"handoff: would archive {len(moved)} item(s) of {log_name} to {archive}:")
        for i in moved:
            first = items[i][0][0].rstrip("\r\n")
            print("  " + (first if len(first) <= 100 else first[:99] + "…"))
        print(f"handoff: the log would have {shown(size)}; nothing was written (rerun without --dry-run)")
        return 0
    block = [f"## {args.date} — from {log_name}", ""] + [l.rstrip("\r\n") for i in moved for l in items[i][0]]
    try:
        archive.parent.mkdir(parents=True, exist_ok=True)
        old = archive.read_text(encoding="utf-8") if archive.exists() else (
            "# Hand-off archive\n\nItems moved out of the hand-off log by `handoff.py archive`; this file is not read at "
            "session start.\n")
        archive.write_text(old.rstrip("\n") + "\n\n" + "\n".join(block) + "\n", encoding="utf-8")
        path.write_bytes(new.encode("utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise Usage(f"cannot write the archive or the log ({exc}); check the permissions of {archive.parent} and {path}, "
                    "then rerun: handoff.py archive")
    print(f"handoff: archived {len(moved)} item(s) to {archive}; {log_name} now {shown(size)}; commit both files with "
          "the work")
    return 0


def write_atomic(path, data):
    """Write `data` (bytes) to `path` through a temp file in the same folder and os.replace (B38): a failed write
    leaves the old file whole."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except OSError:  # already renamed, or not there
            pass


def rewrite_row(ctx, branch, text):
    """Replace the text of `branch`'s row in the log file. Returns (rows found, the new row); writes only if exactly 1."""
    path = ctx.root / ctx.log
    try:
        with open(path, encoding="utf-8", newline="") as f:  # Path.read_text(newline=) is Python 3.13+
            raw = f.read()
    except OSError as exc:
        raise Usage(f"cannot read {path} ({exc}); fix `log` in .claude/gw.json")
    eol = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.split(eol)
    hit, new = 0, None
    for i, line in enumerate(lines):
        m = ROW.match(line)
        if m and m.group("branch") == branch:
            lines[i] = new = f"| **{m.group('label')} · `{branch}`** | {text} |"
            hit += 1
    if hit == 1:
        day = today()  # D154: the commit-msg rejects a stale "Updated" row
        for i, line in enumerate(lines):
            m = UPDATED_ROW.match(line)
            if m:
                lines[i] = f"{m.group(1)}{day}{line[m.end():]}"
                break
        with open(path, "w", encoding="utf-8", newline="") as f:  # Path.write_text(newline=) is Python 3.10+
            f.write(eol.join(lines))
    return hit, new


def show_row(ctx, row, text):
    """Print the row as written and its size against the limit (E61), so the caller need not reread the log."""
    print(f"  {row}")
    print(f"  {len(text.strip())}/{gwconfig.handoff(ctx.config)['rowLimit']} characters")


def row_branch(ctx, args):
    """The branch whose row set-row / close-row touch: --branch on both (close-row also takes it positional), else the
    current branch (D71)."""
    given = [b for b in (getattr(args, "branch", None), args.branch_opt) if b]
    if len(set(given)) > 1:
        raise Usage(f"two different branches ({given[0]} and {given[1]}); name one: handoff.py {args.cmd} --branch <branch>")
    branch = given[0] if given else current_branch(ctx)
    if not branch:
        raise Usage(f"detached HEAD, so there is no branch whose row to write; name it: handoff.py {args.cmd} --branch <branch>")
    return branch


def task_record_path(ctx, args):
    """(is the argument the shape of a task id, the path of its task record if that file exists else None). A branch
    given with --branch is always a branch: only the positional argument can be a task (C11)."""
    given = getattr(args, "branch", None)
    if not given or getattr(args, "branch_opt", None) or not re.fullmatch(ctx.id_src, given):
        return False, None
    path = Path(ctx.root) / gwconfig.task_record(ctx.config)["path"] / f"{given}.md"
    return True, (path if path.is_file() else None)


REF_TEST = re.compile(r"(?P<file>[\w./-]*test_[\w.-]+\.py)::(?P<cls>\w+)(?:::(?P<fn>\w+))?")
REF_SECTION = re.compile(r"`==\s*([^`]+?)\s*`")
SHA_WORD = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{7,40}(?![0-9A-Za-z])")
BOX = re.compile(r"^\s*[-*]\s*\[(.)\]\s*(.*)$")


def check_sections(ctx):
    """The `== …` titles the project's `check` commands print: every word of a command that is a file of the project
    is read for `section "title"` and `echo "== title"` (what tests/check.sh does)."""
    import shlex
    titles = set()
    for command in ctx.config.get("check") or []:
        try:
            words = shlex.split(command)
        except ValueError:
            words = command.split()
        for word in words:
            path = Path(ctx.root) / word
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
                titles.update(m.strip() for m in re.findall(r'(?m)^\s*section\s+"([^"]+)"', text))
                titles.update(m.strip() for m in re.findall(r'echo\s+"==\s*([^"]+)"', text))
    return titles


def acceptance_reasons(ctx, body, sections):
    boxes = [m for m in (BOX.match(l) for l in body.splitlines()) if m]
    if not boxes:
        return ["`## Acceptance` has no checkbox; write the criteria as `- [ ] text (tests/test_X.py::Class)`"]
    out = []
    root = Path(ctx.root).resolve()
    for m in boxes:
        mark, text = m.group(1), m.group(2).strip()
        shown = text if len(text) <= 60 else text[:57] + "..."
        if mark not in "xX":
            out.append(f"Acceptance box not ticked: {shown!r}; tick it with [x] once its test passes")
            continue
        named = 0
        for r in REF_TEST.finditer(text):
            named += 1
            path = (root / r.group("file")).resolve()
            if root not in path.parents or not path.is_file():
                out.append(f"Acceptance {shown!r} names {r.group('file')}, which does not exist; fix the name or write the test")
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, ValueError):
                out.append(f"Acceptance {shown!r}: {r.group('file')} does not parse as Python; fix the file")
                continue
            classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == r.group("cls")]
            if not classes:
                out.append(f"Acceptance {shown!r}: {r.group('file')} has no class {r.group('cls')} at module level; fix the name")
            elif r.group("fn") and not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == r.group("fn")
                                           for c in classes for n in c.body):
                out.append(f"Acceptance {shown!r}: class {r.group('cls')} of {r.group('file')} has no test {r.group('fn')}; fix the name")
        for title in REF_SECTION.findall(text):
            named += 1
            if title not in sections:
                out.append(f"Acceptance {shown!r} names the check section `== {title}`, which no `check` command prints; "
                           "fix the name (the `== …` lines of `bash tests/check.sh`)")
        if not named:
            out.append(f"Acceptance box ticked without a test: {shown!r}; name one as `tests/test_X.py::Class` "
                       "or a check section as `== name` (in backticks)")
    return out


RUNNERS = ("python", "python3", "bash", "sh", "zsh", "npm", "npx", "yarn", "pnpm", "make", "pytest", "node", "git", "cargo",
           "go", "uv", "pip", "ruby", "php", "mvn", "gradle", "dotnet", "deno", "bun", "tox", "gh")


def runnable(ctx, span):
    """Whether a backquoted text starts like a command: a known program, or an existing script of the project (a bare
    path such as docs/questions.md or a branch name is not one)."""
    words = span.split()
    if not words or SHA_WORD.fullmatch(span.strip()):
        return False
    first = words[0]
    if first in RUNNERS:
        return True
    path = Path(ctx.root) / first
    return first.endswith((".sh", ".py", ".js")) and path.is_file()


def verification_reasons(ctx, body):
    if not body.strip() or re.fullmatch(r"(?:\s|—|-|\*)*", body):
        return ["`## Verification` is empty or still the template; write the commit and the command that proves it"]
    out = []
    candidates = [w for w in SHA_WORD.findall(body) if re.search(r"\d", w)]
    known = [w for w in candidates
             if subprocess.run(["git", "-C", str(ctx.root), "cat-file", "-e", f"{w}^{{commit}}"],
                               capture_output=True).returncode == 0]
    if not candidates:
        out.append("`## Verification` names no commit sha; add the sha of the commit that did the work (git rev-parse --short HEAD)")
    elif not known:
        out.append(f"`## Verification` names {', '.join(candidates)}, which is not a commit of this repository; "
                   "fix the sha (git log --oneline)")
    spans = re.findall(r"`([^`\n]+)`", body) + [l.strip() for b in re.findall(r"```[^\n]*\n(.*?)```", body, re.S)
                                               for l in b.splitlines() if l.strip()]
    if not any(runnable(ctx, s) for s in spans):
        out.append("`## Verification` names no command; write the command that proves it between backticks, starting with "
                   "a program (python3, bash, npm, make, pytest, ...) or an existing script")
    return out


def close_task(ctx, task_id, record):
    """C11: mark a task's roadmap row done, only when its record shows the work is tested and verified."""
    import task as gwtask
    import roadmap as gwroadmap
    text = record.read_text(encoding="utf-8").replace("\r\n", "\n")
    sections = {h.lower(): b for h, b in gwtask.sections_of(text)}
    rel = record.relative_to(Path(ctx.root)).as_posix()
    reasons = []
    for name, check in (("acceptance", lambda b: acceptance_reasons(ctx, b, check_sections(ctx))),
                        ("verification", lambda b: verification_reasons(ctx, b))):
        if name in sections:
            reasons += check(sections[name])
        else:
            reasons.append(f"{rel} has no `## {name.title()}` section; see the template (task.py new)")
    if reasons:
        print(f"handoff: {task_id} is not ready to close, nothing was written ({len(reasons)} reasons) in {rel}:")
        for r in reasons:
            print(f"  - {r}")
        print(f"fix {rel} and run again: python3 {HERE / 'handoff.py'} close-row {task_id}")
        return 1
    files = gwconfig.roadmap_files(ctx.config)
    if not files:
        print("handoff: roadmapFiles is empty in .claude/gw.json, so there is no roadmap row to mark; list the roadmap "
              "in each language (see docs/en/config.md)")
        return 1
    try:
        loaded = gwroadmap.load_files(Path(ctx.root), files, task_id)
        print(f"handoff: {task_id} closed; roadmap rows marked done:")
        gwroadmap.cmd_done(loaded, task_id, today(), [], False)
    except gwroadmap.RoadmapError as exc:
        print(f"handoff: {exc}; nothing was written (see: python3 {HERE / 'roadmap.py'} show {task_id})")
        return 1
    print(f"commit it: git commit -am 'Close {task_id}'")
    return 0


def cmd_close_row(ctx, args):
    shaped, record = task_record_path(ctx, args)
    if record is not None:
        if args.text:
            raise Usage(f"--text is for a branch row; {args.branch} is a task (its record exists): drop --text")
        rc = close_task(ctx, args.branch, record)
        if rc == 0:
            import task as gwtask
            try:
                gwtask.clear_mark(ctx.root, args.branch)  # C4: a closed task is no longer the current one
            except gwtask.GitStuck:
                pass
        return rc
    text = args.text or CLOSED_TEXT.get(gwconfig.languages(ctx.config)["docs"]["primary"], CLOSED_TEXT["en"])
    branch = row_branch(ctx, args)
    hit = 0
    if ctx.config.get("logRows"):
        hit, row = rewrite_row(ctx, branch, text)
    if hit != 1:
        if shaped:
            rec = gwconfig.task_record(ctx.config)["path"]
            print(f"handoff: {branch} has no task record ({rec}/{branch}.md) and no branch row in {ctx.log}; for a task, "
                  f"create the record: python3 {HERE / 'task.py'} new {branch}; for a branch: handoff.py close-row --branch {branch}")
            return 1
        print(f"handoff: found {hit} rows for {branch}, expected 1; add the row first: edit {ctx.log}")
        return 1
    print(f"handoff: row of {branch} closed in {ctx.log}; commit it: git commit -am 'Close the log row of {branch}'")
    show_row(ctx, row, text)
    return 0


def cmd_set_row(ctx, args):
    branch = row_branch(ctx, args)
    text = args.text.strip()
    if not text or "\n" in text or "\r" in text:
        raise Usage("TEXT must be one non-empty line (a table cell); write the row text on a single line")
    text = re.sub(r"(?<!\\)\|", r"\\|", text)
    limit = gwconfig.handoff(ctx.config)["rowLimit"]
    if len(text) > limit:
        print(f"handoff: the text has {len(text)} characters (limit {limit}); shorten it, or move what is done to the Done "
              f"section: python3 {HERE / 'handoff.py'} done \"<text>\"")
        return 1
    hit, row = rewrite_row(ctx, branch, text)
    if hit != 1:
        print(f"handoff: found {hit} rows for {branch}, expected 1; add the row first: edit {ctx.log}")
        return 1
    print(f"handoff: row of {branch} updated in {ctx.log} ({len(text)} characters); commit it together with the work")
    show_row(ctx, row, text)
    return 0


def pending_skeleton(english):
    """The text of a new pending file (move-pending and add-pending create it the same way)."""
    title = "Pending" if english else "Pendiente"
    return (f"# {title}\n\n" + ("What is still open; the log only points here. Add and remove items in this file.\n"
                                  if english else
                                  "Lo que queda abierto; la bitácora solo apunta aquí. Se añade y se quita en este "
                                  "archivo.\n") + f"\n## {title}\n")


DECISIONS_HEADING = re.compile(r"^##\s+(Decisiones|Decisions)\b.*$", re.I)


def split_lines(raw):
    """The lines of `raw` cut at "\\n" only: a CRLF line keeps its "\\r" at its end, so every line keeps its own
    ending and a mixed file stays as it was; blank lines at the end are kept (only the last terminator is dropped).
    `write_added` joins them back with "\\n"; the lines a command adds take the "\\r" of their neighbour (`ends`)."""
    if not raw.strip():
        return []
    lines = raw.split("\n")
    if lines[-1] == "":  # the terminator of the last line, not a blank line
        lines.pop()
    elif len(lines) > 1 and lines[-2].endswith("\r"):  # no final newline: the last line ends like the one before
        lines[-1] += "\r"
    return lines


def ends(lines, at):
    """"\\r" when the line at `at` of `lines` (the last one when `at` is past the end) ends in CRLF, else ""."""
    i = min(at, len(lines) - 1)
    return "\r" if 0 <= i and lines[i].endswith("\r") else ""


def item_lines(text):
    """`text` as list lines: the first becomes a "- " item (a "* ", "+ ", "1. " marker is replaced; "- [ ]" stays); the
    others are indented two spaces and blank ones are dropped (a blank line would end the item)."""
    rows = [l for l in text.strip().splitlines() if l.strip()]
    first = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", rows[0].strip())
    return ["- " + first] + ["  " + l.rstrip() for l in rows[1:]]


def fenced_lines(lines):
    """The indexes of `lines` inside a fenced code block (```` ``` ```` or ``~~~``), fences included."""
    inside, mark, out = False, "", set()
    for i, l in enumerate(lines):
        m = re.match(r"\s*(```+|~~~+)", l)
        if m and (not inside or m.group(1)[0] == mark):
            inside, mark = not inside, m.group(1)[0]
            out.add(i)
        elif inside:
            out.add(i)
    return out


def section_span(lines, heading_re, lo=0, hi=None):
    """(head, end) of the first section in lines[lo:hi] whose heading matches `heading_re`, outside code fences; it
    ends at the next "## " heading (at the next "## " or "### " one when it is itself a "### " heading) or at `hi`;
    (None, None) when missing."""
    hi = len(lines) if hi is None else hi
    fenced = fenced_lines(lines)
    head = next((i for i in range(lo, hi) if i not in fenced and heading_re.match(lines[i])), None)
    if head is None:
        return None, None
    stops = ("## ", "### ") if lines[head].startswith("### ") else ("## ",)
    return head, next((i for i in range(head + 1, hi) if i not in fenced and lines[i].startswith(stops)), hi)


def insert_in_section(lines, head, end, items, lead=False):
    """Insert `items` after the last non-blank line of the section (head, end) of `lines`, in place (`lead`: after a
    blank line); the new lines end like the section's heading (CRLF or LF)."""
    cr = ends(lines, head)
    items = [l + cr for l in items]
    pos = end
    while pos > head + 1 and not lines[pos - 1].strip():
        pos -= 1
    new = ([cr] if pos == head + 1 or lead else []) + items
    if end == pos and end < len(lines):  # no blank line before the next heading
        new.append(cr)
    lines[pos:pos] = new


def read_for_add(path, me, cmd):
    try:
        return path.read_bytes().decode("utf-8") if path.exists() else None
    except (OSError, UnicodeDecodeError) as exc:
        raise Usage(f"cannot read {path} ({exc}); fix the file (UTF-8) and rerun: {me} {cmd}")


def log_is_english(ctx):
    """True when the log's Pending or Decisions heading is English (the way move-pending tells); the log is read once
    per run (n.º 11 of the D95 review): the answer is kept in `ctx`."""
    if not hasattr(ctx, "log_english"):
        ctx.log_english = _log_is_english(ctx)
    return ctx.log_english


def _log_is_english(ctx):
    try:
        for l in (ctx.root / ctx.log).read_text(encoding="utf-8").splitlines():
            if PENDING_HEADING.match(l):
                return l.split()[1].lower().startswith("pending")
            if DECISIONS_HEADING.match(l):
                return l.split()[1].lower().startswith("decisions")
    except (OSError, UnicodeDecodeError):
        pass
    return False


def write_added(path, lines, me, cmd):
    try:
        write_atomic(path, ("\n".join(lines) + "\n").encode("utf-8"))
    except OSError as exc:
        raise Usage(f"cannot write {path} ({exc}); check its permissions and rerun: {me} {cmd}")


# The commands that rewrite the log or `pendingFile`/`decisionsFile`: main() runs them under one lock, the single
# point that decides what is locked (n.º 1 and 4 of the review of D95).
WRITING_COMMANDS = ("done", "set-row", "close-row", "archive", "move-pending", "add-pending", "add-decision")


@contextlib.contextmanager
def write_lock(ctx, cmd):
    """One exclusive lock per repository, <git common dir>/gw/handoff.lock, around the read-change-write of a writing
    command (two `add-*` at once, or an `add-*` and a `move-pending`, lost an item: n.º 9 of the D95 review).
    `fcntl.flock`: the system drops it when the process ends, so a killed run leaves no orphan lock. It waits
    `handoff.lockWait` seconds and then fails saying how to rerun; only EWOULDBLOCK/EAGAIN mean "held". Without
    `fcntl` (Windows), without a git dir, or when the file system refuses locks (any other OSError) there is no lock
    and one `WARNING` line says so."""
    me = f"python3 {HERE / 'handoff.py'}"
    try:
        import fcntl
    except ImportError:
        print(f"handoff: WARNING: no fcntl on this platform, so {cmd} runs without a lock (two at once can lose an item)",
              file=sys.stderr)
        yield
        return
    common = gwconfig.git_common_dir(ctx.root)
    if common is None:
        print(f"handoff: WARNING: {ctx.root} is not in a git repository, so {cmd} runs without a lock", file=sys.stderr)
        yield
        return
    where = common / "gw" / "handoff.lock"
    wait = gwconfig.handoff(ctx.config)["lockWait"]
    try:
        where.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(where, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as exc:
        raise Usage(f"cannot open the lock {where} ({exc}); check its permissions and rerun: {me} {cmd}")
    try:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN):  # the file system has no flock: go without
                    print(f"handoff: WARNING: cannot lock {where} ({exc}), so {cmd} runs without a lock", file=sys.stderr)
                    break
                if time.monotonic() >= deadline:
                    raise Usage(f"another handoff.py holds the lock {where} and did not let go in {wait} s; wait for "
                                f"it, or raise handoff.lockWait in .claude/gw.json, and rerun: {me} {cmd}")
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)  # closing the descriptor releases the lock


def cmd_add_pending(ctx, args):
    me = f"python3 {HERE / 'handoff.py'}"
    if not args.text.strip():
        raise Usage(f"the text is empty; give it: {me} add-pending \"the item\"")
    own = gwconfig.pending_file(ctx.config)
    rel = own or ctx.log
    path = ctx.root / rel
    section = re.sub(r"^#+\s*", "", args.section.strip()).strip() if args.section else ""
    if args.section is not None and not section:
        raise Usage(f"--section is empty; give a title: {me} add-pending \"the item\" --section \"Title\"")
    raw = read_for_add(path, me, "add-pending")
    if raw is None:
        if not own:
            raise Usage(f"{path} does not exist; fix `log` in .claude/gw.json and rerun: {me} add-pending")
        raw = pending_skeleton(log_is_english(ctx))
    lines = split_lines(raw)
    head, end = section_span(lines, PENDING_HEADING)
    if head is None and own:
        cr = ends(lines, len(lines))
        lines += ([cr] if lines and lines[-1].strip() else []) + [("## Pending" if log_is_english(ctx) else "## Pendiente") + cr]
        head, end = len(lines) - 1, len(lines)
    elif head is None:
        raise Usage(f"{path} has no \"## Pendiente\" / \"## Pending\" section; add the line \"## Pending\" to it "
                    f"and rerun: {me} add-pending")
    items = item_lines(args.text)
    if section:  # a "### <title>" of the Pending section (case and edge spaces ignored); created at its end
        sub, sub_end = section_span(lines, re.compile(rf"^###\s+{re.escape(section)}\s*$", re.I), head + 1, end)
        if sub is None:
            insert_in_section(lines, head, end, [f"### {section}", ""] + items, lead=True)
        else:
            insert_in_section(lines, sub, sub_end, items)
    else:
        insert_in_section(lines, head, end, items)
    if own:
        count = pending_count("\n".join(lines))
    else:
        h, e = section_span(lines, PENDING_HEADING)
        count = pending_count("\n".join(lines[h + 1:e]))
    write_added(path, lines, me, "add-pending")
    print(f"handoff: added 1 item to {rel} ({count} in all)")
    return 0


def cmd_add_decision(ctx, args):
    me = f"python3 {HERE / 'handoff.py'}"
    if not args.text.strip():
        raise Usage(f"the text is empty; give it: {me} add-decision \"the decision\"")
    rel = gwconfig.decisions_file(ctx.config) or ctx.log
    path = ctx.root / rel
    separate = path.resolve() != (ctx.root / ctx.log).resolve()
    raw = read_for_add(path, me, "add-decision")
    if raw is None:
        if not separate:
            raise Usage(f"{path} does not exist; fix `log` in .claude/gw.json and rerun: {me} add-decision")
        raw = "# Decisions\n\n## Decisions\n" if log_is_english(ctx) else "# Decisiones\n\n## Decisiones\n"
    lines = split_lines(raw)
    text = re.sub(r"^\d{4}-\d{2}-\d{2}\s*[—–-]\s*", "", args.text.strip())  # the entry gets its date: never twice
    if not text:
        raise Usage(f"the text is empty (only a date was given); give it: {me} add-decision \"the decision\"")
    item = item_lines(f"{args.date} — {text}")
    head, end = section_span(lines, DECISIONS_HEADING)
    if head is None:
        title = "## Decisions" if log_is_english(ctx) else "## Decisiones"
        ph, _ = section_span(lines, PENDING_HEADING)
        if ph is not None and not separate:
            cr = ends(lines, ph)
            lines[ph:ph] = [title + cr, cr] + [l + cr for l in item] + [cr]
        else:
            cr = ends(lines, len(lines))
            lines += ([cr] if lines and lines[-1].strip() else []) + [title + cr, cr] + [l + cr for l in item]
    else:
        insert_in_section(lines, head, end, item)
    write_added(path, lines, me, "add-decision")
    print(f"handoff: added 1 decision to {rel}")
    return 0


def cmd_preflight(ctx, args):
    """D61: the log checks of prepush-branches.sh (check with a date, clash with origin/<protectedBranch>), run before
    pushing so a green `check` is enough to push."""
    me = f"python3 {HERE / 'handoff.py'}"
    if not ctx.config.get("logRows"):  # the date is a logRows rule: no git needed; the size and Done rules still run
        return cmd_check(ctx, argparse.Namespace(file=None, date=None, strict=args.strict, at="commit", pending=None))
    date, dirty = args.date, True
    status = ctx.git("status", "--porcelain", "--", ctx.log)
    # --no-merges: the pre-push dates the log by the commits that change it, never by a merge (diff-tree shows none
    # for one), so a CI pull_request merge made today does not move the day.
    last = ctx.git("log", "-1", "--no-merges", "--format=%as", "--", ctx.log)
    if status.returncode == 0 and last.returncode == 0:
        dirty = bool(status.stdout.strip()) or not last.stdout.strip()
    elif not date:
        raise Usage(f"git cannot read the state of {ctx.log} ({(status.stderr or last.stderr).strip()}); "
                    f"check the repository (git status) or pass the day: {me} preflight --date YYYY-MM-DD")
    if not date:
        date = today() if dirty else last.stdout.strip()
    # A clean log is already committed: the fix is a new commit (at="push"), not "run the commit again".
    code = cmd_check(ctx, argparse.Namespace(file=None, date=date, strict=args.strict, at="commit" if dirty else "push",
                                             pending=None))
    protected = ctx.config["protectedBranch"]
    ref = f"refs/remotes/origin/{protected}"
    if not ctx.git("rev-parse", "-q", "--verify", f"{ref}^{{commit}}").stdout.strip():
        print(f"handoff: preflight: no {ref} here, so the task-id clash check is skipped (the pre-push skips it too); "
              f"to run it, fetch it: git fetch origin {protected}")
        return code
    clash = cmd_clash(ctx, argparse.Namespace(revs=["HEAD", ref], warn=False, merge=None, tip=None, merging=False))
    return code or clash


def cmd_move_pending(ctx, args):
    rel = gwconfig.pending_file(ctx.config)
    me = f"python3 {HERE / 'handoff.py'}"
    if not rel:
        raise Usage("pendingFile is not set in .claude/gw.json; set it (for example \"docs/records/pending.md\") and "
                    f"rerun: {me} move-pending")
    path = Path(args.file) if args.file else ctx.root / ctx.log
    target = ctx.root / rel
    try:
        lines = re.findall(r"[^\n]*\n|[^\n]+", path.read_bytes().decode("utf-8"))
        old = target.read_text(encoding="utf-8") if target.exists() else None
    except (OSError, UnicodeDecodeError) as exc:
        raise Usage(f"cannot read {path} or {target} ({exc}); fix the file (UTF-8) and rerun: {me} move-pending")
    head, end = pending_section(lines)
    if head is None:
        raise Usage(f"{path} has no \"## Pendiente\" / \"## Pending\" section; add the line \"## Pending\" to it and "
                    f"rerun: {me} move-pending")
    english = lines[head].split()[1].lower().startswith("pending")
    eol = "\r\n" if lines[head].endswith("\r\n") else "\n"
    body = [l.rstrip("\r\n") for l in lines[head + 1:end]]
    names = {rel, Path(rel).name, "`pendingFile`"}  # the template's pointer names the key

    def is_pointer(l):  # an earlier pointer, as move-pending or the template writes it, naming the file; prose stays
        return POINTER_START.match(l) is not None and any(n in l for n in names)

    moved = [l for l in body if not is_pointer(l)]
    while moved and not moved[0].strip():
        moved.pop(0)
    while moved and not moved[-1].strip():
        moved.pop()
    title = "Pending" if english else "Pendiente"
    if old is None:
        old = pending_skeleton(english)
    flines = old.splitlines()
    fhead, fend = pending_section(flines)
    if fhead is None:
        flines += ["", f"## {title}"]
        fhead, fend = len(flines) - 1, len(flines)
    section = flines[fhead + 1:fend]
    while section and not section[-1].strip():
        section.pop()
    if moved:
        section = (section or [""]) + ([""] if section and section[-1].strip() and not moved[0].startswith("- ") else [])
        section += moved
    new_file = flines[:fhead + 1] + section + ([""] + flines[fend:] if fend < len(flines) else [])
    new_text = "\n".join(new_file).rstrip("\n") + "\n"
    count = pending_count(new_text)
    try:
        link = Path(os.path.relpath(target, path.resolve().parent)).as_posix()
    except ValueError:  # another drive on Windows: no relative path
        link = target.as_posix()
    pointer = (f"Pending items live in [`{rel}`]({link}); add and remove them there." if english else
               f"Lo pendiente está en [`{rel}`]({link}); se añade y se quita allí.")
    tail = [eol] if end < len(lines) else []
    new_log = "".join(lines[:head + 1] + [eol, pointer + eol] + tail + lines[end:])
    try:  # the pending file first: if the log write fails, the items are in both files, never in neither
        write_atomic(target, new_text.encode("utf-8"))
        write_atomic(path, new_log.encode("utf-8"))
    except OSError as exc:
        raise Usage(f"cannot write {target} or {path} ({exc}); check their permissions and rerun: {me} move-pending")
    print(f"handoff: moved {sum(1 for l in moved if PENDING_ITEM.match(l))} item(s) to {rel} ({count} in all); "
          "commit both files with the work")
    return 0


COMMANDS = {"check": cmd_check, "done": cmd_done, "own-row": cmd_own_row, "closed": cmd_closed,
            "in-progress": cmd_in_progress, "close-row": cmd_close_row, "set-row": cmd_set_row, "clash": cmd_clash,
            "archive": cmd_archive, "next-id": cmd_next_id, "move-pending": cmd_move_pending,
            "add-pending": cmd_add_pending, "add-decision": cmd_add_decision, "preflight": cmd_preflight}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root")
    p.add_argument("--plan", action="append")
    p.add_argument("--id-regex")
    # D134: the same three options after the subcommand too (`next-id B --plan docs/plan.md`); SUPPRESS keeps the
    # global value when the subcommand does not repeat them, and the subcommand's wins when both are given.
    common = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    common.add_argument("--root")
    common.add_argument("--plan", action="append")
    common.add_argument("--id-regex")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser = functools.partial(sub.add_parser, parents=[common])
    c = sub.add_parser("check")
    c.add_argument("file", nargs="?")
    c.add_argument("--date")
    c.add_argument("--strict", action="store_true")
    c.add_argument("--at", choices=("commit", "push"), default="commit",
                   help="where it runs: at commit time (the commit does not exist yet) or at push time (it does)")
    c.add_argument("--roadmap", help="read the roadmap (roadmapFiles[0]) from this path for the closed-id check; a missing one = none")
    c.add_argument("--pending", help="read the pending file (pendingFile) from this path; a missing one = no file")
    d = sub.add_parser("done")
    d.add_argument("text")
    d.add_argument("file", nargs="?")
    d.add_argument("--date")
    a = sub.add_parser("archive")
    a.add_argument("file", nargs="?")
    a.add_argument("--date")
    a.add_argument("--dry-run", action="store_true")
    f = sub.add_parser("preflight")
    f.add_argument("--date")
    f.add_argument("--strict", action="store_true")
    m = sub.add_parser("move-pending")
    m.add_argument("file", nargs="?")
    ap = sub.add_parser("add-pending")
    ap.add_argument("text")
    ap.add_argument("--section")
    ad = sub.add_parser("add-decision")
    ad.add_argument("text")
    ad.add_argument("--date")
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
    r.add_argument("branch", nargs="?")
    r.add_argument("--branch", dest="branch_opt")
    r.add_argument("--text")
    n = sub.add_parser("next-id")
    n.add_argument("prefix")
    n.add_argument("--fetch", action="store_true")
    w = sub.add_parser("set-row")
    w.add_argument("text")
    w.add_argument("--branch", dest="branch_opt")
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
        if args.cmd == "archive":
            args.date = args.date or today()
        elif args.cmd in ("done", "add-decision"):
            args.date = args.date or today()
        elif (not ctx.config.get("logRows") and args.cmd not in ("check", "archive", "next-id", "move-pending",
                                                                 "add-pending", "preflight")
              and not (args.cmd == "close-row" and task_record_path(ctx, args)[0])):  # a task id needs no branch rows
            if args.cmd in ("set-row", "close-row"):
                print("handoff: logRows is off in .claude/gw.json, so there are no branch rows and nothing was written; "
                      f"enable it: set \"logRows\": true in .claude/gw.json, then rerun {args.cmd}")
                return 1
            return 0  # the branch-row module is off: nothing to check (`check` still reads the size and Done rules)
        with (write_lock(ctx, args.cmd) if args.cmd in WRITING_COMMANDS else contextlib.nullcontext()):
            return COMMANDS[args.cmd](ctx, args)
    except Usage as exc:
        print(f"handoff: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
