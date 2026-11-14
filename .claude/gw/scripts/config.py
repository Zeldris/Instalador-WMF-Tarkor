#!/usr/bin/env python3
# galivelop-workflow v0.6.0
"""The only reader of a project's .claude/gw.json (one fact, one place).

Validates the config against schema/gw.schema.json (a stdlib validator for the subset the schema uses) and fills the
defaults the schema declares. Shell scripts call the CLI; Python scripts import load().

  python3 config.py validate            # exit 0 if valid; errors on stderr, exit 2
  python3 config.py get KEY             # scalar: one line; list: one item per line; object: JSON
  python3 config.py get KEY --json      # always JSON
  python3 config.py default KEY         # the schema default of a top-level key, with no config read (a script's
                                        # fallback when the config cannot be read); a list: one item per line
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
import fnmatch
import functools
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
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value > schema.get("maximum", value):
            errors.append(f"{path}: must be at most {schema['maximum']}, got {value!r}")
        if value <= schema.get("exclusiveMinimum", value - 1):
            errors.append(f"{path}: must be above {schema['exclusiveMinimum']}, got {value!r}")
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


@functools.lru_cache(maxsize=None)
def _schema_text():
    return schema_path().read_text(encoding="utf-8")


def _schema():
    """The parsed schema: read once per process, a fresh copy per call (callers may change what they get)."""
    return json.loads(_schema_text())


def _section(config, key):
    """The object key `key` of the config with every missing inner key filled from the schema default (the only place
    the defaults live): the loader fills only top-level keys."""
    props = _schema()["properties"][key]["properties"]
    given = config.get(key)
    given = given if isinstance(given, dict) else {}
    return {k: given.get(k, prop["default"]) for k, prop in props.items()}


def _bounded_section(config, key):
    """Like `_section`, but a value that is not an integer within the schema's minimum and maximum gives that key's
    default: for the keys a hook reads, a bad value must never hide what the hook shows (the loader rejects it, a caller
    that fell back to `{}` still gets numbers)."""
    props = _schema()["properties"][key]["properties"]
    given = config.get(key)
    given = given if isinstance(given, dict) else {}
    out = {}
    for k, prop in props.items():
        v = given.get(k, prop["default"])
        ok = (isinstance(v, int) and not isinstance(v, bool) and v >= prop.get("minimum", v)
              and v <= prop.get("maximum", v))
        out[k] = v if ok else prop["default"]
    return out


def recover(config):
    """The `recover` key (A13) as a dict (logLines, statusLines, worktrees, otherBranches, branchRow, worktreeRow,
    outputCap, gitWait, searchMax, searchWidth): the sizes of recover.py's --state and --search. The schema's minimums
    keep an over-low value from hiding the state; an invalid value (or `{}`, an unreadable config) gives the default."""
    return _bounded_section(config, "recover")


def handoff(config):
    """The `handoff` key (A13) as a dict (rowLimit, cellLimit, doneItems): the log size rules of handoff.py; an invalid
    value gives the schema default."""
    return _bounded_section(config, "handoff")


def _int_key(config, key):
    """The top-level integer key `key`: its value when it is an integer within the schema's minimum and maximum, else
    the schema default (for the keys a script reads after a config it could not read: a bad value never hides a check)."""
    prop = _schema()["properties"][key]
    given = config.get(key)
    ok = (isinstance(given, int) and not isinstance(given, bool) and given >= prop.get("minimum", given)
          and given <= prop.get("maximum", given))
    return given if ok else prop["default"]


def _string_list_key(config, key):
    """The top-level key `key`, a list of non-empty strings: the list when it is one (and not empty when the schema
    asks for `minItems`), else the schema default."""
    prop = _schema()["properties"][key]
    given = config.get(key)
    allowed = prop.get("items", {}).get("enum")  # a closed list (ciGreenConclusions): anything else is the default
    if (isinstance(given, list) and len(given) >= prop.get("minItems", 0)
            and all(isinstance(x, str) and x and (allowed is None or x in allowed) for x in given)):
        return list(given)
    return list(prop["default"])


def harvest(config):
    """The `harvest` key (A13) as a dict (ideaChars, commitsShown): the sizes harvest.py prints; an invalid value gives
    the schema default."""
    return _bounded_section(config, "harvest")


def commit_types(config):
    """The `commitTypes` key (A13): the Conventional Commits types, the schema default when absent or invalid."""
    return _string_list_key(config, "commitTypes")


def commit_wip_prefix(config):
    """The `commitWipPrefix` key (A13): the prefix of a commit made in red ("" = none), the default when not a string."""
    given = config.get("commitWipPrefix")
    return given if isinstance(given, str) else _schema()["properties"]["commitWipPrefix"]["default"]


def patch_commit_types(config):
    """The `patchCommitTypes` key (A13): the commit types version.py reads as asking for a patch bump."""
    return _string_list_key(config, "patchCommitTypes")


def ci_green_conclusions(config):
    """The `ciGreenConclusions` key (A13): the check-run conclusions ci-status.py counts as green (success, neutral and
    skipped only: a failing conclusion can never count as green)."""
    return _string_list_key(config, "ciGreenConclusions")


def ci_status_timeout(config):
    """The `ciStatusTimeout` key (A13): seconds a gh or curl call of ci-status.py may take (0 = no limit)."""
    return _int_key(config, "ciStatusTimeout")


def ci_step_timeout(config):
    """The `ciStepTimeout` key (A13): minutes a step of ci-local.py without its own `timeout-minutes` may take
    (0 = no limit; a fraction of a minute is fine, like GitHub's own `timeout-minutes`)."""
    given = config.get("ciStepTimeout")
    if isinstance(given, (int, float)) and not isinstance(given, bool) and 0 <= given < float("inf"):
        return given
    return _schema()["properties"]["ciStepTimeout"]["default"]


def ci_system_commands(config):
    """The `ciSystemCommands` key (A13): the commands whose steps ci-local.py leaves out as system-package installs
    (an empty list leaves none out)."""
    prop = _schema()["properties"]["ciSystemCommands"]
    given = config.get("ciSystemCommands")
    if isinstance(given, list) and all(isinstance(x, str) and x in prop["items"]["enum"] for x in given):
        return list(given)  # only package managers: a bad entry gives the default, never a way to skip a real step
    return list(prop["default"])


def doctor_scan_bytes(config):
    """The `doctorScanBytes` key (A13): the size under which doctor.py reads a file that a `check` command names."""
    return _int_key(config, "doctorScanBytes")


def apply_diff_lines(config):
    """The `applyDiffLines` key (A13): the lines of template diff apply.py prints for a seeded file."""
    return _int_key(config, "applyDiffLines")


def stale_refs_paths(config):
    """The `staleRefsPaths` key (A13): the globs of the tracked files md-links.py scans for `staleRefs`."""
    return _string_list_key(config, "staleRefsPaths")


def instruction_lines(config):
    """The `instructionLines` key as (warn, fail): the line limits of AGENTS.md/CLAUDE.md."""
    limits = _section(config, "instructionLines")
    return limits["warn"], limits["fail"]


def doctor_test_dirs_ignore(config):
    """The `doctorTestDirsIgnore` key: folder patterns doctor.py skips when it looks for test_*.py nobody runs (E43)."""
    return list(config.get("doctorTestDirsIgnore", _schema()["properties"]["doctorTestDirsIgnore"]["default"]))


def context_guard(config):
    """The `contextGuard` key as a dict (cutoff, window, autocompactShare, warn, alarm,
    charsPerToken, bigWindow)."""
    return _section(config, "contextGuard")


def metrics(config):
    """The `metrics` key as a dict (ledger, record, reports, prices, alert, quality); `alert` and `quality` are filled
    key by key."""
    out = _section(config, "metrics")
    props = _schema()["properties"]["metrics"]["properties"]
    for key in ("alert", "quality"):
        given = out[key] if isinstance(out[key], dict) else {}
        out[key] = {k: given.get(k, p["default"]) for k, p in props[key]["properties"].items()}
    return out


def models(config):
    """The `models` key as a dict (disabled) (B7)."""
    return _section(config, "models")


def measure(config):
    """The `measure` key as a dict (minCalls, imageTokens, mixedRatio, minOutput, coldMs) (B29, A13)."""
    return _section(config, "measure")


def media_content(config):
    """The `mediaContent` key as a dict (maxSubjects) (A13)."""
    return _section(config, "mediaContent")


def test_scan_skip_dirs(config):
    """The `testScanSkipDirs` key (A13): the folder names tests-after-main.py skips in its walk outside git; the schema
    default when absent or invalid (an empty list is valid: skip none)."""
    given = config.get("testScanSkipDirs")
    if isinstance(given, list) and all(isinstance(x, str) and x for x in given):
        return list(given)
    return list(_schema()["properties"]["testScanSkipDirs"]["default"])


def review_trivial_lines(config):
    """The `reviewTrivialLines` key (B27): the changed lines at or under which a phase 1 diff is trivial; the schema
    default when absent or not a non-negative integer."""
    given = config.get("reviewTrivialLines")
    if isinstance(given, int) and not isinstance(given, bool) and given >= 0:
        return given
    return _schema()["properties"]["reviewTrivialLines"]["default"]


def test_map(config):
    """The `testMap` key as a dict (rules, command) (E21)."""
    return _section(config, "testMap")


def roadmap_files(config):
    """The `roadmapFiles` key: [{"path", "done", "open"}] (D55), [] when absent."""
    return config.get("roadmapFiles") or []


def change_size(config):
    """The `changeSize` key as a dict (commit, block, exclude, pairs) (D43)."""
    return _section(config, "changeSize")


def retro(config):
    """The `retro` key as a dict (filePattern, statusMarker, decidedWords, pendingWords) (A13)."""
    return _section(config, "retro")


def red_without_fix(config):
    """The `redWithoutFix` key as a dict (compileRegex, testRegex) (A13)."""
    return _section(config, "redWithoutFix")


def branch_prefixes(config):
    """The `branchPrefixes` key as a dict (agent, keep) (A13)."""
    return _section(config, "branchPrefixes")


def marketing_sheets(config):
    """The `marketingSheets` settings (`{"sources": [...]}` alone is a valid way to turn the feature on)."""
    return _section(config, "marketingSheets")


def log_size(config):
    """The `logSize` key: the cap on the hand-off log in characters (0 = no cap), the schema default when absent."""
    given = config.get("logSize")
    if isinstance(given, int) and not isinstance(given, bool):
        return given
    return _schema()["properties"]["logSize"]["default"]


def whole_read_warn_bytes(config):
    """The `wholeReadWarnBytes` key (B26): the size above which a whole Read of the log or a record is warned about
    (0 = never), the schema default when absent or invalid."""
    given = config.get("wholeReadWarnBytes")
    if isinstance(given, int) and not isinstance(given, bool) and given >= 0:
        return given
    return _schema()["properties"]["wholeReadWarnBytes"]["default"]


def hook_stdin_wait(root=None):
    """The `hookStdinWait` key (A13): seconds a hook waits for its event JSON on stdin. A hook reads stdin before it
    knows whether the config is usable, so a missing, unreadable or invalid config (or value) gives the schema
    default, never an error: the hook then says what is wrong when it reads the config for its own keys."""
    try:
        default = float(schema_default("hookStdinWait"))
    except (ConfigError, OSError, ValueError, KeyError):
        return 3.0  # only when the schema itself is missing (a broken install): the hook then reports it
    try:
        given = load(root)["hookStdinWait"]
    except (ConfigError, OSError, ValueError, KeyError):
        return default
    if isinstance(given, bool) or not isinstance(given, (int, float)) or not 0.1 <= given <= 60:
        return default
    return float(given)


def schema_default(key):
    """The schema default of the top-level key `key` (the only place the defaults live)."""
    return _schema()["properties"][key]["default"]


SUBAGENT_KEYS = ("subagentCap", "subagentCapStep", "subagentCounterStaleDays", "subagentTranscriptBytes",
                 "subagentCapAction")


def subagent_settings(root=None):
    """The subagent-cap.py keys (A13) as a dict: subagentCap, subagentCapStep, subagentCounterStaleDays,
    subagentTranscriptBytes, subagentCapAction. A hook must keep counting, so a config it cannot read, or a value
    that does not fit its schema, gives that key's schema default, never an error."""
    out = {k: schema_default(k) for k in SUBAGENT_KEYS}
    try:
        conf = load(root)
    except (ConfigError, OSError, ValueError):
        return out
    props = _schema()["properties"]
    for key in SUBAGENT_KEYS:
        given, prop = conf.get(key), props[key]
        if prop["type"] == "string":
            ok = given in prop["enum"]
        else:
            ok = (isinstance(given, int) and not isinstance(given, bool) and given >= prop["minimum"]
                  and given <= prop.get("maximum", given))
        if ok:
            out[key] = given
    return out


def stop_severity(config):
    """The `stopSeverity` key (A13) as a dict (unpushed, logRequired), each "block" or "warn"."""
    return _section(config, "stopSeverity")


def log_archive(config):
    """The `logArchive` key: repo-relative path of the hand-off archive, the schema default when absent."""
    given = config.get("logArchive")
    return given if isinstance(given, str) and given else _schema()["properties"]["logArchive"]["default"]


def owned(config, rel):
    """Whether the repo-relative path `rel` matches an `ownedFiles` pattern (fnmatch.fnmatchcase; an exact path is a
    pattern): a workflow file the project made its own on purpose, so apply.py and doctor.py leave it alone."""
    rel = str(rel).replace(os.sep, "/")
    return any(isinstance(p, str) and fnmatch.fnmatchcase(rel, p) for p in config.get("ownedFiles") or [])


def log_size(config):
    """The `logSize` key: the cap on the hand-off log in characters (0 = no cap), the schema default when absent."""
    schema = json.loads(schema_path().read_text(encoding="utf-8"))
    given = config.get("logSize")
    return given if isinstance(given, int) and not isinstance(given, bool) else schema["properties"]["logSize"]["default"]


def log_archive(config):
    """The `logArchive` key: repo-relative path of the hand-off archive, the schema default when absent."""
    schema = json.loads(schema_path().read_text(encoding="utf-8"))
    given = config.get("logArchive")
    return given if isinstance(given, str) and given else schema["properties"]["logArchive"]["default"]


# What Python re and grep -E do not share (A13): shorthand classes and word boundaries, extension groups, POSIX classes,
# backreferences. agentSignaturePatterns reach both engines, so they are limited to the common subset.
SHARED_REGEX_UNSAFE = re.compile(r"\\[dDsSwWbBAZz<>`'1-9]|\(\?|\[\[:|\[\^?\[:")


def semantic_errors(config):
    """Problems the schema subset cannot express: a relatedTests `paths`, testMap `paths`/`contains` or changeSize
    `exclude`/`pairs`, fullCheckPaths, agentModelShapes or agentSignaturePatterns entry that is not a valid regex (or a pair replacement that does not fit its
    regex), an agentMap prefix that is not one folder name, an instructionLines `warn` above its `fail`, an
    ownedFiles pattern that is absolute or has a `..`."""
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
    test_rules = config.get("testMap", {}).get("rules") if isinstance(config.get("testMap"), dict) else None
    for i, rule in enumerate(test_rules if isinstance(test_rules, list) else []):
        for key in ("paths", "contains"):
            if isinstance(rule, dict) and isinstance(rule.get(key), str):
                try:
                    re.compile(rule[key])
                except re.error as exc:
                    errors.append(f"$.testMap.rules[{i}].{key}: {rule[key]!r} is not a valid regex ({exc})")
    size = config.get("changeSize") if isinstance(config.get("changeSize"), dict) else {}
    regexes = [("exclude", i, rx) for i, rx in enumerate(size.get("exclude") or []) if isinstance(rx, str)]
    regexes += [("pairs", rx, rx) for rx in (size.get("pairs") or {})]
    for key, where, rx in regexes:
        try:
            re.compile(rx)
        except re.error as exc:
            errors.append(f"$.changeSize.{key}[{where!r}]: {rx!r} is not a valid regex ({exc})")
    for i, rx in enumerate(config.get("fullCheckPaths") or []):
        if isinstance(rx, str):
            try:
                re.compile(rx)
            except re.error as exc:
                errors.append(f"$.fullCheckPaths[{i}]: {rx!r} is not a valid regex ({exc})")
    for key in ("agentModelShapes", "agentSignaturePatterns"):
        for i, rx in enumerate(config.get(key) or []):
            if isinstance(rx, str):
                try:
                    re.compile(rx)
                except re.error as exc:
                    errors.append(f"$.{key}[{i}]: {rx!r} is not a valid regex ({exc})")
                    continue
                if key == "agentSignaturePatterns" and (m := SHARED_REGEX_UNSAFE.search(rx)):
                    errors.append(f"$.{key}[{i}]: {rx!r} uses {m.group(0)!r}, which Python re and grep -E read differently; "
                                  "write it with the common subset only (literals, . [abc] [^abc] * + ? {n,m} | ( ) ^ $), "
                                  "e.g. [0-9] instead of \\d, [ \\t] instead of \\s")
    retro_keys = config.get("retro") if isinstance(config.get("retro"), dict) else {}
    for key, rx in retro_keys.items():  # reviewed.sh reads them with grep -E and awk: the common subset only
        if isinstance(rx, str):
            try:
                re.compile(rx)
            except re.error as exc:
                errors.append(f"$.retro.{key}: {rx!r} is not a valid regex ({exc})")
                continue
            if m := SHARED_REGEX_UNSAFE.search(rx):
                errors.append(f"$.retro.{key}: {rx!r} uses {m.group(0)!r}, which Python re and grep -E read differently; "
                              "write it with the common subset only (literals, . [abc] [^abc] * + ? {n,m} | ( ) ^ $)")
    for i, pat in enumerate(config.get("ownedFiles") or []):
        if isinstance(pat, str) and pat:
            parts = pat.replace("\\", "/").split("/")
            if pat.startswith("/") or re.match(r"^[A-Za-z]:", pat):
                errors.append(f"$.ownedFiles[{i}]: {pat!r} is an absolute path; use a path relative to the repo root")
            elif ".." in parts:
                errors.append(f"$.ownedFiles[{i}]: {pat!r} has a '..' component; use a path inside the repo")
    for rx, repl in (size.get("pairs") or {}).items():
        try:
            re.compile(rx).sub(repl, "")
        except (re.error, IndexError) as exc:
            errors.append(f"$.changeSize.pairs[{rx!r}]: replacement {repl!r} does not fit its regex ({exc})")
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
    """The `privateCheck` key as {"emails": bool, "allowEmails": [...], "maxHits": int} with its defaults, or None when
    it is false (private-check.py off)."""
    value = config.get("privateCheck", True)
    if value is False:
        return None
    value = value if isinstance(value, dict) else {}
    max_hits = _schema()["properties"]["privateCheck"]["default"]["maxHits"]
    return {"emails": value.get("emails", True), "allowEmails": list(value.get("allowEmails") or []),
            "maxHits": value.get("maxHits", max_hits)}


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


def _raw_at(root, rev):
    """The top-level JSON object of .claude/gw.json in commit `rev`, or None when it is missing or not an object."""
    try:
        data = json.loads(read_at(root, rev))
    except (ConfigError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def config_keys_changed(root, commits):
    """The top-level keys of .claude/gw.json that `commits` (shas) change, each against every parent it has (E47).
    None, failing closed, when a commit or a parent has no readable config object there (an added, removed or broken
    file) or git cannot list a commit's parents."""
    changed = set()
    for sha in commits:
        try:
            r = subprocess.run(["git", "-C", str(root), "rev-parse", f"{sha}^@"], capture_output=True, text=True)
        except OSError:
            return None
        if r.returncode != 0:
            return None
        new = _raw_at(root, sha)
        for parent in r.stdout.split():
            old = _raw_at(root, parent)
            if new is None or old is None:
                return None
            changed |= {k for k in set(old) | set(new) if old.get(k, _MISSING) != new.get(k, _MISSING)}
    return changed


_MISSING = object()


def push_scope(config, files, commits=None):
    """What the pre-push runs for a branch push that changes `files` (repo-relative), as (scope, reason): ("full",
    why) or ("related", None) (D49). Full when branchCheck is "full", when relatedTests has no command (there would
    be nothing to run), or when a file matches a fullCheckPaths regex or is .claude/gw.json (an environment change).
    E47: with `commits` (the push's new shas), a .claude/gw.json change counts only when one of the keys it changes is
    not in fullCheckSkipKeys (fullCheckSkipKeys itself always counts; an unreadable config on either side, too).
    The protected branch never asks: it always runs the full check."""
    if config.get("branchCheck", "related") == "full":
        return "full", "branchCheck is full"
    related = config.get("relatedTests") or {}
    if not any(related.get(kind) for kind in ("fast", "slow")):
        return "full", "relatedTests has no command"
    regexes = [re.compile(rx) for rx in config.get("fullCheckPaths") or []]
    for name in files:
        if any(rx.search(name) for rx in regexes):
            return "full", f"environment change: {name}"
    if CONFIG_REL.as_posix() in files:
        if commits is None:
            return "full", f"environment change: {CONFIG_REL.as_posix()}"
        keys = config_keys_changed(config["_root"], commits)
        if keys is None:
            return "full", f"environment change: {CONFIG_REL.as_posix()} (cannot compare it with its parent)"
        skip = set(config.get("fullCheckSkipKeys") or []) - {"fullCheckSkipKeys"}
        counted = sorted(keys - skip)
        if counted:
            return "full", f"environment change: {CONFIG_REL.as_posix()} ({', '.join(counted)})"
    return "related", None


def _print_value(value, as_json):
    """A scalar on one line, a list one item per line, an object as JSON (`get` and `default`)."""
    if as_json or isinstance(value, dict):
        print(json.dumps(value, ensure_ascii=False))
    elif isinstance(value, list):
        for item in value:
            print(item if not isinstance(item, (dict, list)) else json.dumps(item, ensure_ascii=False))
    elif isinstance(value, bool):
        print("true" if value else "false")
    else:
        print(value)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="project path (default: see above)")
    parser.add_argument("--rev", help="read the config from this commit instead of the working tree")
    parser.add_argument("--paths-at", help="look for the old-name path fallback in this commit (default: --rev)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    default_p = sub.add_parser("default", help="the schema default of a top-level key (no config needed): a script's "
                                               "fallback when the config cannot be read")
    default_p.add_argument("key")
    sub.add_parser("root")
    sub.add_parser("local", help="the validated local file .claude/gw.local.json as JSON (null when absent)")
    related = sub.add_parser("related", help="relatedTests commands that apply to the files on stdin")
    related.add_argument("--kind", choices=("fast", "slow"), required=True)
    related.add_argument("--deleted-file", help="file listing, one per line, the pushed paths that no longer exist")
    scope_p = sub.add_parser("push-scope", help="'full <reason>' or 'related' for a branch push changing the files on stdin")
    scope_p.add_argument("--commits", help="file listing the push's new commits, one sha per line: a .claude/gw.json "
                                           "change then counts only by its keys (fullCheckSkipKeys, E47)")
    get = sub.add_parser("get")
    get.add_argument("key", help="top-level key, or dotted (relatedTests.fast)")
    get.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "default":
        try:
            value = schema_default(args.key)
        except (ConfigError, KeyError, OSError):
            print(f"gw config: key '{args.key}' has no default in the schema", file=sys.stderr)
            return 2
        _print_value(value, False)
        return 0
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
    if args.command == "push-scope":
        commits = None
        if args.commits:
            with open(args.commits, encoding="utf-8") as fh:
                commits = [line.strip() for line in fh.read().splitlines() if line.strip()]
        scope, reason = push_scope(config, [line for line in sys.stdin.read().splitlines() if line], commits)
        print(f"{scope} {reason}" if reason else scope)
        return 0
    value = dict(config, metrics=metrics(config), models=models(config), measure=measure(config), mediaContent=media_content(config),
                 recover=recover(config), handoff=handoff(config), harvest=harvest(config),
                 contextGuard=context_guard(config),
                 stopSeverity=stop_severity(config), changeSize=change_size(config),
                 retro=retro(config), redWithoutFix=red_without_fix(config), branchPrefixes=branch_prefixes(config))  # inner keys fill from the schema too
    for part in args.key.split("."):
        if not isinstance(value, dict) or part not in value or part.startswith("_"):
            print(f"gw config: key '{args.key}' is not set and has no default", file=sys.stderr)
            return 2
        value = value[part]
    _print_value(value, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
