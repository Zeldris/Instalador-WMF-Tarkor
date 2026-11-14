#!/usr/bin/env python3
# galivelop-workflow v0.6.0
"""PreToolUse hook on `Read` (B26): warn when a session reads WHOLE a watched file that is larger than
`wholeReadWarnBytes` in .claude/gw.json. It never blocks: it adds `additionalContext` to the call, so the next steps
read less; with no warning it prints nothing (no opinion).

Watched files: the hand-off log (`log`), its archive (`logArchive`) and every file directly or deeper under
`recordsDir`; only text files (not images, PDF or notebooks). A Read is "whole" when `tool_input` has no `offset`,
`limit` or `pages` (a null, 0 or empty value counts as absent). The log is compared in characters (as `logSize`
is), the records in bytes. A watched file of more than `wholeReadWarnBytes` bytes (default 20000; 0 turns the hook off) gets a note
that names the size and the commands that read less:

  hand-off log   python3 .claude/gw/scripts/recover.py --state (the state), or grep -n for a row and Read with
                 offset and limit
  a record       Read with offset and limit, or grep -n for the heading first

Output format (https://code.claude.com/docs/en/hooks.md, PreToolUse): a JSON object on stdout, exit 0,

  {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "..."}}

Fails open, because it only advises: stdin it cannot read, an event that is not a Read, a path outside the project, a
file it cannot stat or a config it cannot read (the defaults apply to the config) print nothing and exit 0. The
project root is config.find_root (the script's own repo, never the current directory first); a relative path is
resolved against the event's `cwd`. Python 3.8+ standard library only.
"""
import json
import os
import select
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, HERE)
import config  # noqa: E402



def read_event():
    if sys.stdin is None or sys.stdin.isatty():
        return None
    try:
        ready, _, _ = select.select([sys.stdin], [], [], config.hook_stdin_wait())
        if not ready:
            return None
        data = json.loads(sys.stdin.read())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def settings(root):
    """(threshold, log, archive, records, skip, extra) from the config; the schema defaults when it cannot be read
    (`log` has none there: docs/handoff.md). `skip`: wholeReadSkipExtensions as a lower-case tuple; `extra`:
    wholeReadPaths (repo-relative files, or folders ending in /)."""
    try:
        cfg = config.load(root)
    except Exception:  # advice only: any problem with the config means the defaults
        cfg = {}
    props = config._schema()["properties"]

    def pick(key, fallback=None):
        value = cfg.get(key)
        if isinstance(value, str) and value:
            return value
        return props[key].get("default", fallback)

    def pick_list(key):
        value = cfg.get(key)
        ok = isinstance(value, list) and all(isinstance(v, str) and v for v in value)
        return list(value) if ok else list(props[key]["default"])

    return (config.whole_read_warn_bytes(cfg), pick("log", "docs/handoff.md"), pick("logArchive"), pick("recordsDir"),
            tuple(e.lower() for e in pick_list("wholeReadSkipExtensions")), pick_list("wholeReadPaths"))


def is_whole(tool_input):
    return not (tool_input.get("offset") or tool_input.get("limit") or tool_input.get("pages"))


def kind_of(path, root, log, archive, records, extra=()):
    """'log' for the hand-off log or its archive, 'record' for a file under recordsDir or one of `extra`
    (wholeReadPaths: a file, or a folder ending in /), else None."""
    real = os.path.realpath(path)
    for rel in (log, archive):
        if real == os.path.realpath(os.path.join(root, rel)):
            return "log"
    folder = os.path.realpath(os.path.join(root, records))
    if real.startswith(folder + os.sep):
        return "record"
    for rel in extra:
        target = os.path.realpath(os.path.join(root, rel))
        if real == target or (rel.endswith("/") and real.startswith(target + os.sep)):
            return "record"
    return None


def note(kind, rel, size, limit):
    head = (f"{rel} is {size} bytes (wholeReadWarnBytes {limit} in .claude/gw.json) and this Read takes it whole, "
            f"which costs tokens on every turn it stays in the context. ")
    if kind == "log":
        return head + ("Next time: `python3 .claude/gw/scripts/recover.py --state` for the state, "
                       "or grep -n for the row you need and Read with offset and limit.")
    return head + "Next time: grep -n for the heading you need, then Read with offset and limit."


def main():
    event = read_event()
    if not event or event.get("tool_name") != "Read":
        return 0
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict) or not is_whole(tool_input):
        return 0
    target = tool_input.get("file_path")
    if not isinstance(target, str) or not target:
        return 0
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) and event.get("cwd") else os.getcwd()
    path = target if os.path.isabs(target) else os.path.join(cwd, target)
    try:
        info = os.stat(path)
        root = config.find_root()
    except Exception:
        return 0
    if not stat.S_ISREG(info.st_mode):
        return 0
    size = info.st_size
    limit, log, archive, records, skip, extra = settings(root)
    if limit <= 0 or size <= limit or path.lower().endswith(skip):
        return 0
    kind = kind_of(path, str(root), log, archive, records, extra)
    if kind is None:
        return 0
    if kind == "log":  # logSize counts characters: a log of accents that passes logSize must not warn here
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                if len(handle.read()) <= limit:
                    return 0
        except OSError:
            return 0
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(str(root)))
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "additionalContext": note(kind, rel, size, limit)}}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # advice only: never stop a Read
        sys.exit(0)
