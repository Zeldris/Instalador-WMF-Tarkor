#!/usr/bin/env python3
# galivelop-workflow v0.6.0
"""Which models the workflow may use: `models.disabled` in .claude/gw.json (B7).

  python3 models.py list                  # the disabled entries, one per line (nothing when none)
  python3 models.py check MODEL           # exit 1 and the entry that blocks MODEL; exit 0 when it is enabled
  python3 models.py disable MODEL [...]   # add entries to models.disabled (an entry already there is kept once)
  python3 models.py enable MODEL [...]    # remove entries; one that is not in the list -> exit 2, nothing written

An entry blocks a model when, compared in lower case and without a context suffix such as `[1m]`, it is the model
(`claude-opus-5-5`), a prefix of it followed by `-` (`claude-opus` blocks `claude-opus-5-5` and
`claude-opus-4-5-20251101`), or a family alias (`opus`, `sonnet`, `haiku`, `fable`) and the model is a `claude-<family>-`
id or that same alias. A full id never blocks an alias: `opus` resolves to whatever Claude Code calls the latest Opus,
so disabling `claude-opus-4-5` leaves `opus` free, and to block what the alias launches the entry is `opus`.

Who reads it: subagent-cap.py (PreToolUse on Agent/Task) denies a subagent whose model is blocked, and gw-selector and
gw-orchestrate-dealer never pick one. `disable` and `enable` rewrite .claude/gw.json (two-space JSON, key order kept)
and validate it, putting the old text back if the result is invalid; config-guard.py asks the user before an agent runs
them, as for any edit of that file. Project root and config: config.find_root and config.load. Fails closed: no
config or an invalid one -> exit 2 with the command that fixes it. Python 3.8+ standard library only.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, str(HERE))
import config  # noqa: E402

ALIASES = ("opus", "sonnet", "haiku", "fable")


def normalize(name):
    """`name` in lower case, without spaces around it or a trailing context suffix (`claude-opus-5-5[1m]`)."""
    return re.sub(r"\[[^\]]*\]$", "", name.strip().lower()).strip()


def family(model):
    """The family alias of a `claude-<family>-...` id, or the alias itself; None for anything else."""
    if model in ALIASES:
        return model
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
    args = parser.parse_args(argv)
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
