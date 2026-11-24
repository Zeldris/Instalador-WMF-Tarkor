#!/usr/bin/env python3
# galivelop-workflow v0.9.0
"""One switch for the workflow's modes: the `modes` section of .claude/gw.json (C6, C7).

  python3 mode.py list                 # each mode with its value and what it does; then the list settings, read-only
  python3 mode.py line                 # one line for SessionStart: "Modes: careful on, questions restrictive"
  python3 mode.py set MODE on|off      # write the mode into .claude/gw.json (also true|false|1|0|yes|no)

The modes it knows are the boolean keys of `modes` (careful, questions); the list keys (carefulExempt,
carefulWorktrees) are shown by `list` and edited by hand. `set` edits .claude/gw.json in place: only the text of that
one value changes (EOL, tabs, compact sections and key order stay; a missing key or `modes` section is added), through
a temp file and os.replace, and the result is validated, putting the old text back if it is invalid. config-guard.py
asks the user before an agent runs `mode.py set`, as for any edit of that file. Project root and config: config.find_root and
config.load. Fails closed: no config, an invalid one or an unknown mode -> exit 2 with the command that fixes it.
Python 3.8+ standard library only.
"""
import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, str(HERE))
import config  # noqa: E402

# mode -> (label when true, label when false, meaning)
MODES = {
    "careful": ("on", "off", "careful.py asks before a destructive command (rm -r, git push --force, git reset --hard)"),
    "questions": ("restrictive", "guide", "questions-guard.py (C4, C5): restrictive = the guard blocks, guide = it only advises"),
}
TRUE_WORDS = ("on", "true", "1", "yes")
FALSE_WORDS = ("off", "false", "0", "no")


def label(mode, value):
    """How a mode's value reads: `on`/`off`, or its own words (questions: restrictive/guide)."""
    on, off, _ = MODES.get(mode, ("on", "off", ""))
    return on if value else off


def boolean_modes(conf):
    """The boolean keys of the loaded config's `modes`, in config order, with their values."""
    return {k: v for k, v in config.modes(conf).items() if isinstance(v, bool)}


_WS = re.compile(r"[ \t\r\n]*")
_DECODER = json.JSONDecoder()


def members(text, start):
    """The members of the JSON object whose `{` is at text[start]: (key, key_start, value_start, value_end) each, and
    the index of its closing `}`. Raises ValueError when it is not an object."""
    if text[start] != "{":
        raise ValueError("not an object")
    out, i = [], _WS.match(text, start + 1).end()
    while text[i] != "}":
        key, key_end = _DECODER.raw_decode(text, i)
        colon = _WS.match(text, key_end).end()
        if text[colon] != ":":
            raise ValueError("no colon after a key")
        value_start = _WS.match(text, colon + 1).end()
        _, value_end = _DECODER.raw_decode(text, value_start)
        out.append((key, i, value_start, value_end))
        i = _WS.match(text, value_end).end()
        if text[i] == ",":
            i = _WS.match(text, i + 1).end()
    return out, i


def lead_of(text, key_start):
    """The whitespace (newline and indent, or a space) just before a key: reused for a member added after it."""
    return re.search(r"[ \t\r\n]*\Z", text[:key_start]).group(0) or " "


def edit_text(text, mode, value):
    """`text` (a gw.json) with modes.<mode> set to `value`, changing only that value's text: a member is added after
    the last one with the same indent and line ending when it is missing, and `modes` itself when that is missing.
    Everything else (EOL, tabs, compact sections, key order) stays byte for byte."""
    word = json.dumps(value)
    top_start = _WS.match(text, 0).end()
    top, top_end = members(text, top_start)
    section = [m for m in top if m[0] == "modes"]
    if section:
        _, _, v_start, v_end = section[0]
        inner, inner_end = members(text, v_start)
        found = [m for m in inner if m[0] == mode]
        if found:
            return text[:found[0][2]] + word + text[found[0][3]:]
        if inner:
            last = inner[-1]
            return text[:last[3]] + "," + lead_of(text, last[1]) + json.dumps(mode) + ": " + word + text[last[3]:]
        return text[:v_start] + "{" + json.dumps(mode) + ": " + word + "}" + text[v_end:]
    member = json.dumps("modes") + ": {" + json.dumps(mode) + ": " + word + "}"
    if top:
        last = top[-1]
        return text[:last[3]] + "," + lead_of(text, last[1]) + member + text[last[3]:]
    return text[:top_start] + "{" + member + "}" + text[top_end + 1:]


def write(root, mode, value):
    """Set modes.<mode> to `value` in root/.claude/gw.json, changing only that value's text, and validate it; the file
    is replaced atomically (temp file + os.replace), so a failure leaves the old one; on an invalid result the old
    text is put back and ConfigError raised."""
    path = Path(root) / config.CONFIG_REL
    old = path.read_bytes().decode("utf-8")
    raw = json.loads(old)
    expected = dict(raw, modes=dict(raw["modes"] if isinstance(raw.get("modes"), dict) else {}, **{mode: value}))
    new = edit_text(old, mode, value)
    if json.loads(new) != expected:
        raise ValueError("the edit would change more than modes." + mode)
    replace(path, new)
    try:
        config.load(root)
    except config.ConfigError:
        replace(path, old)
        raise


def replace(path, text):
    """Write `text` (bytes as given, no newline translation) to `path` through a temp file in the same folder."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(text.encode("utf-8"))
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True) if sys.version_info >= (3, 8) else None
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="project path (default: config.find_root)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("line")
    setter = sub.add_parser("set")
    setter.add_argument("mode")
    setter.add_argument("value")
    args = parser.parse_args(argv)
    name = Path(__file__).name
    try:
        conf = config.load(args.root)
    except config.ConfigError as exc:
        print(f"gw mode: {exc}; fix .claude/gw.json, then: python3 {name} list", file=sys.stderr)
        return 2
    bools = boolean_modes(conf)
    if args.command == "line":
        print("Modes: " + ", ".join(f"{k} {label(k, v)}" for k, v in bools.items()))
        return 0
    if args.command == "list":
        for k, v in bools.items():
            print(f"{k}: {label(k, v)} ({'true' if v else 'false'}) - {MODES.get(k, ('', '', 'no description'))[2]}")
        for k, v in config.modes(conf).items():
            if isinstance(v, list):
                print(f"{k}: {json.dumps(v)} - list setting, read-only here; edit modes.{k} in .claude/gw.json")
        return 0
    if args.mode not in bools:
        print(f"gw mode: unknown mode `{args.mode}` (known: {', '.join(bools) or 'none'}); run: python3 {name} list",
              file=sys.stderr)
        return 2
    word = args.value.strip().lower()
    if word not in TRUE_WORDS + FALSE_WORDS:
        print(f"gw mode: `{args.value}` is not on or off; run: python3 {name} set {args.mode} on|off", file=sys.stderr)
        return 2
    value = word in TRUE_WORDS
    try:
        write(conf["_root"], args.mode, value)
    except (OSError, ValueError, config.ConfigError) as exc:
        print(f"gw mode: .claude/gw.json was not changed ({exc}); fix it, then: python3 config.py validate",
              file=sys.stderr)
        return 2
    print(f"modes.{args.mode}: {label(args.mode, value)} ({'true' if value else 'false'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
