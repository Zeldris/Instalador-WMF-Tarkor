#!/usr/bin/env python3
# galivelop-workflow v0.2.0
"""The only reader of a project's .claude/gw.json (one fact, one place).

Validates the config against schema/gw.schema.json (a stdlib validator for the subset the schema uses) and fills the
defaults the schema declares. Shell scripts call the CLI; Python scripts import load().

  python3 config.py validate            # exit 0 if valid; errors on stderr, exit 2
  python3 config.py get KEY             # scalar: one line; list: one item per line; object: JSON
  python3 config.py get KEY --json      # always JSON
  python3 config.py root                # the project root it resolved
  python3 config.py --rev REV get KEY   # the config as commit REV has it (git show REV:.claude/gw.json), e.g. the
                                        # commit a hook is about to push; absent or invalid at REV -> exit 2

Project root: --root, else the git top level of this script's folder when that repo has .claude/gw.json (the copy
in a project lives in .claude/gw/scripts/), else the git top level of $CLAUDE_PROJECT_DIR, else of the current
directory. Fails closed: no config, invalid config or unknown key -> exit 2 with the command that fixes it.
Python 3.8+ (macOS ships 3.9).
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_REL = Path(".claude") / "gw.json"


class ConfigError(Exception):
    pass


def git_toplevel(path):
    try:
        out = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True).stdout.strip()
        return Path(out) if out else None
    except (OSError, subprocess.CalledProcessError):
        return None


def find_root(explicit=None):
    if explicit:
        root = git_toplevel(explicit)
        if root is None:
            raise ConfigError(f"{explicit} is not inside a git repository")
        return root
    own = git_toplevel(HERE)
    if own is not None and (own / CONFIG_REL).is_file():
        return own
    for candidate in (os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()):
        if candidate:
            root = git_toplevel(candidate)
            if root is not None:
                return root
    raise ConfigError("not inside a git repository; run from the project or pass --root <path>")


def schema_path():
    """The schema next to this script's workflow: <workflow>/schema/ or, in a project copy, .claude/gw/schema/."""
    for candidate in (HERE.parent / "schema" / "gw.schema.json", HERE / "gw.schema.json"):
        if candidate.is_file():
            return candidate
    raise ConfigError(f"gw.schema.json not found next to {HERE}; reinstall the workflow files")


TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int, "number": (int, float)}


def validate(value, schema, path="$"):
    """Return a list of 'path: problem' strings for the JSON Schema subset gw.schema.json uses."""
    errors = []
    expected = schema.get("type")
    if expected:
        ok = isinstance(value, TYPES[expected]) and not (expected in ("integer", "number") and isinstance(value, bool))
        if not ok:
            return [f"{path}: expected {expected}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']}, got {value!r}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: must not be empty")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: needs at least {schema['minItems']} item(s)")
        for i, item in enumerate(value):
            errors += validate(item, schema.get("items", {}), f"{path}[{i}]")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required key '{key}'")
        for key, item in value.items():
            if key in props:
                errors += validate(item, props[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unknown key '{key}' (check spelling; allowed: {', '.join(sorted(props))})")
    return errors


def with_defaults(config, schema):
    filled = dict(config)
    for key, prop in schema.get("properties", {}).items():
        if key not in filled and "default" in prop:
            filled[key] = prop["default"]
    return filled


def read_at(root, rev):
    """Text of .claude/gw.json in commit `rev`. Raises ConfigError when the commit or the file is not there."""
    try:
        r = subprocess.run(["git", "-C", str(root), "show", f"{rev}:{CONFIG_REL.as_posix()}"],
                           capture_output=True, text=True)
    except OSError as exc:
        raise ConfigError(f"cannot run git to read {CONFIG_REL} at {rev}: {exc}")
    if r.returncode != 0:
        raise ConfigError(f"{CONFIG_REL} is not in commit {rev} ({r.stderr.strip()[:200]}); commit a valid one: "
                          f"git add {CONFIG_REL.as_posix()} && git commit")
    return r.stdout


def load(root=None, rev=None):
    """Return the validated config with defaults, plus '_root' (Path). With `rev`, the config as that commit has it
    instead of the working tree's. Raises ConfigError."""
    root = find_root(root)
    path = root / CONFIG_REL
    if rev:
        text = read_at(root, rev)
        path = f"{rev}:{CONFIG_REL.as_posix()}"
    elif not path.is_file():
        raise ConfigError(f"{path} not found; apply the workflow first (see docs/en/apply.md) "
                          f"or create it from templates/gw.json")
    else:
        text = path.read_text(encoding="utf-8")
    try:
        config = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON at line {exc.lineno}: {exc.msg}")
    schema = json.loads(schema_path().read_text(encoding="utf-8"))
    errors = validate(config, schema)
    if errors:
        raise ConfigError(f"{path} is invalid:\n  " + "\n  ".join(errors))
    config = with_defaults(config, schema)
    config["_root"] = root
    return config


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="project path (default: see above)")
    parser.add_argument("--rev", help="read the config from this commit instead of the working tree")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("root")
    get = sub.add_parser("get")
    get.add_argument("key", help="top-level key, or dotted (relatedTests.fast)")
    get.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load(args.root, args.rev)
    except ConfigError as exc:
        print(f"gw config: {exc}", file=sys.stderr)
        return 2
    if args.command == "validate":
        print(f"{args.rev + ':' + CONFIG_REL.as_posix() if args.rev else config['_root'] / CONFIG_REL}: valid")
        return 0
    if args.command == "root":
        print(config["_root"])
        return 0
    value = config
    for part in args.key.split("."):
        if not isinstance(value, dict) or part not in value or part == "_root":
            print(f"gw config: key '{args.key}' is not set and has no default", file=sys.stderr)
            return 2
        value = value[part]
    if args.json or isinstance(value, dict):
        print(json.dumps(value, ensure_ascii=False))
    elif isinstance(value, list):
        for item in value:
            print(item if not isinstance(item, (dict, list)) else json.dumps(item, ensure_ascii=False))
    elif isinstance(value, bool):
        print("true" if value else "false")
    else:
        print(value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
