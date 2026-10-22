#!/usr/bin/env python3
# galivelop-workflow v0.2.0
"""Hand-off log rules, for projects with `"logRows": true` in .claude/gw.json (a no-op otherwise).

The log (config `log`) has a state table with one row per branch, labelled "<anything> · `<branch>`" (for example
"| **Task in progress · `claude/topic`** | text |"). Two accounts writing in the same cell ended in two tasks and two
contradicting "Next" lines, so each branch writes only in its own row and the row stays short.

  bitacora.py check [FILE] [--date YYYY-MM-DD]   rows well formed, one per branch, <= 600 characters; with --date,
                                                 the "Updated" row is not older than that day
  bitacora.py own-row COMMIT BRANCH [--shared]   fail if COMMIT changes another branch's row or a shared row of the
                                                 state table ("Updated" and "Tests" are free); --shared, or
                                                 BITACORA_COMPARTIDA=1 / GW_SHARED_LOG=1, allows it
  bitacora.py closed BASE SHA                    every task closed in the plan between BASE and SHA ("- [x] **ID**"
                                                 or struck through) is also listed in the "Done" section of SHA's log
  bitacora.py in-progress BASE SHA               WARNING only: a task marked 🚧 that the commits name, whose plan
                                                 entry did not change (it may still say "Next: X" with X done)
  bitacora.py close-row BRANCH [--text TEXT]     rewrite BRANCH's row as "merged, branch finished" (last commit
                                                 before the PR, so main does not inherit a stale "Next")

Common options: --root PATH (default: from this script's folder, via config.py), --plan PATH (repeatable; a file or a
folder with the plan/roadmap; env GW_PLAN, ':'-separated; config `plan`), --id-regex REGEX (task ids; env GW_TASK_ID;
config `taskId`; default
`[A-Z]{2,5}-\\d+[a-z]?`). Without a plan, `closed` and `in-progress` have nothing to compare and pass.
Exit 0 ok, 1 rule broken (each message ends with the command that fixes it), 2 bad usage or config.
Python 3.8+, stdlib only.
"""
import argparse
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
FREE_ROWS = {"Actualizado", "Tests", "Updated"}  # shared rows every commit may touch
DEFAULT_ID = r"[A-Z]{2,5}-\d+[a-z]?"
ROW = re.compile(r"^\|\s*\*\*(?P<label>.+?) · `(?P<branch>[^`]+)`\*\*\s*\|(?P<text>.*)\|\s*$")
STATE_HEADING = re.compile(r"^##\s+(Estado actual|Current state|Status)\b.*$", re.M | re.I)
DONE_HEADING = re.compile(r"^##\s+(Hecho|Done)\b.*$", re.M | re.I)
RANGE = r"\s*(?:…|\.\.\.|–|—|\ba\b|\bto\b)\s*"
CLOSED_TEXT = {"es": "Al fusionarse, rama terminada: no queda nada pendiente en ella.",
               "en": "Merged, branch finished: nothing is pending on it."}


class Usage(Exception):
    pass


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
        pattern = args.id_regex or os.environ.get("GW_TASK_ID") or self.config.get("taskId") or DEFAULT_ID
        try:
            self.id = re.compile(pattern)
        except re.error as exc:
            raise Usage(f"--id-regex / GW_TASK_ID is not a valid regex ({exc}); fix it and rerun")
        self.id_src = f"(?:{pattern})"
        self.sep = rf"(?:{RANGE}|\s*(?:,|\by\b|\band\b)\s*)"
        self.closed_box = re.compile(rf"^\s*[-*]\s*\[[xX]\]\s*(?:\*\*)?`?(?P<id>{self.id_src})", re.M)
        self.entry = re.compile(rf"[-|]\s*(?:\[(?P<box>[ xX])\]\s*)?(?P<strike>~~)?\s*(?:\*\*)?`?(?P<id>{self.id_src})")
        self.bullet = re.compile(rf"^\s*(?:[-*]|\d+\.)\s*(?:\*\*)?`?(?P<id>{self.id_src})", re.M)

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
        """Plan/roadmap files at `rev` (a plan entry may be a folder)."""
        out = []
        for p in self.plans:
            r = self.git("ls-tree", "-r", "--name-only", rev, "--", p)
            out += [f for f in r.stdout.splitlines() if f.endswith(".md")]
        return sorted(set(out))

    def show(self, rev, path):
        r = self.git("show", f"{rev}:{path}")
        return r.stdout if r.returncode == 0 else ""

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


def cmd_check(ctx, args):
    path = Path(args.file) if args.file else ctx.root / ctx.log
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise Usage(f"cannot read {path} ({exc}); create the log or fix `log` in .claude/gw.json")
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
    return report(problems, f"edit {ctx.log} and commit again: git commit --amend")


def report(problems, fix):
    for p in problems:
        print(f"bitacora: {p}")
    if problems:
        print(f"bitacora: fix: {fix}")
    return 1 if problems else 0


def cmd_own_row(ctx, args):
    if args.shared or os.environ.get("BITACORA_COMPARTIDA") or os.environ.get("GW_SHARED_LOG"):
        return 0
    parent = ctx.git("rev-parse", "--verify", "-q", f"{args.commit}^").stdout.strip()
    bad = foreign_rows(log_at(ctx, parent) if parent else "", log_at(ctx, args.commit), args.branch)
    for key in bad:
        print(f"bitacora: the commit changes the row \"{key}\", which is not {args.branch}'s; each branch writes only in "
              "its own row. If it is on purpose (closing a PR, a shared row), push with: BITACORA_COMPARTIDA=1 git push")
    return 1 if bad else 0


def cmd_closed(ctx, args):
    if not ctx.plans:
        return 0
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
    listed = ctx.closed_ids(done) | {x.group("id") for x in ctx.bullet.finditer(done)}
    missing = sorted(new - listed)
    for t in missing:
        print(f"bitacora: {t} is closed in the plan; list it in the \"Done\" section of {ctx.log}")
    if missing:
        print(f"bitacora: fix: edit {ctx.log}, then git commit --amend")
    return 1 if missing else 0


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


def cmd_close_row(ctx, args):
    path = ctx.root / ctx.log
    try:
        lines = path.read_text(encoding="utf-8").split("\n")
    except OSError as exc:
        raise Usage(f"cannot read {path} ({exc}); fix `log` in .claude/gw.json")
    text = args.text or CLOSED_TEXT.get(ctx.config["language"], CLOSED_TEXT["en"])
    hit = 0
    for i, line in enumerate(lines):
        m = ROW.match(line)
        if m and m.group("branch") == args.branch:
            lines[i] = f"| **{m.group('label')} · `{args.branch}`** | {text} |"
            hit += 1
    if hit != 1:
        print(f"bitacora: found {hit} rows for {args.branch}, expected 1; add the row first: edit {ctx.log}")
        return 1
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"bitacora: row of {args.branch} closed in {ctx.log}; commit it: git commit -am 'Close the log row of {args.branch}'")
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
    o = sub.add_parser("own-row")
    o.add_argument("commit")
    o.add_argument("branch")
    o.add_argument("--shared", action="store_true")
    for name in ("closed", "in-progress"):
        s = sub.add_parser(name)
        s.add_argument("base")
        s.add_argument("sha")
    r = sub.add_parser("close-row")
    r.add_argument("branch")
    r.add_argument("--text")
    args = p.parse_args(argv)
    if getattr(args, "date", None) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        print("bitacora: --date must be YYYY-MM-DD; fix it and rerun", file=sys.stderr)
        return 2
    try:
        ctx = Ctx(args)
        if not ctx.config.get("logRows"):
            return 0  # the module is off: nothing to check
        return {"check": cmd_check, "own-row": cmd_own_row, "closed": cmd_closed,
                "in-progress": cmd_in_progress, "close-row": cmd_close_row}[args.cmd](ctx, args)
    except Usage as exc:
        print(f"bitacora: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
