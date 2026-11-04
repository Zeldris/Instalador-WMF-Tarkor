#!/usr/bin/env python3
# galivelop-workflow v0.5.0
"""The only reader of a project's .claude/gw.json (one fact, one place).

Validates the config against schema/gw.schema.json (a stdlib validator for the subset the schema uses) and fills the
defaults the schema declares. Shell scripts call the CLI; Python scripts import load().

  python3 config.py validate            # exit 0 if valid; errors on stderr, exit 2
  python3 config.py get KEY             # scalar: one line; list: one item per line; object: JSON
  python3 config.py get KEY --json      # always JSON
  python3 config.py root                # the project root it resolved
  python3 config.py related --kind fast|slow [--deleted-file F]   # relatedTests commands to run, NUL-terminated, ready for `bash -c`
                                        # (reads the changed files that exist, one per line, on stdin)
  python3 config.py --rev REV get KEY   # the config as commit REV has it (git show REV:.claude/gw.json), e.g. the
                                        # commit a hook is about to push; absent or invalid at REV -> exit 2
  python3 config.py local               # the validated local file .claude/gw.local.json as JSON (`null` when absent);
                                        # malformed -> exit 2. Never committed: it holds what must not be public
                                        # (privateNames, plus allowEmails for private-check.py and anonymize, the
                                        # aliases harvest.py prints instead of the names)

Project root: --root, else the git top level of this script's folder when that repo has .claude/gw.json (the copy
in a project lives in .claude/gw/scripts/), else the git top level of the current directory when it is
$CLAUDE_PROJECT_DIR's repo (the same checkout or a linked worktree of it, where $CLAUDE_PROJECT_DIR names the main
checkout), else of $CLAUDE_PROJECT_DIR (a plugin hook run from a sibling repo or from outside any repo), else of the
current directory. GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE are
ignored: git exports them to hooks, and with GIT_DIR set `rev-parse --show-toplevel` answers the folder it is
given, not the repo's. Fails closed: no config, invalid config or unknown key -> exit 2 with the command that fixes it.
Python 3.8+ (macOS ships 3.9).
"""
import argparse
import json
import os
import posixpath
import re
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_REL = Path(".claude") / "gw.json"
# The person's own file, never committed (.gitignore, and the pre-commit hook refuses it): what must not be public.
LOCAL_REL = Path(".claude") / "gw.local.json"
LOCAL_KEYS = {"privateNames": "names that must never reach the repo (private repos, people, places)",
              "allowEmails": "e-mail addresses private-check.py lets through, on top of privateCheck.allowEmails",
              "anonymize": "private name (any spelling) -> the public alias harvest.py prints instead, "
                           "private-project-N; its names count as privateNames too"}
ALIAS = re.compile(r"^private-project-\d+$")

# The format of gw.json (its `schemaVersion`; absent = 0, written before 0.5). load() migrates an older config in
# memory, so every reader sees the current shape; apply.py (/gw-update) writes the migration to disk. A newer one
# fails closed: this copy of the workflow cannot know what changed.
SCHEMA_VERSION = 1


class ConfigError(Exception):
    pass


def _migrate_to_1(raw):
    """0 -> 1: only the `schemaVersion` key, written right after `version` (the old Spanish paths of A8 have their
    own mechanism: LEGACY_PATHS here and plan_paths in apply.py)."""
    out = {}
    for key, value in raw.items():
        if key != "schemaVersion":
            out[key] = value
        if key == "version":
            out["schemaVersion"] = 1
    out["schemaVersion"] = 1
    return out


# (target schemaVersion, what it changes in one line, function(raw dict) -> raw dict), in order.
MIGRATIONS = [
    (1, "schemaVersion written (the format is versioned from now on)", _migrate_to_1),
]


def schema_version(raw, where=CONFIG_REL):
    """The `schemaVersion` of the raw config `raw` (0 when absent). Raises ConfigError, failing closed, when it is not
    a non-negative integer or is newer than this copy of the workflow knows (SCHEMA_VERSION)."""
    found = raw.get("schemaVersion", 0) if isinstance(raw, dict) else 0
    if isinstance(found, bool) or not isinstance(found, int) or found < 0:
        raise ConfigError(f"{where}: schemaVersion must be a non-negative integer, got {found!r}; fix it (the "
                          f"current format is {SCHEMA_VERSION}) and validate: python3 {HERE / 'config.py'} validate")
    if found > SCHEMA_VERSION:
        raise ConfigError(f"{where}: schemaVersion {found} is newer than this copy of the workflow knows "
                          f"({SCHEMA_VERSION}); update the workflow (in the project: /gw-update; the workflow's clone: "
                          f"git -C <workflow> fetch origin tag vX.Y.Z, then checkout vX.Y.Z) and apply it again")
    return found


def migrate(raw):
    """(a migrated copy of the raw config `raw`, [the one-line description of each migration applied]). `raw` is not
    changed. Raises ConfigError like schema_version()."""
    found = schema_version(raw)
    out = json.loads(json.dumps(raw))
    done = []
    for target, description, step in MIGRATIONS:
        if target > found:
            out = step(out)
            done.append(description)
    return out, done


def git_toplevel(path):
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    try:
        out = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True, env=env).stdout.strip()
        return Path(out) if out else None
    except (OSError, subprocess.CalledProcessError):
        return None


def git_common_dir(root):
    """The repository a checkout belongs to (shared by the main checkout and its linked worktrees), or None."""
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-common-dir"],
                             capture_output=True, text=True, check=True, env=env).stdout.strip()
        return (Path(root) / out).resolve() if out else None  # relative to `root` when git prints it relative
    except (OSError, subprocess.CalledProcessError):
        return None


def non_capturing(pattern):
    """`pattern` with every capturing group made non-capturing: `(A|B)-\\d+` -> `(?:A|B)-\\d+`, so re.findall of a
    task id (taskId) returns whole matches and not the groups. Escaped parentheses, `[...]` classes and `(?...)`
    constructs are left alone; a named group `(?P<n>` becomes `(?:`. Raises ConfigError on a back-reference, which
    cannot survive the change."""
    out, i, n, in_class = [], 0, len(pattern), False
    backref = f"the pattern {pattern!r} uses a back-reference; write it without capturing groups"
    while i < n:
        c = pattern[i]
        if c == "\\" and i + 1 < n:
            if not in_class and pattern[i + 1] in "123456789":
                raise ConfigError(backref)
            out.append(pattern[i:i + 2])
            i += 2
            continue
        if in_class:
            in_class = c != "]"
        elif c == "[":
            in_class = True
            out.append(c)
            i += 1
            if pattern[i:i + 1] == "^":
                out.append("^")
                i += 1
            if pattern[i:i + 1] == "]":  # a leading ] is a literal
                out.append("]")
                i += 1
            continue
        elif c == "(":
            if pattern.startswith("(?P=", i):
                raise ConfigError(backref)
            named = re.match(r"\(\?P<[^>]*>", pattern[i:])
            if named:
                out.append("(?:")
                i += named.end()
                continue
            if pattern[i + 1:i + 2] != "?":
                out.append("(?:")
                i += 1
                continue
        out.append(c)
        i += 1
    return "".join(out)


def find_root(explicit=None):
    if explicit:
        root = git_toplevel(explicit)
        if root is None:
            raise ConfigError(f"{explicit} is not inside a git repository")
        return root
    own = git_toplevel(HERE)
    if own is not None and (own / CONFIG_REL).is_file():
        return own
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    project = git_toplevel(project_dir) if project_dir else None
    cwd_root = git_toplevel(os.getcwd())
    if project is not None and cwd_root is not None and git_common_dir(project) != git_common_dir(cwd_root):
        return project  # the current directory is another repo (a sibling, a cloned dependency): not the project
    root = cwd_root or project
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
    if "anyOf" in schema:
        tried = [validate(value, option, path) for option in schema["anyOf"]]
        if all(tried):
            return [f"{path}: matches none of the allowed forms: " + " | ".join("; ".join(t) for t in tried)]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']}, got {value!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value < schema.get("minimum", value):
        errors.append(f"{path}: must be at least {schema['minimum']}, got {value!r}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: must not be empty")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: needs at least {schema['minItems']} item(s)")
        if schema.get("uniqueItems"):
            seen = set()
            for i, item in enumerate(value):
                key = json.dumps(item, sort_keys=True)
                if key in seen:
                    errors.append(f"{path}[{i}]: duplicate of an earlier item ({item!r})")
                seen.add(key)
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
            elif isinstance(schema.get("additionalProperties"), dict):
                errors += validate(item, schema["additionalProperties"], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unknown key '{key}' (check spelling; allowed: {', '.join(sorted(props))})")
    return errors


def instruction_lines(config):
    """The `instructionLines` key as (warn, fail): the line limits of AGENTS.md/CLAUDE.md, each missing part filled
    from the schema default (the only place the defaults live)."""
    schema = json.loads(schema_path().read_text(encoding="utf-8"))
    prop = schema["properties"]["instructionLines"]
    given = config.get("instructionLines")
    given = given if isinstance(given, dict) else {}
    return tuple(given.get(k, prop["properties"][k]["default"]) for k in ("warn", "fail"))


def semantic_errors(config):
    """Problems the schema subset cannot express: a relatedTests `paths` that is not a valid regex, an agentMap
    prefix that is not one folder name, an instructionLines `warn` above its `fail`."""
    errors = []
    warn, fail = instruction_lines(config)
    if warn > fail:
        errors.append(f"$.instructionLines: warn ({warn}) must not be above fail ({fail}); lower warn or raise fail "
                      "in .claude/gw.json")
    agent_map = config.get("agentMap")
    if isinstance(agent_map, dict) and isinstance(agent_map.get("prefixes"), dict):
        for short in agent_map["prefixes"]:
            if not re.fullmatch(r"[^/\s]+/?", short) or short in (".", "..", "./", "../"):
                errors.append(f"$.agentMap.prefixes: key {short!r} must be one folder-like name, with or without a "
                              f"trailing '/' (e.g. \"b/\")")
    related = config.get("relatedTests")
    if isinstance(related, dict):
        for kind in ("fast", "slow"):
            for i, entry in enumerate(related.get(kind) or []):
                if isinstance(entry, dict) and isinstance(entry.get("paths"), str):
                    try:
                        re.compile(entry["paths"])
                    except re.error as exc:
                        errors.append(f"$.relatedTests.{kind}[{i}].paths: {entry['paths']!r} is not a valid regex ({exc})")
    return errors


# Paths the workflow creates in a project. Until 1.0 a project that still has the old Spanish name and has not
# moved yet keeps working: an ABSENT key whose English default does not exist but whose old path does gets the old path.
LEGACY_PATHS = {
    "log": "docs/traspaso.md",
    "reviewMark": "docs/registros/revisado.txt",
    "ciLocalLog": "docs/registros/ci-local.md",
    "recordsDir": "docs/registros",
    "proposalsDir": "docs/propuestas",
}


def _same_path(a, b):
    """Whether two repo-relative paths name the same place (`./x`, `x/` and `x` do)."""
    return posixpath.normpath(a.strip()) == posixpath.normpath(b.strip())


def with_defaults(config, schema, exists=None, follow_moves=False):
    """`config` plus the schema defaults. `exists(path)` says whether a repo-relative path exists (None: no fallback
    to the old Spanish names). The keys filled from an old path are listed in filled["_legacy"] ({key: old path}).
    `follow_moves` (a policy config read for another commit, load's paths_at): a key set explicitly to its old Spanish
    path that this commit no longer has, while it has the English default, gets the default. That is the push that
    applies the A8 move (apply.py moves the file and drops the key), judged by a protected branch that still names the
    old path; keepLegacyPaths turns it off."""
    filled = dict(config)
    legacy = {}
    for key, prop in schema.get("properties", {}).items():
        old = LEGACY_PATHS.get(key)
        if (follow_moves and old and exists is not None and isinstance(filled.get(key), str)
                and _same_path(filled[key], old) and "default" in prop and not filled.get("keepLegacyPaths")
                and not exists(filled[key]) and exists(prop["default"])):
            filled[key] = prop["default"]
            continue
        if key not in filled and "default" in prop:
            value = prop["default"]
            if old and exists is not None and not exists(value) and exists(old):
                value = legacy[key] = old
            filled[key] = value
    if legacy:
        filled["_legacy"] = legacy
    return filled


def legacy_flags(argv, renames, prog):
    """`argv` with the old Spanish option names turned into the English ones (A8, 0.x). `renames` maps old -> new
    (`--old` and `--old=value` both count; nothing after a bare `--`). Each old name used is warned once on stderr
    with the name that replaces it. The old names go away in 1.0."""
    out, seen, literal = [], set(), False
    for arg in argv:
        if arg == "--":
            literal = True
        name = arg.split("=", 1)[0]
        if not literal and name in renames:
            if name not in seen:
                seen.add(name)
                print(f"{prog}: warning: {name} is deprecated and will stop working in 1.0; use {renames[name]}",
                      file=sys.stderr)
            arg = renames[name] + arg[len(name):]
        out.append(arg)
    return out


def legacy_env(new, old, prog, default=None):
    """The value of the environment variable `new`, else that of `old` (warned on stderr), else `default`."""
    if os.environ.get(new) is not None:
        return os.environ[new]
    if os.environ.get(old) is not None:
        print(f"{prog}: warning: the environment variable {old} is deprecated and will stop working in 1.0; "
              f"use {new}", file=sys.stderr)
        return os.environ[old]
    return default


def path_exists_fn(root, rev=None):
    """exists(path) for with_defaults: in the working tree, or in commit `rev` (a push checks the pushed commit)."""
    root = Path(root)
    if not rev:
        # A folder counts only with some file in it: git does not version empty folders, so the tree and a commit agree.
        return lambda rel: (root / rel).is_file() or ((root / rel).is_dir() and any((root / rel).iterdir()))
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}

    def exists(rel):
        try:
            return subprocess.run(["git", "-C", str(root), "cat-file", "-e", f"{rev}:{rel}"],
                                  capture_output=True, env=env).returncode == 0
        except OSError:
            return False
    return exists


def stale_refs(config):
    """(patterns, skip) of the `staleRefs` key, whichever form it has: a list of regexes (skip empty) or
    {"patterns": [...], "skip": [globs]} (both optional)."""
    value = config.get("staleRefs") or []
    if isinstance(value, dict):
        return list(value.get("patterns") or []), list(value.get("skip") or [])
    return list(value), []


def glob_regex(glob):
    """Compile a repo-relative glob to a regex. Only `*`, `**` and `?` are special (no brackets, no gitignore rules):
    `*` and `?` stay inside one folder, `**` crosses folders (`**/` also matches no folder), a leading `./` or `/` is
    dropped. An entry without metacharacters (`docs/records`, with or without a trailing `/`) matches that file or
    that folder and everything under it; a trailing `/` after metacharacters, or `/**`, also matches the folder."""
    glob = glob[2:] if glob.startswith("./") else glob
    glob = glob.lstrip("/")
    if glob.endswith("/"):
        glob = glob.rstrip("/")
        glob += "/**" if re.search(r"[*?]", glob) else ""
    if not re.search(r"[*?]", glob):
        return re.compile(re.escape(glob) + r"(?:/.*)?\Z")
    out, i = [], 0
    while i < len(glob):
        c = glob[i]
        if glob.startswith("/**", i) and i + 3 == len(glob):
            out.append("(?:/.*)?")
            i += 3
        elif glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("".join(out) + r"\Z")


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


def _commit(root, rev):
    """The full sha `rev` names in `root` ("" when it names none)."""
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    try:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "-q", f"{rev}^{{commit}}"],
                           capture_output=True, text=True, env=env)
    except OSError:
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def load(root=None, rev=None, paths_at=None):
    """Return the validated config with defaults, plus '_root' (Path) and '_schemaFrom' (the schemaVersion it had
    before load() migrated it in memory to SCHEMA_VERSION; an absent one is 0, a newer one fails closed). With `rev`,
    the config as that commit has it instead of the working tree's. `paths_at` (a commit) is where the old-Spanish-path fallback looks for files: a
    policy config read from the protected branch's tip still resolves the paths of the commit being pushed or
    merged, so every reader gets the same path for the same commit; an old path the tip names explicitly follows
    that commit's move to the English default (with_defaults, follow_moves). Raises ConfigError."""
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
    schema_from = 0
    if isinstance(config, dict):  # not an object: validate() says so below
        schema_from = schema_version(config, path)
        config, _done = migrate(config)
    schema = json.loads(schema_path().read_text(encoding="utf-8"))
    errors = validate(config, schema) or semantic_errors(config)
    if errors:
        raise ConfigError(f"{path} is invalid:\n  " + "\n  ".join(errors))
    if paths_at:
        env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
        try:
            ok = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "-q", f"{paths_at}^{{commit}}"],
                                capture_output=True, env=env).returncode == 0
        except OSError:
            ok = False
        if not ok:  # fail closed: a missing commit would make every old path look absent
            raise ConfigError(f"--paths-at {paths_at} is not a commit in {root}; pass an existing one: "
                              f"git rev-parse --verify {paths_at}")
    # following a move only makes sense for a config read for ANOTHER commit (the protected tip judging a push)
    follow = bool(paths_at) and rev is not None and _commit(root, paths_at) != _commit(root, rev)
    config = with_defaults(config, schema, path_exists_fn(root, paths_at or rev), follow_moves=follow)
    config["_root"] = root
    config["_schemaFrom"] = schema_from  # the schemaVersion on disk (or at `rev`) before the in-memory migration
    return config


def load_local(root):
    """The local file .claude/gw.local.json of `root` as {"privateNames": [...], "allowEmails": [...], "anonymize":
    {name: alias}}, or None when it does not exist. The names of `anonymize` are added to privateNames, so they are
    written once and private-check.py checks them too. Raises ConfigError (fail closed) when it is not a JSON object
    with only the LOCAL_KEYS: privateNames and allowEmails lists of non-empty strings, anonymize an object that maps
    non-empty names to aliases private-project-N."""
    path = Path(root) / LOCAL_REL
    if not path.is_file():
        return None
    fix = (f"fix it (a JSON object with {', '.join(sorted(LOCAL_KEYS))}: lists of strings, and anonymize "
           f'{{"<name>": "private-project-N"}}) and check: python3 {HERE / "config.py"} --root {root} local')
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON at line {exc.lineno}: {exc.msg}; {fix}")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: cannot read it ({exc}); {fix}")
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a JSON object, got {type(data).__name__}; {fix}")
    out = {}
    for key, value in data.items():
        if key not in LOCAL_KEYS:
            raise ConfigError(f"{path}: unknown key '{key}' (allowed: {', '.join(sorted(LOCAL_KEYS))}); {fix}")
        if key == "anonymize":
            if not isinstance(value, dict) or not all(k.strip() and isinstance(v, str) and ALIAS.match(v)
                                                      for k, v in value.items()):
                raise ConfigError(f"{path}: 'anonymize' must map non-empty names to aliases private-project-N "
                                  f"(N a number); {fix}")
            out[key] = dict(value)
            continue
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            raise ConfigError(f"{path}: '{key}' must be a list of non-empty strings; {fix}")
        out[key] = list(value)
    out.setdefault("privateNames", [])
    out.setdefault("allowEmails", [])
    out.setdefault("anonymize", {})
    out["privateNames"] += [name for name in out["anonymize"] if name not in out["privateNames"]]
    return out


def private_check(config):
    """The `privateCheck` key as {"emails": bool, "allowEmails": [...]} with its defaults, or None when it is false
    (private-check.py off)."""
    value = config.get("privateCheck", True)
    if value is False:
        return None
    value = value if isinstance(value, dict) else {}
    return {"emails": value.get("emails", True), "allowEmails": list(value.get("allowEmails") or [])}


def related_commands(config, kind, files, deleted=(), skipped=None):
    """The relatedTests commands of `kind` that apply to `files` (repo-relative paths that exist in the commit), each
    as one shell command line. An entry is a string or {"command", "paths"?, "cwd"?}. `paths` (a regex searched in the
    repo-relative path) narrows {files} and makes the entry run only when some file matches; `cwd` (a folder of the
    repo) is where it runs and {files} arrive relative to it, files outside it being left out. Without either, the
    old rules: a fast command runs always unless it uses {files}; a slow one only when some file changed. `deleted`
    (paths of the push that no longer exist) is decided per entry: when an entry's scope matches no existing file but
    matches a deleted one, it runs if its command has no {files} (nonexistent paths are never passed) and is skipped
    otherwise (its command is appended to `skipped`, a list, when given). Every command is run as
    `<checkWrapper> bash -c '<command>'` (with `cd CWD &&` inside when `cwd` is set), so the wrapper covers a compound
    command whole."""
    wrapper = (config.get("checkWrapper") or "").strip()
    out = []

    def scoped(paths, cwd, names):
        names = list(names)
        if paths:
            names = [f for f in names if re.search(paths, f)]
        if cwd and cwd != ".":
            names = [f[len(cwd) + 1:] for f in names if f.startswith(cwd + "/")]
        return names

    for entry in (config.get("relatedTests") or {}).get(kind) or []:
        spec = {"command": entry} if isinstance(entry, str) else entry
        command, paths, cwd = spec["command"], spec.get("paths"), spec.get("cwd")
        if cwd:
            cwd = posixpath.normpath(cwd)
        scope = scoped(paths, cwd, files)
        uses_files = "{files}" in command
        if kind == "slow" or paths or uses_files:
            if not scope:
                if scoped(paths, cwd, deleted):
                    if uses_files:
                        if skipped is not None:
                            skipped.append(command)
                        continue
                else:
                    continue
        inner = command.replace("{files}", " ".join(shlex.quote(f) for f in scope))
        if cwd:
            inner = f"cd {shlex.quote(cwd)} && {inner}"
        out.append(f"{wrapper} bash -c {shlex.quote(inner)}" if wrapper else inner)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="project path (default: see above)")
    parser.add_argument("--rev", help="read the config from this commit instead of the working tree")
    parser.add_argument("--paths-at", help="look for the old-name path fallback in this commit (default: --rev)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("root")
    sub.add_parser("local", help="the validated local file .claude/gw.local.json as JSON (null when absent)")
    related = sub.add_parser("related", help="relatedTests commands that apply to the files on stdin")
    related.add_argument("--kind", choices=("fast", "slow"), required=True)
    related.add_argument("--deleted-file", help="file listing, one per line, the pushed paths that no longer exist")
    get = sub.add_parser("get")
    get.add_argument("key", help="top-level key, or dotted (relatedTests.fast)")
    get.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load(args.root, args.rev, args.paths_at)
    except ConfigError as exc:
        print(f"gw config: {exc}", file=sys.stderr)
        return 2
    if args.command == "validate":
        print(f"{args.rev + ':' + CONFIG_REL.as_posix() if args.rev else config['_root'] / CONFIG_REL}: valid")
        return 0
    if args.command == "root":
        print(config["_root"])
        return 0
    if args.command == "local":
        try:
            print(json.dumps(load_local(config["_root"]), ensure_ascii=False))
        except ConfigError as exc:
            print(f"gw config: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.command == "related":
        files = [line for line in sys.stdin.read().splitlines() if line]
        deleted = []
        if args.deleted_file:
            with open(args.deleted_file, encoding="utf-8") as fh:
                deleted = [line for line in fh.read().splitlines() if line]
        skipped = []
        for full in related_commands(config, args.kind, files, deleted, skipped):
            sys.stdout.write(full + "\0")
        for command in skipped:
            print(f"related-tests: skipped ({args.kind}): {command} (its changed files were only deleted)", file=sys.stderr)
        return 0
    value = config
    for part in args.key.split("."):
        if not isinstance(value, dict) or part not in value or part.startswith("_"):
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
