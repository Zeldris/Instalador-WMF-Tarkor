#!/usr/bin/env python3
# galivelop-workflow v0.3.0
"""Get back what a compaction or a /clear dropped, without reading the whole session transcript.

  recuperar.py --estado         what the SessionStart hook (clear|compact) puts back into the context: the log's
                                state (with logRows, the current branch's row; else the log's first section, ~25
                                lines), `git status --short` (15 lines at most), the last 5 commits, the compactions
                                in this session (WMF P10: compare them with the task's budget) and how to search the
                                transcript for a detail.
  recuperar.py --buscar TEXT    the transcript fragments (main conversation: user, Claude, tool calls and results)
                                matching TEXT (case-insensitive regex; plain text if it is not a valid regex), newest
                                last. --max N (10), --ancho N (300 characters per fragment).
  --sesion PATH                 the transcript to read (default: the hook's transcript_path on stdin, else the newest
                                one for the repo, see registro_sesion.py).

Fails open: --estado always exits 0 (a SessionStart hook cannot block; its stdout goes into the context). A new
session does not have the previous one's transcript: what must survive goes into the log.
Project root: config.find_root (the script's own repo when it holds .claude/gw.json, never the current directory
first). Python 3.8+ standard library only.
"""
import argparse
import json
import os
import re
import select
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, HERE)
import config  # noqa: E402
import registro_sesion  # noqa: E402

LOG_LINES = 25
STATUS_LINES = 15
# A call to this script's search (not a mention: a diff or a message that names it is still searched).
OWN_CALL = re.compile(r"recuperar\.py\s+(--sesion\s+\S+\s+)?--buscar")


def git(root, *args):
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    except OSError:
        return ""
    return r.stdout.rstrip("\n") if r.returncode == 0 else ""


def script_command(root):
    """How to call this script from the repo root: a relative path for a project copy, absolute from a plugin."""
    here = os.path.abspath(__file__)
    try:
        rel = os.path.relpath(here, str(root))
    except ValueError:
        rel = here
    return f"python3 {here if rel.startswith('..') else rel}"


# ---------------------------------------------------------------- transcript

def who(entry, text):
    """Text injected into a user turn (system reminders, hook output, slash commands) was not said by the user."""
    if entry.get("type") != "user":
        return "claude"
    return "system" if entry.get("isMeta") or text.lstrip().startswith("<") else "user"


def texts(entry):
    """(who, text) for each block of a transcript line."""
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        yield who(entry, content), content
        return
    for block in content or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            yield who(entry, block.get("text", "")), block.get("text", "")
        elif kind == "tool_use":
            yield f"tool {block.get('name', '?')}", json.dumps(block.get("input") or {}, ensure_ascii=False)
        elif kind == "tool_result":
            c = block.get("content")
            if isinstance(c, list):
                c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
            yield "result", c if isinstance(c, str) else ""


def entries(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                yield entry


def count_compactions(path):
    """Compaction boundaries in the transcript; if the format has none, compaction summaries instead."""
    boundaries = summaries = 0
    for entry in entries(path):
        if entry.get("subtype") == "compact_boundary" or entry.get("type") == "compact_boundary":
            boundaries += 1
        elif entry.get("isCompactSummary"):
            summaries += 1
    return boundaries or summaries


def search(path, pattern, maximum, width):
    try:
        rx = re.compile(pattern, re.I)
    except re.error:
        rx = re.compile(re.escape(pattern), re.I)
    found, own_ids = [], set()
    for entry in entries(path):
        if entry.get("isSidechain") or entry.get("isCompactSummary"):
            continue
        blocks = (entry.get("message") or {}).get("content")
        if isinstance(blocks, list):
            # Earlier searches with this script and their results would only repeat what was already found.
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "tool_use" and \
                        OWN_CALL.search(str((b.get("input") or {}).get("command", ""))):
                    own_ids.add(b.get("id"))
            if any(isinstance(b, dict) and (b.get("id") in own_ids or b.get("tool_use_id") in own_ids)
                   for b in blocks):
                continue
        for speaker, text in texts(entry):
            m = rx.search(text)
            if m:
                start = max(0, m.start() - width // 2)
                piece = re.sub(r"\s+", " ", text[start:start + width]).strip()
                tail = "…" if start + width < len(text) else ""
                found.append(f"[{(entry.get('timestamp') or '')[:16]}] {speaker}: {'…' if start else ''}{piece}{tail}")
    for line in found[-maximum:]:
        print(line)
    extra = f" (the last {maximum} shown; narrow it or raise --max)" if len(found) > maximum else ""
    print(f"{len(found)} fragment(s) match /{pattern}/{extra}")


# ---------------------------------------------------------------- state

def row_for_branch(text, branch):
    """The log table row for this branch ('… · `<branch>`' in its first cell): the rest of the row, trimmed."""
    marker = f"· `{branch}`"
    for line in text.splitlines():
        if line.lstrip().startswith("|") and marker in line:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            return " | ".join(c for c in cells[1:] if c) or "(empty row)"
    return None


def named_section(text, heading):
    """The '#'-heading section whose title is heading (case and trailing colon ignored), up to the next heading of the
    same or a higher level; None when the log has none."""
    lines = text.splitlines()
    want = heading.strip().rstrip(":").lower()
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*?)\s*:?\s*$", line)
        if m and m.group(2).lower() == want:
            level, out = len(m.group(1)), [line]
            for nxt in lines[i + 1:]:
                h = re.match(r"^(#{1,6})\s", nxt)
                if h and len(h.group(1)) <= level:
                    break
                out.append(nxt)
            while out and not out[-1].strip():
                out.pop()
            if len(out) > LOG_LINES:
                out = out[:LOG_LINES] + ["… (trimmed; the rest is in the log)"]
            return out
    return None


def first_section(text):
    """The log's first section (from the first '## ' heading or table to the next '## '), ~25 lines."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("## ") or l.lstrip().startswith("|")), None)
    if start is None:
        start = 1 if lines and lines[0].startswith("# ") else 0
    out = []
    for i, line in enumerate(lines[start:]):
        if i and line.startswith("## "):
            break
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    if len(out) > LOG_LINES:
        out = out[:LOG_LINES] + ["… (trimmed; the rest is in the log)"]
    return out


def log_state(root, branch):
    try:
        cfg = config.load(root)
    except config.ConfigError as exc:
        return [f"- Log: unknown ({str(exc).splitlines()[0]}); check it: python3 {HERE}/config.py validate"]
    log = root / cfg["log"]
    if not log.is_file():
        return [f"- Log: {cfg['log']} does not exist; create it from the workflow template (docs/en/apply.md)"]
    text = log.read_text(encoding="utf-8", errors="replace")
    if cfg.get("logRows"):
        row = row_for_branch(text, branch)
        if row is None:
            return [f"- Log ({cfg['log']}): no row for branch `{branch}`; add your '… · `{branch}`' row to the log"]
        return [f"- Log ({cfg['log']}), row for `{branch}`: {row}"]
    def indented(lines):
        return ["  " + l if l else "" for l in lines]
    wanted = cfg.get("logSections") or []
    if wanted:
        out = []
        for heading in wanted:
            section = named_section(text, heading)
            if section is None:
                out.append(f"- Log ({cfg['log']}): no section '{heading}' (logSections in .claude/gw.json); fix the "
                           f"heading or the key")
            else:
                out += [f"- Log ({cfg['log']}), section '{heading}':"] + indented(section)
        return out
    first = first_section(text)
    out = [f"- Log ({cfg['log']}), first section:"] + indented(first)
    for heading in ("Pendiente", "Pending"):
        section = named_section(text, heading)
        if section is not None and section[0] not in first:
            out += [f"- Log ({cfg['log']}), section '{heading}':"] + indented(section)
            break
    return out


def state(root, transcript):
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD") or "?"
    print(f"State after compaction or /clear (galivelop-workflow), branch {branch}:")
    for line in log_state(root, branch):
        print(line)
    status = git(root, "status", "--short").splitlines()
    if status:
        print(f"- Uncommitted: {len(status)} file(s)")
        for line in status[:STATUS_LINES]:
            print(f"  {line}")
        if len(status) > STATUS_LINES:
            print(f"  … and {len(status) - STATUS_LINES} more (git status --short)")
    else:
        print("- Uncommitted: nothing")
    commits = git(root, "log", "--format=%h %s", "-5").splitlines()
    print("- Last commits:" + ("" if commits else " none"))
    for line in commits:
        print(f"  {line}")
    path, own = registro_sesion.find(root, transcript, warn=False)
    if path and not own:
        print(f"- Warning: this transcript is in {os.path.basename(os.path.dirname(path))}, not the repo's folder: "
              f"the session was opened outside the repo; restart it from the repo: cd {root} && claude")
    if path:
        n = count_compactions(path)
        print(f"- Compactions in this session: {n} (compare with the task's compaction budget in the log)")
    else:
        print("- Compactions in this session: unknown (no session transcript found)")
    session = f" --sesion {path}" if path else ""
    print(f"- A detail from before (an error, a piece of code, what the user said): "
          f"{script_command(root)}{session} --buscar '<text>'; never read the transcript whole.")


def hook_transcript(wait=1.0):
    """The transcript_path Claude Code passes to a hook on stdin. Read only when data arrives within `wait` seconds:
    an agent's Bash tool or `cmd | recuperar.py` leaves stdin open with nothing on it, and --estado must not hang."""
    if sys.stdin is None or sys.stdin.isatty():
        return None
    try:
        ready, _, _ = select.select([sys.stdin], [], [], wait)
    except (OSError, ValueError, TypeError):  # no select on this stream (Windows pipes, a closed stdin)
        return None
    if not ready:
        return None
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError, OSError):
        return None
    return data.get("transcript_path") if isinstance(data, dict) else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--estado", action="store_true", help="print the state (SessionStart clear|compact)")
    mode.add_argument("--buscar", metavar="TEXT", help="search the session transcript")
    parser.add_argument("--sesion", metavar="PATH", help="transcript to read")
    parser.add_argument("--max", type=int, default=10)
    parser.add_argument("--ancho", type=int, default=300)
    parser.add_argument("--root", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.estado:
        try:
            root = config.find_root(args.root)
            state(root, args.sesion or hook_transcript())
        except BrokenPipeError:
            raise
        except Exception as exc:  # fail open: the hook must never break the session
            print(f"recuperar.py --estado could not finish ({exc}); run it by hand to see why: "
                  f"python3 {os.path.abspath(__file__)} --estado")
        return 0
    try:
        root = config.find_root(args.root)
    except config.ConfigError as exc:
        print(f"recuperar.py: {exc}", file=sys.stderr)
        return 2
    path, _ = registro_sesion.find(root, args.sesion)
    if not path:
        print("recuperar.py: no session transcript found for this repo; pass it: "
              f"python3 {os.path.abspath(__file__)} --sesion <path.jsonl> --buscar '<text>'", file=sys.stderr)
        return 1
    search(path, args.buscar, max(1, args.max), max(40, args.ancho))
    return 0


if __name__ == "__main__":
    try:
        code = main()
        sys.stdout.flush()
    except BrokenPipeError:  # `--estado | head`: the reader left; say nothing more and exit 0
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        code = 0
    sys.exit(code)
