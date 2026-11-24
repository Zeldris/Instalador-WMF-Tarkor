#!/usr/bin/env python3
# galivelop-workflow v0.9.0
"""Everything about one task id, gathered on the spot from the repo (D14); nothing is stored, so there is no index
to keep in step.

  python3 trace.py ID [--json] [--limit N] [--no-docs] [--root PATH]

Sources, in two groups (a section with nothing is left out of the text output). DECLARED is what the project states
about the id; DEDUCED is only a mention found by reading text:
  roadmap   declared: the table rows whose first cell is ID, in each file of `roadmapFiles`, with their `## ` section;
            a row with the same id cell in a later file (the translation) is folded into the first as `also`
  log   deduced:       the lines of the log (`log`) that name ID
  pending   deduced: the lines of the pending file (`pendingFile`) that name ID
  commits   declared: the commits (all local branches and remote-tracking refs) whose `Refs:` trailer lists ID or
            whose subject scope names it (`feat(D14): ...`, `feat(D1, D14): ...`); and the merge commits whose
            message names it (the branch that was merged: the offline stand-in for a PR; nothing is fetched)
  task      declared: the task record `<taskRecord.path>/ID.md` (its Goal and the state of its Acceptance boxes) and the
            decision log entries in `<taskRecord.path>/ID/`, sorted by file name (so by date), each with its date,
            agent, commit (read from `git log --diff-filter=A` of the file; `pending` only while it is not committed) and Why; an entry whose form is wrong is shown
            with the reason and a note, never a crash. The task's own files are not listed again under docs; shown
            even with --no-docs (it reads two named paths, not the tracked .md files)
  docs      deduced: the tracked Markdown files that name ID, other than the roadmap, the log and the pending file (copies
            under `.claude/` are skipped: they are generated); --no-docs skips it without reading any .md
"Names ID" is a whole-word match: D1 does not match D14 or D1a. --limit N (default 20) caps the entries shown per
source; the text says how many were left out (--json always carries every entry).

ID must match the project's `taskId` (config key; the schema default applies only when the project sets none).
A roadmap id cell, a `Refs:` value or a subject scope that lists ids (`D61, D62`) or a range with one prefix
(`E9-E16`) names every id in it. A merge commit counts only through its subject or its `Refs:`, never its body.
Exit 0 when something names ID, 1 when ID is well formed but nothing does (the message says where it looked), 2 on a
malformed ID, a bad config or no git repository. --json prints one object: id, found, `declared` {roadmap, task, commits}, `deduced` {log, pending, docs} and notes.
Project root: config.find_root (--root PATH, else the script's own repo, never the current directory first).
Python 3.8+ standard library only.
"""
import argparse
import json
import posixpath
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, str(HERE))
import config  # noqa: E402
import roadmap  # noqa: E402
import task as taskrec  # noqa: E402

DECLARED = ("roadmap", "task", "commits")
DEDUCED = ("log", "pending", "docs")
SOURCES = DECLARED + DEDUCED
SNIPPET = 160


class TraceError(Exception):
    pass


def word_re(task):
    """A whole-word match for `task`: not glued to letters, digits, `_` or `-` before, nor to letters, digits or `_` after."""
    return re.compile(r"(?<![\w-])" + re.escape(task) + r"(?!\w)")


RANGE = re.compile(r"^([A-Za-z]+-?)(\d+)([a-z]?)-\1(\d+)\3$")
ITEM = re.compile(r"^([A-Za-z]+-?)(\d+)$")


def names_id(text, task):
    """True when `text` (a roadmap id cell, a `Refs:` value or a subject scope) lists `task`: as an item of a
    comma-, semicolon- or space-separated list (`D61, D62`), or inside a range with the same prefix (`E9-E16`)."""
    own = ITEM.match(task)
    for item in re.split(r"[,;\s]+", text.strip().strip("`")):
        item = item.strip("`")
        if item == task:
            return True
        m = RANGE.match(item)
        if m and own and own.group(1) == m.group(1) and int(m.group(2)) <= int(own.group(2)) <= int(m.group(4)) \
                and int(m.group(4)) - int(m.group(2)) < 1000:
            return True
    return False


def snippet(text):
    text = " ".join(text.split())
    return text if len(text) <= SNIPPET else text[:SNIPPET - 1] + "…"


def read_lines(path):
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None


def roadmap_rows(root, files, task):
    rows, notes, first = [], [], {}  # first: id cell -> the row of the first file that has it
    for entry in files:
        lines = read_lines(root / entry["path"])
        if lines is None:
            notes.append(f"cannot read {entry['path']}; fix roadmapFiles in .claude/gw.json")
            continue
        heading = ""
        for n, line in enumerate(lines, 1):
            if line.startswith("## "):
                heading = line.strip()
            spans = roadmap.cells(line)
            if spans and names_id(line[spans[0][0]:spans[0][1]], task):
                key = line[spans[0][0]:spans[0][1]].strip()
                if key in first and first[key]["file"] != entry["path"]:  # the translation of a row already listed
                    first[key]["also"].append({"file": entry["path"], "line": n})
                    continue
                first[key] = {"file": entry["path"], "line": n, "section": heading, "text": snippet(line), "also": []}
                rows.append(first[key])
    return rows, notes


def mentions(root, rel, pattern):
    """([{file, line, text}], note) for the lines of `rel` that match; ([], None) when `rel` is empty."""
    if not rel:
        return [], None
    lines = read_lines(root / rel)
    if lines is None:
        return [], f"cannot read {rel}"
    return [{"file": rel, "line": n, "text": snippet(line)} for n, line in enumerate(lines, 1) if pattern.search(line)], None


def git(root, *args):
    try:
        done = subprocess.run(["git", "-C", str(root)] + list(args), capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
    except OSError as exc:
        raise TraceError(f"cannot run git ({exc.strerror}); install git")
    if done.returncode != 0:
        raise TraceError(f"git {' '.join(args[:2])} failed: {done.stderr.strip() or done.returncode}")
    return done.stdout


def commit_entries(root, task, pattern):
    out = git(root, "log", "--all", "--format=%x1e%H%x1f%P%x1f%B")
    found = []
    for record in out.split("\x1e"):
        if not record.strip():
            continue
        sha, parents, message = record.split("\x1f", 2)
        lines = message.strip().splitlines()
        subject = lines[0] if lines else ""
        refs = []
        for line in lines[1:]:
            m = re.match(r"Refs:\s*(.*)$", line)
            if m:
                refs.append(m.group(1))
        scope = re.match(r"^(?:WIP:\s*)?[\w-]+\(([^)]*)\)!?:", subject)
        if any(names_id(r, task) for r in refs):
            how = "refs"
        elif scope and names_id(scope.group(1), task):
            how = "scope"
        elif len(parents.split()) > 1 and pattern.search(subject):  # a merge: its subject or Refs:, never the body
            how = "merge"
        else:
            continue
        found.append({"sha": sha, "short": sha[:7], "how": how, "subject": snippet(subject)})
    return found


def task_entries(root, cfg, task, notes):
    """The task record and its decision log entries as items: {kind: record|entry, file, ...}; [] when there are none."""
    tr = config.task_record(cfg)
    base = tr["path"]
    rec_rel = posixpath.join(base, task + ".md")
    items = []
    text = read_lines(root / rec_rel) if (root / rec_rel).is_file() else None
    if text is not None:
        body = {h.lower(): b for h, b in taskrec.sections_of("\n".join(text))}
        goal = body.get(tr["sections"][0].lower(), "")
        acc = body.get(taskrec.ACCEPTANCE.lower(), "")
        done = len(re.findall(r"^\s*[-*]\s*\[[xX]\]", acc, re.M))
        total = done + len(re.findall(r"^\s*[-*]\s*\[ \]", acc, re.M))
        items.append({"kind": "record", "file": rec_rel, "goal": snippet(goal), "done": done, "total": total})
    elif (root / rec_rel).is_file():
        notes.append(f"cannot read {rec_rel} (not UTF-8?); it was skipped")
    folder = root / base / task
    names = sorted(p.name for p in folder.glob("*.md") if p.is_file()) if folder.is_dir() else []
    for name in names:
        rel = posixpath.join(base, task, name)
        lines = read_lines(root / rel)
        if lines is None:
            notes.append(f"cannot read {rel} (not UTF-8?); it was skipped")
            continue
        first = next((l for l in lines if l.strip()), "")
        parts = first[2:].split(taskrec.SEP) if first.startswith("# ") else []
        date, agent, commit = (x.strip() for x in parts[:3]) if len(parts) == 4 else (name[:10], "?", "?")
        errors = taskrec.entry_errors("\n".join(lines), task, cfg)
        why = {h.lower(): b for h, b in taskrec.sections_of("\n".join(lines))}.get(tr["logSections"][0].lower(), "")
        if commit == tr["pendingMarker"]:  # the header is never rewritten: the commit that added the file, if any
            try:
                commit = taskrec.resolve(root, rel) or commit
            except OSError:
                pass
        item = {"kind": "entry", "file": rel, "date": date, "agent": agent, "commit": commit, "why": snippet(why)}
        if errors:
            item["warning"] = errors[0]
            notes.append(f"{rel} is not a valid decision log entry: {errors[0]}")
        items.append(item)
    return items


def doc_entries(root, task, pattern, skip, notes):
    names = git(root, "ls-files", "-z", "--", "*.md").split("\0")
    found = []
    for rel in sorted(n for n in names if n and n not in skip and not n.startswith(".claude/")):
        lines = read_lines(root / rel)
        if lines is None:
            notes.append(f"cannot read {rel} (not UTF-8?); it was skipped")
            continue
        for n, line in enumerate(lines, 1):
            if pattern.search(line):
                found.append({"file": rel, "line": n, "text": snippet(line)})
    return found


def collect(root, cfg, task, docs=True):
    pattern = word_re(task)
    notes = []
    rows, more = roadmap_rows(root, config.roadmap_files(cfg), task)
    notes += more
    log_rel = cfg.get("log") or ""
    pend_rel = config.pending_file(cfg)
    log_hits, note = mentions(root, log_rel, pattern)
    notes += [note] if note else []
    pend_hits, note = mentions(root, pend_rel, pattern)
    notes += [note] if note else []
    task_items = task_entries(root, cfg, task, notes)
    skip = {e["path"] for e in config.roadmap_files(cfg)} | {log_rel, pend_rel} | {i["file"] for i in task_items}
    commits = commit_entries(root, task, pattern)
    found_docs = doc_entries(root, task, pattern, skip, notes) if docs else []
    return {"id": task, "declared": {"roadmap": rows, "task": task_items, "commits": commits},
            "deduced": {"log": log_hits, "pending": pend_hits, "docs": found_docs}, "notes": notes}


def render(result, limit):
    lines = [f"trace {result['id']}"]
    for group, names in (("declared", DECLARED), ("deduced", DEDUCED)):
        if any(result[group][s] for s in names):
            lines.append(f"\n#### {group}")
        lines += render_group(result[group], names, limit)
    for note in result["notes"]:
        lines.append(f"\nnote: {note}")
    return "\n".join(lines)


def render_group(group, names, limit):
    lines = []
    for source in names:
        items = group[source]
        if not items:
            continue
        lines.append(f"\n== {source} ({len(items)})")
        for item in items[:limit]:
            if source == "commits":
                lines.append(f"  {item['short']} [{item['how']}] {item['subject']}")
            elif source == "task" and item["kind"] == "record":
                lines.append(f"  {item['file']}: Goal: {item['goal']}; Acceptance {item['done']}/{item['total']} done")
            elif source == "task":
                warn = f"  [WARNING: {item['warning']}]" if "warning" in item else ""
                lines.append(f"  {item['date']} · {item['agent']} · {item['commit']} ({item['file']}): "
                             f"{item['why']}{warn}")
            elif source == "roadmap":
                also = "".join(f" (also {a['file']}:{a['line']})" for a in item["also"])
                lines.append(f"  {item['file']}:{item['line']} {item['section']}{also}\n    {item['text']}")
            else:
                lines.append(f"  {item['file']}:{item['line']}: {item['text']}")
        if len(items) > limit:
            lines.append(f"  … {len(items) - limit} more (--limit N, or --json for all)")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="Everything about one task id, gathered on the spot.")
    ap.add_argument("id", help="task id, e.g. D14")
    ap.add_argument("--json", action="store_true", help="one JSON object instead of text")
    ap.add_argument("--limit", type=int, default=20, help="entries per source in the text output (default 20)")
    ap.add_argument("--no-docs", action="store_true", help="skip the search in tracked .md files (reads none of them)")
    ap.add_argument("--root", help="project root (default: the script's own repo)")
    args = ap.parse_args(argv)
    if args.limit < 1:
        print("trace.py: --limit must be 1 or more; pass e.g. --limit 20", file=sys.stderr)
        return 2
    try:
        root = config.find_root(args.root)
        cfg = config.load(root)
        id_src = cfg.get("taskId") or config.schema_default("taskId")
        try:
            ok = re.fullmatch(id_src, args.id)
        except re.error as exc:
            raise TraceError(f"taskId in .claude/gw.json is not usable ({exc}); fix it: python3 {HERE / 'config.py'} validate")
        if not ok:
            raise TraceError(f"{args.id!r} is not a task id: it must match taskId {id_src!r} (e.g. D14); "
                             "list the ids with: python3 .claude/gw/scripts/roadmap.py list <version>")
        result = collect(root, cfg, args.id, docs=not args.no_docs)
    except (config.ConfigError, TraceError) as exc:
        print(f"trace.py: {exc}", file=sys.stderr)
        return 2
    result["found"] = any(result[g][s] for g, names in (("declared", DECLARED), ("deduced", DEDUCED)) for s in names)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["found"]:
        print(render(result, args.limit))
    else:
        where = ("tracked .md files were skipped (--no-docs)" if args.no_docs else "and tracked .md files")
        print(f"trace {args.id}: nothing names it (looked in roadmapFiles, the log, pendingFile, the commits' Refs: "
              f"and subject scopes; {where}); check the id, or fetch the branches that carry it: git fetch --all",
              file=sys.stderr)
        for note in result["notes"]:
            print(f"note: {note}", file=sys.stderr)
    return 0 if result["found"] else 1


if __name__ == "__main__":
    sys.exit(main())
