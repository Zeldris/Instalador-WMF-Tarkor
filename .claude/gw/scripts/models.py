#!/usr/bin/env python3
# galivelop-workflow v0.9.0
"""Which models the workflow may use: `models.disabled` in .claude/gw.json (B7).

  python3 models.py list                  # the disabled entries, one per line (nothing when none)
  python3 models.py check MODEL           # exit 1 and the entry that blocks MODEL; exit 0 when it is enabled
  python3 models.py disable MODEL [...]   # add entries to models.disabled (an entry already there is kept once)
  python3 models.py enable MODEL [...]    # remove entries; one that is not in the list -> exit 2, nothing written
  python3 models.py session-check --transcript PATH [--model MODEL]
                                          # D142: one warning line when the session model differs from the one the
                                          # last gw-selector line recommends; nothing otherwise (always exit 0)

An entry blocks a model when, compared in lower case and without a context suffix such as `[1m]`, it is the model
(`claude-opus-5-5`), a prefix of it followed by `-` (`claude-opus` blocks `claude-opus-5-5` and
`claude-opus-4-5-20251101`), or a family alias (`opus`, `sonnet`, `haiku`, `fable`) and the model is a `claude-<family>-`
id or that same alias. A full id never blocks an alias: `opus` resolves to whatever Claude Code calls the latest Opus,
so disabling `claude-opus-4-5` leaves `opus` free, and to block what the alias launches the entry is `opus`.

Who reads it: subagent-cap.py (PreToolUse on Agent/Task) denies a subagent whose model is blocked, and gw-selector and
gw-orchestrate-dealer never pick one. `disable` and `enable` rewrite .claude/gw.json (two-space JSON, key order kept)
and validate it, putting the old text back if the result is invalid; config-guard.py asks the user before an agent runs
them, as for any edit of that file. Project root and config: config.find_root and config.load. Fails closed: no
config or an invalid one -> exit 2 with the command that fixes it.

`session-check` (D142, called by session-start.sh with the hook's `transcript_path` and `model`) reads the last
subagentTranscriptBytes of the transcript (format internal to Claude Code: assistant rows carry `message.model` and text
blocks, as subagent-cap.py reads them). The recommendation is the last `Session: <model> <effort>` line an assistant text
block holds (the gw-selector line; `large`/`medium`/`light` stand for opus/sonnet/haiku, `X or Y` allows both); the
current model is `--model` (the hook's input), else the model of the last assistant message. It compares families only
(effort is not in the transcript). Known limit: only that tail is read, so on a long resumed session whose selector
line is older than the tail it prints a note that the check did not run (raising subagentTranscriptBytes reaches further back). Unknown or unreadable data, or `models.sessionCheck` false, prints nothing: a
SessionStart hook cannot block, and a wrong warning costs more than a missing one. Python 3.8+ standard library only.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, str(HERE))
import config  # noqa: E402

ALIASES = ("opus", "sonnet", "haiku", "fable")
SIZES = {"large": "opus", "medium": "sonnet", "light": "haiku"}  # the gw-selector table's words
# D142 review: the label also in Spanish, and a bullet, quote or backtick before it; or after a ' · ' separator mid-line (not in bare prose)
SESSION_LINE = re.compile(r"(?:^[\s>`*\-\u2022]*|\u00b7\s*)(?:Session|Sesi[o\u00f3]n):\W*([A-Za-z][\w.\-]*)(?:\s+or\s+([A-Za-z][\w.\-]*))?", re.MULTILINE)


def normalize(name):
    """`name` in lower case, without spaces around it or a trailing context suffix (`claude-opus-5-5[1m]`)."""
    return re.sub(r"\[[^\]]*\]$", "", name.strip().lower()).strip()


def family(model):
    """The family alias of a `claude-<family>-...` id, or the alias itself; None for anything else."""
    if model in ALIASES:
        return model
    match = re.match(r"([a-z]+)[\s-]", model)  # `opus-5.5`, `opus 5.5`
    if match and match.group(1) in ALIASES:
        return match.group(1)
    match = re.match(r"claude-([a-z]+)(-|$)", model)
    return match.group(1) if match and match.group(1) in ALIASES else None


def blocked_by(model, disabled):
    """The first entry of `disabled` that blocks `model`, or None (see the module docstring for the rule)."""
    m = normalize(model)
    if not m:
        return None
    for entry in disabled:
        if not isinstance(entry, str):
            continue
        e = normalize(entry)
        if e and (m == e or m.startswith(e + "-") or (e in ALIASES and family(m) == e)):
            return entry
    return None


def disabled(conf):
    """The `models.disabled` list of a loaded config ([] when the key or the list is missing)."""
    entries = config.models(conf)["disabled"]
    return [e for e in entries if isinstance(e, str)] if isinstance(entries, list) else []


def recommended_families(text):
    """The families the last line of `text` that starts with `Session: <model> ...` recommends (a set), or None when
    no such line names known models (a line with a word that is no model is skipped, an earlier one still counts)."""
    for match in reversed(SESSION_LINE.findall(text or "")):
        out = set()
        for word in (normalize(w) for w in match if w):
            fam = SIZES.get(word) or family(word)
            if fam is None:
                out = None
                break
            out.add(fam)
        if out:
            return out
    return None


def transcript_size(path):
    """The size in bytes of the transcript at `path` (0 when it cannot be read)."""
    try:
        return os.path.getsize(path)
    except (OSError, TypeError, ValueError):
        return 0


def transcript_tail(path, tail_bytes):
    """The JSON rows of the last `tail_bytes` of the transcript at `path` ([] when it cannot be read)."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - tail_bytes))
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
    except (OSError, TypeError, ValueError):
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue  # the first line of the tail may be cut
        if isinstance(row, dict):
            rows.append(row)
    return rows


def session_text_before_tail(path, tail_bytes, chunk=1 << 20):
    """True when the text `Session: ` appears before the last `tail_bytes` of the transcript: the evidence that a selector
    line exists but is out of reach. A resumed or compacted session that never had one has none (no note then)."""
    needle = b"Session: "
    try:
        with open(path, "rb") as fh:
            left = max(0, os.path.getsize(path) - tail_bytes)
            carry = b""
            while left > 0:
                data = fh.read(min(chunk, left))
                if not data:
                    break
                left -= len(data)
                if needle in carry + data:
                    return True
                carry = data[-(len(needle) - 1):]
    except (OSError, TypeError, ValueError):
        return False
    return False


def session_line_seen(rows):
    """True when a main-session assistant text in `rows` has a `Session: <model> ...` line naming known models."""
    for row in rows:
        message = row.get("message") if row.get("type") == "assistant" and not row.get("isSidechain") else None
        content = message.get("content") if isinstance(message, dict) else None
        texts = [b.get("text") for b in content if isinstance(b, dict) and b.get("type") == "text"] \
            if isinstance(content, list) else [content] if isinstance(content, str) else []
        if any(isinstance(t, str) and recommended_families(t) for t in texts):
            return True
    return False


def session_check(rows, hook_model=None):
    """The warning line when the session's model family is not one the last selector line recommends, else None."""
    recommended, current = None, normalize(hook_model) if isinstance(hook_model, str) else ""
    for row in reversed(rows):
        if row.get("isSidechain"):
            continue  # a subagent's row: neither its model nor its text is the session's
        message = row.get("message") if row.get("type") == "assistant" else None
        if not isinstance(message, dict):
            continue
        model = message.get("model")
        if not current and isinstance(model, str) and model.strip() and not model.startswith("<"):
            current = normalize(model)
        content = message.get("content")
        texts = [b.get("text") for b in content if isinstance(b, dict) and b.get("type") == "text"] \
            if isinstance(content, list) else [content] if isinstance(content, str) else []
        if recommended is None:
            for text in reversed([t for t in texts if isinstance(t, str)]):
                recommended = recommended_families(text)
                if recommended:
                    break
        if current and recommended is not None:
            break
    fam = family(current) if current else None
    if not recommended or fam is None or fam in recommended:
        return None
    wanted = " or ".join(sorted(recommended))
    return (f"the last gw-selector line recommends {wanted} for this session, but it runs on {current}; stop and ask the "
            f"user to switch (/model {sorted(recommended)[0]}, and /effort as the line says) before working, or say "
            f"why it stays (turn this off: models.sessionCheck false in .claude/gw.json)")


def write(root, entries):
    """Set models.disabled to `entries` in root/.claude/gw.json and validate it; on an invalid result the old text is
    put back and ConfigError raised."""
    path = Path(root) / config.CONFIG_REL
    old = path.read_text(encoding="utf-8")
    raw = json.loads(old)
    models = raw.get("models") if isinstance(raw.get("models"), dict) else {}
    models["disabled"] = entries
    raw["models"] = models
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        config.load(root)
    except config.ConfigError:
        path.write_text(old, encoding="utf-8")
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="project path (default: config.find_root)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    check = sub.add_parser("check")
    check.add_argument("model")
    for name in ("disable", "enable"):
        sub.add_parser(name).add_argument("model", nargs="+")
    sc = sub.add_parser("session-check", help="D142: warn when the session model differs from the selector's")
    sc.add_argument("--transcript", default="", help="the hook's transcript_path")
    sc.add_argument("--model", default="", help="the hook's model, when it gives one")
    args = parser.parse_args(argv)
    if args.command == "session-check":
        try:
            conf = config.load(args.root)
        except config.ConfigError:
            return 0  # session-start.sh already warns about a broken config
        if config.models(conf).get("sessionCheck") is False or not args.transcript:
            return 0
        tail = config.subagent_settings(conf["_root"])["subagentTranscriptBytes"]
        rows = transcript_tail(args.transcript, tail)
        line = session_check(rows, args.model or None)
        if line:
            print(line)
        elif not session_line_seen(rows) and transcript_size(args.transcript) > tail \
                and session_text_before_tail(args.transcript, tail):
            # D142: the selector line may be older than the tail; say the check did not run rather than stay silent
            print(f"gw models: the session model check did not run: no `Session:` line in the last {tail} bytes of a "
                  f"longer transcript; raise subagentTranscriptBytes in .claude/gw.json to look further back, or "
                  f"turn this off with models.sessionCheck false")
        return 0
    try:
        conf = config.load(args.root)
    except config.ConfigError as exc:
        print(f"gw models: {exc}", file=sys.stderr)
        return 2
    root, entries = conf["_root"], disabled(conf)
    if args.command == "list":
        for entry in entries:
            print(entry)
        return 0
    if args.command == "check":
        entry = blocked_by(args.model, entries)
        if entry is None:
            print(f"{args.model}: enabled")
            return 0
        print(f"{args.model}: disabled by `{entry}` in models.disabled (re-enable: python3 {Path(__file__).name} "
              f"enable {entry})")
        return 1
    wanted = [normalize(m) for m in args.model]
    if any(not m for m in wanted):
        print("gw models: an empty model name; give an id (claude-opus-5-5), a prefix or an alias (opus)",
              file=sys.stderr)
        return 2
    if args.command == "disable":
        new = list(entries)
        for model in wanted:
            if model not in (normalize(e) for e in new):
                new.append(model)
    else:
        missing = [m for m in wanted if m not in (normalize(e) for e in entries)]
        if missing:
            print(f"gw models: {', '.join(missing)} not in models.disabled (it holds: "
                  f"{', '.join(entries) or 'nothing'}); run: python3 {Path(__file__).name} list", file=sys.stderr)
            return 2
        new = [e for e in entries if normalize(e) not in wanted]
    try:
        write(root, new)
    except (OSError, ValueError, config.ConfigError) as exc:
        print(f"gw models: .claude/gw.json was not changed ({exc}); fix it, then: python3 config.py validate",
              file=sys.stderr)
        return 2
    print(f"models.disabled: {', '.join(new) or '(empty)'}")
    if args.command == "enable":
        for model in wanted:
            entry = blocked_by(model, new)
            if entry is not None:
                print(f"note: {model} is still blocked by `{entry}`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
