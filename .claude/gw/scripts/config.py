#!/usr/bin/env python3
# galivelop-workflow v0.9.0
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
  python3 config.py author-check        # E41: exit 1 when the commit's author or committer (git var GIT_AUTHOR_IDENT /
                                        # GIT_COMMITTER_IDENT, so GIT_AUTHOR_*/GIT_COMMITTER_* count as in git) matches
                                        # authorDeny; an empty list checks nothing (called by the pre-commit hook)
  python3 config.py --rev REV author-check --commits -   # the same over the commits on stdin, one sha per line
                                        # (%an/%ae/%cn/%ce; the pre-push on what it pushes, pre-commit --range in CI)
  python3 config.py spike-branch NAME   # C12: exit 0 when branch NAME is an exploration branch (spikeBranch prefix),
                                        # 1 when it is not or the feature is off (""); --prefix prints the prefix as
                                        # applied (`spike` -> `spike/`; empty when off)
  python3 config.py --rev REV spike-check --commits -    # C12: exit 1 (and the reason, with what to do instead)
                                        # when a commit on stdin comes from an exploration branch: a `Spike:` trailer
                                        # naming one (also indented, as a squash message keeps it) or a merge whose
                                        # subject names one ("Merge branch 'spike/x'", remote-tracking too)

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
import hashlib
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
SCHEMA_VERSION = 2


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


def _migrate_to_2(raw):
    """1 -> 2 (A12, Q-14): `language` -> `languages.docs.primary` and `languages.public.primary`, `visibleLanguages` ->
    `languages.ui`, `languages.code` = "en", the `others` lists []; both old keys are removed. A `languages` block
    already there wins: the old keys only fill what it lacks. The block takes the place of `language`; a config with
    neither old key gets none (the schema then says `languages` is missing). `schemaVersion` becomes 2 in place."""
    old_language = raw.get("language")
    old_visible = raw.get("visibleLanguages")
    has_old = "language" in raw or "visibleLanguages" in raw
    block = raw.get("languages")
    if has_old and not isinstance(block, dict):
        if "languages" in raw:  # not an object: the old keys stay, and the schema rejects `languages` with its reason
            out = dict(raw)
            out["schemaVersion"] = 2
            return out
        block = {}
    out = {}
    placed = False
    for key, value in raw.items():
        if key in ("language", "visibleLanguages"):
            if not placed and has_old:
                out["languages"] = block
                placed = True
            continue
        if key == "languages" and placed:
            continue
        out[key] = value
        if key == "languages":
            placed = True
    if has_old and not placed:
        out["languages"] = block
    if has_old:
        block = out["languages"]
        block.setdefault("code", "en")
        for part in ("docs", "public"):
            sub = block.setdefault(part, {})
            if isinstance(sub, dict):
                if "language" in raw:
                    sub.setdefault("primary", old_language)
                sub.setdefault("others", [])
        if "visibleLanguages" in raw:
            block.setdefault("ui", old_visible)
        else:
            block.setdefault("ui", [])
    out["schemaVersion"] = 2
    return out


# (target schemaVersion, what it changes in one line, function(raw dict) -> raw dict), in order.
MIGRATIONS = [
    (1, "schemaVersion written (the format is versioned from now on)", _migrate_to_1),
    (2, "language and visibleLanguages become the languages block (docs.primary, public.primary, ui; code en)",
     _migrate_to_2),
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


# Where a project keeps its copy of push.sh (D94), relative to its root: the installed copy first, then this repo's
# source. A hook may run from the plugin cache, whose push.sh would take the cache as its root; so a suggested push
# command always names the project's own copy.
PUSH_SCRIPTS = (".claude/gw/scripts/push.sh", "scripts/push.sh")


def push_command(root, branch, wip=False):
    """The shell command that pushes `branch` of the project at `root` (D94): `bash <root>/<copy>/push.sh <branch>`
    with the project's own push.sh (PUSH_SCRIPTS), shell-quoted; without one, `git push -u origin <branch>`.
    `wip` (E84) adds `--wip` (a WIP: head pushed without the check); it is None when the project has no push.sh or its
    copy does not know `--wip` (an older one)."""
    for rel in PUSH_SCRIPTS:
        path = os.path.join(str(root), rel)
        if os.path.isfile(path):
            if wip:
                try:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        if "--wip" not in f.read():
                            return None
                except OSError:
                    return None
            return f"bash {shlex.quote(path)} {'--wip ' if wip else ''}{shlex.quote(branch)}"
    return None if wip else f"git push -u origin {shlex.quote(branch)}"


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


def languages(config):
    """A12: the `languages` block of the config, normalized: {"code": "en", "docs": {"primary", "others"}, "public":
    {"primary", "others"}, "ui": [...]}, each missing key filled from the schema default (the readers' one accessor;
    a partial or absent block, or a caller that fell back to `{}`, still gets every key)."""
    props = _schema()["properties"]["languages"]["properties"]
    given = config.get("languages") if isinstance(config, dict) else None
    given = given if isinstance(given, dict) else {}
    out = {"code": given.get("code", props["code"]["default"])}
    for part in ("docs", "public"):
        inner = given.get(part) if isinstance(given.get(part), dict) else {}
        out[part] = {"primary": inner.get("primary", props[part]["properties"]["primary"]["default"]),
                     "others": list(inner.get("others", props[part]["properties"]["others"]["default"]))}
    out["ui"] = list(given.get("ui", props["ui"]["default"]))
    return out


def user_config_path():
    """A12 (Q-18): the per-user file (not the project config): $GW_USER_CONFIG, else ~/.claude/gw.json."""
    given = os.environ.get("GW_USER_CONFIG")
    return Path(given) if given else Path.home() / ".claude" / "gw.json"


def agent_language(config):
    """A12 (Q-18): (code, warning) of the language the agent talks in: the user file's `agentLanguage[<git config
    user.email of the repo>]` (emails compared trimmed and lowercase), else `languages.docs.primary`. A missing file,
    entry or email falls back silently; an unreadable file, a bad `agentLanguage` or a code that does not match the
    schema's language pattern falls back with a one-line warning (never an exception)."""
    fallback = languages(config)["docs"]["primary"]
    path = user_config_path()
    if not path.is_file():
        return fallback, None
    fix = '{"agentLanguage": {"<git config user.email>": "<code>"}}'
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("it must be a JSON object")
        table = data.get("agentLanguage")
        if "agentLanguage" in data and not isinstance(table, dict):
            raise ValueError("`agentLanguage` must be an object of {email: language code}")
    except (OSError, ValueError) as exc:  # JSONDecodeError is a ValueError
        return fallback, f"{path} is not usable ({exc}); using '{fallback}' (languages.docs.primary); fix it: {fix}"
    r = subprocess.run(["git", "-C", str(config.get("_root", ".")), "config", "--get", "user.email"],
                       capture_output=True, text=True)
    email = r.stdout.strip().lower()
    if not email:
        return fallback, None
    value = {str(k).strip().lower(): v for k, v in (table or {}).items()}.get(email)
    if value is None:
        return fallback, None
    pattern = _schema()["properties"]["languages"]["properties"]["docs"]["properties"]["primary"]["pattern"]
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        return fallback, (f"{path}: agentLanguage for {email} is {value!r}, not a language code matching {pattern}; "
                          f"using '{fallback}' (languages.docs.primary); fix it: {fix}")
    return value, None


def agent_language_line(config):
    """A12 (Q-18): (the `Agent language: <code>` line, warning or None) printed at session start and after a compaction."""
    code, warning = agent_language(config)
    return f"Agent language: {code}", warning


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
    """The `handoff` key (A13) as a dict (rowLimit, cellLimit, cellHardLimit, doneItems, lockWait): the log size rules and the lock wait of
    handoff.py (cellHardLimit 0 = off, D96); an invalid value gives the schema default. A cellHardLimit the project
    did not set never sits below its cellLimit: the default hard cap rises to cellLimit, so a project that only raised
    cellLimit keeps a valid config and a hard cap at or above its warning."""
    sizes = _bounded_section(config, "handoff")
    given = config.get("handoff")
    if not (isinstance(given, dict) and "cellHardLimit" in given) and 0 < sizes["cellHardLimit"] < sizes["cellLimit"]:
        sizes["cellHardLimit"] = sizes["cellLimit"]
    return sizes


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


def author_deny(config):
    """E41: the `authorDeny` patterns (an invalid value gives the schema default, the empty list)."""
    return _string_list_key(config, "authorDeny")


def author_denied(patterns, name, email):
    """E41: the first pattern of `authorDeny` that the identity (name, email) matches, else None. Case-insensitive; a
    pattern with `@` is a whole email and matches only an equal email; any other pattern is a word or phrase of the
    name, matched whole (`Claude` hits `Claude`, `claude[bot]` and `Claude Code`, not `Claudette`)."""
    name, email = (name or "").strip(), (email or "").strip().casefold()
    for pattern in patterns:
        wanted = pattern.strip()
        if not wanted:
            continue
        if "@" in wanted:
            if email == wanted.casefold():
                return pattern
        elif re.search(r"(?<!\w)" + re.escape(wanted) + r"(?!\w)", name, re.IGNORECASE):
            return pattern
    return None


def parse_ident(ident):
    """`Name <email> 1700000000 +0100` (git var GIT_AUTHOR_IDENT) as (name, email); None when it is not one."""
    m = re.match(r"^(.*?)\s*<([^>]*)>", ident or "")
    return (m.group(1), m.group(2)) if m else None


def commits_author_check(root, patterns, shas):
    """E41: (0, "") when no commit of `shas` has an author or committer matching `patterns` (git commit runs the
    pre-commit; a clean merge, cherry-pick, revert or rebase does not, so the pre-push and CI check what they carry),
    else (1, the offending commits and the command that rewrites them). Fails closed when git cannot read them."""
    shas = [s for s in shas if s]
    if not patterns or not shas:
        return 0, ""
    r = subprocess.run(["git", "log", "--no-walk=unsorted", "--format=%H%x00%an%x00%ae%x00%cn%x00%ce", *shas],
                       cwd=str(root), capture_output=True, text=True)
    if r.returncode != 0:
        return 1, f"cannot read the authors of the commits to check authorDeny; fetch and retry: git log {shas[0][:12]}"
    bad, oldest = [], None
    for line in r.stdout.splitlines():
        parts = line.split("\0")
        if len(parts) != 5:
            continue
        sha, an, ae, cn, ce = parts
        for role, name, email in (("author", an, ae), ("committer", cn, ce)):
            hit = author_denied(patterns, name, email)
            if hit:
                bad.append(f"  {sha[:7]}: {role} {name} <{email}> matches '{hit}'")
                oldest = sha
    if not bad:
        return 0, ""
    fix = (f"git config user.name '<your name>' && git config user.email '<your email>' && git rebase -r --exec "
           f"'git commit --amend --no-edit --reset-author' {oldest[:7]}^")
    return 1, "these commits have an author or committer in authorDeny (.claude/gw.json):\n" + "\n".join(bad) + \
        f"\nrewrite them as yourself: {fix}"


def spike_prefix(config):
    """C12: the exploration branch prefix of `spikeBranch` ("" = off). One that ends in a letter or digit gets a "/",
    so `spike` means `spike/` and a branch called `spiked` never counts; `spike-` stays as written."""
    prefix = str(config.get("spikeBranch", "spike/") or "").strip()
    if prefix and prefix[-1].isalnum():
        prefix += "/"
    return prefix


def is_spike_branch(name, prefix):
    """C12: whether branch `name` (refs/heads/ or a remote's name/ removed by the caller) is an exploration branch: it
    starts with `prefix` and has a topic after it."""
    name = (name or "").strip()
    if name.startswith("refs/heads/"):
        name = name[len("refs/heads/"):]
    return bool(prefix) and name.startswith(prefix) and len(name) > len(prefix)


SPIKE_TODO = ("turn what it taught into a task record (python3 task.py new <id>) and redo it with tests on a working "
              "branch, or throw it away (git branch -D <spike branch>)")


def spike_marked(body, prefix):
    """C12: whether a commit message carries the spike mark: a `Spike: <prefix>...` line in its last paragraph (the
    trailer block, where commit-message.py adds it) or indented by four spaces anywhere (how `git merge --squash`
    quotes the squashed commits' messages). A body line elsewhere that merely starts with `Spike:` does not count."""
    p = re.escape(prefix)
    paragraphs = [part for part in re.split(r"\n[ \t]*\n", body.strip("\n")) if part.strip()]
    if paragraphs and re.search(rf"^Spike:[ \t]*{p}\S", paragraphs[-1], re.M):
        return True
    return bool(re.search(rf"^ {{4}}Spike:[ \t]*{p}\S", body, re.M))


def spike_commits(root, prefix, shas):
    """C12: (0, "") when no commit of `shas` comes from an exploration branch, else (1, the commits and what to do
    instead). A commit comes from one when its message carries the spike mark (spike_marked) or it is a merge whose
    subject is git's own for a branch named with the prefix. The shas go on git's stdin (a first push may hold the
    whole history). Fails closed (1, with the reason) when git cannot read them; off (0) with an empty prefix."""
    shas = [s for s in shas if s]
    if not prefix or not shas:
        return 0, ""
    retry = f"fetch and retry: git log --no-walk {shas[0][:12]}"
    try:
        r = subprocess.run(["git", "log", "--no-walk=unsorted", "--stdin", "--format=%H%x00%P%x00%B%x1e"],
                           cwd=str(root), input="\n".join(shas) + "\n", capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except OSError as exc:
        return 1, f"cannot run git to look for exploration-branch work ({exc}); {retry}"
    if r.returncode != 0:
        return 1, f"cannot read the commits to look for exploration-branch work ({r.stderr.strip()[:200]}); {retry}"
    merge = re.compile(rf"^Merge (?:remote-tracking )?branch(?:es)? '(?:[^'/]+/)?{re.escape(prefix)}[^']+'")
    bad = []
    for record in r.stdout.split("\x1e"):
        parts = record.lstrip("\n").split("\0", 2)
        if len(parts) != 3:
            continue
        sha, parents, body = parts
        subject = body.strip().splitlines()[0] if body.strip() else ""
        if spike_marked(body, prefix):
            bad.append(f"  {sha[:7]} {subject[:72]} (Spike: trailer)")
        elif len(parents.split()) > 1 and merge.match(subject):
            bad.append(f"  {sha[:7]} {subject[:72]} (merge of an exploration branch)")
    if not bad:
        return 0, ""
    return 1, (f"these commits come from an exploration branch ({prefix}<topic>, spikeBranch in .claude/gw.json), "
               f"which never goes into a working branch:\n" + "\n".join(bad) + f"\ninstead: {SPIKE_TODO}")


def author_check(root, patterns):
    """E41: (0, "") when neither the author nor the committer of the commit being made matches `patterns`, else
    (1, message with the command that fixes it). Fails closed when git cannot tell the identity."""
    if not patterns:
        return 0, ""
    for role in ("AUTHOR", "COMMITTER"):
        r = subprocess.run(["git", "var", f"GIT_{role}_IDENT"], cwd=str(root), capture_output=True, text=True)
        ident = parse_ident(r.stdout.strip()) if r.returncode == 0 else None
        if ident is None:
            return 1, (f"cannot read the commit's {role.lower()} (git var GIT_{role}_IDENT failed), so authorDeny cannot "
                       f"be checked; set your identity: git config user.name '<name>' && git config user.email '<email>'")
        hit = author_denied(patterns, *ident)
        if hit:
            who = f"{ident[0]} <{ident[1]}>"
            fix = ("git config user.name '<your name>' && git config user.email '<your email>'"
                   + (" (and unset GIT_{0}_NAME/GIT_{0}_EMAIL if set)".format(role)))
            amend = " For --amend, also: git commit --amend --reset-author." if role == "AUTHOR" else ""
            return 1, (f"the commit's {role.lower()} {who} matches '{hit}' in authorDeny (.claude/gw.json); commit as "
                       f"yourself: {fix}.{amend}")
    return 0, ""


def harvest(config):
    """The `harvest` key (A13) as a dict (ideaChars, commitsShown): the sizes harvest.py prints; an invalid value gives
    the schema default."""
    return _bounded_section(config, "harvest")


def front(config):
    """E5: the `front` block normalized ({"tokens", "out", "breakpointGroup", "mainBreakpoints", "browsers":
    {"all", "main"}}), every missing inner key filled from the schema default (front.py's one accessor)."""
    out = _section(config, "front")
    for key in ("browsers", "stylelint"):
        props = _schema()["properties"]["front"]["properties"][key]["properties"]
        given = out[key] if isinstance(out[key], dict) else {}
        out[key] = {k: (list(given.get(k, prop["default"])) if isinstance(prop["default"], list)
                        else given.get(k, prop["default"])) for k, prop in props.items()}
    out["mainBreakpoints"] = list(out["mainBreakpoints"])
    return out


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


def test_unit_timeout(config):
    """The `testUnitTimeout` key (B42): seconds a test unit of tests-for.py --run may take (0 = no limit). A bad value
    raises ConfigError (fails closed, as testJobs does), never a silent default."""
    given = config.get("testUnitTimeout", schema_default("testUnitTimeout"))
    if not isinstance(given, int) or isinstance(given, bool) or given < 0:
        raise ConfigError(f"testUnitTimeout must be an integer >= 0 (seconds; 0 = no limit), got {given!r}; "
                          "fix .claude/gw.json")
    return given


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


def gitignore_stacks(config):
    """The `gitignoreStacks` key (D127): the stacks apply.py --init writes a .gitignore block for, [] = detect them.
    Fails closed on anything but a list of known stack names, with the command that fixes it."""
    prop = _schema()["properties"]["gitignoreStacks"]
    known = prop["items"]["enum"]
    given = config.get("gitignoreStacks", prop["default"])
    if (not isinstance(given, list) or not all(isinstance(x, str) and x in known for x in given)
            or len(set(given)) != len(given)):
        raise ConfigError(f"gitignoreStacks must be a list of different stacks among {', '.join(known)}, got "
                          f"{given!r}; fix it in {CONFIG_REL} (e.g. [\"python\"]) and validate: "
                          f"python3 scripts/config.py validate")
    return list(given)


def instruction_lines(config):
    """The `instructionLines` key as (warn, fail): the line limits of AGENTS.md/CLAUDE.md."""
    limits = _section(config, "instructionLines")
    return limits["warn"], limits["fail"]


def doctor_test_dirs_ignore(config):
    """The `doctorTestDirsIgnore` key: folder patterns doctor.py skips when it looks for test_*.py nobody runs (E43)."""
    return list(config.get("doctorTestDirsIgnore", _schema()["properties"]["doctorTestDirsIgnore"]["default"]))


def context_guard(config):
    """The `contextGuard` key as a dict (cutoff, window, autocompactShare, warn, alarm,
    charsPerToken, bigWindow, systemAdvice, nearRatio, warnedMax, clearAfterTask)."""
    return _section(config, "contextGuard")


def questions_path(config):
    """The `questions.path` key (C1): repo-relative path of the questions file, `docs/questions.md` by default."""
    return _section(config, "questions")["path"]


def modes(config):
    """The `modes` key as a dict (careful, questions, carefulExempt, carefulWorktrees) (C8, C6): on/off switches of the workflow's opt-out hooks."""
    return _section(config, "modes")


def task_record(config):
    """The `taskRecord` key as a dict (enabled, path, requiredFor, sections, logSections, pendingMarker) (C11)."""
    out = _section(config, "taskRecord")
    out["path"] = posixpath.normpath(out["path"].strip()).strip("/") or "."  # ./docs/tasks, docs//tasks/ -> docs/tasks
    return out


def scope_guard(config):
    """The `scopeGuard` key (C13) as a dict: `mode` as written (off, warn, block or auto), `skipStamps` and `skipVendored`
    (B44) and `effective`, the mode the guard applies (auto = block when modes.questions is restrictive, else warn)."""
    out = _section(config, "scopeGuard")
    mode = out["mode"]
    out["effective"] = ("block" if modes(config)["questions"] else "warn") if mode == "auto" else mode
    return out


def given_keys(root, key):
    """The inner keys the project's .claude/gw.json itself writes under the object key `key` (not the defaults the
    loader fills), as a set; empty when the file, the key or the JSON is missing (B31: is the window known?)."""
    try:
        data = json.loads((Path(root) / CONFIG_REL).read_text(encoding="utf-8"))
        section = data.get(key) if isinstance(data, dict) else None
        return set(section) if isinstance(section, dict) else set()
    except (OSError, ValueError, TypeError):
        return set()


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


WORKFLOW_NAME = "galivelop-workflow"  # the `name` of the workflow's own .claude-plugin/plugin.json


def plugin_field(cand, field):
    """A field of `<cand>/.claude-plugin/plugin.json`, or None when it is unreadable or not an object."""
    try:
        data = json.loads((Path(cand) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get(field) if isinstance(data, dict) else None


def is_workflow(cand):
    """A folder is the workflow repo only when it has the workflow layout and its plugin.json names the workflow (a
    project that vendors the scripts has scripts/apply.py and skills/ too, and must not be taken for the workflow)."""
    return (bool(cand) and (Path(cand) / "scripts" / "apply.py").is_file() and (Path(cand) / "skills").is_dir()
            and plugin_field(cand, "name") == WORKFLOW_NAME)


def workflow_clone(config):
    """The `workflowClone` key (D132): where a project looks for its workflow clone (relative to the repo root)."""
    given = config.get("workflowClone")
    if isinstance(given, str) and given:
        return given
    return _schema()["properties"]["workflowClone"]["default"]


def workflow_repository(config):
    """The `workflowRepository` key (D132): the URL review-scope.py tells to clone when it finds no workflow copy."""
    given = config.get("workflowRepository")
    if isinstance(given, str) and given:
        return given
    return _schema()["properties"]["workflowRepository"]["default"]


def review_trivial_lines(config):
    """The `reviewTrivialLines` key (B27): the changed lines at or under which a phase 1 diff is trivial; the schema
    default when absent or not a non-negative integer."""
    given = config.get("reviewTrivialLines")
    if isinstance(given, int) and not isinstance(given, bool) and given >= 0:
        return given
    return _schema()["properties"]["reviewTrivialLines"]["default"]


def review_split_lines(config):
    """The `review.splitLines` key (E86): the changed lines above which the phase 1 review is dealt to several
    reviewers (0 = never split); the schema default when the block or the value is absent or invalid."""
    default = _schema()["properties"]["review"]["properties"]["splitLines"]["default"]
    block = config.get("review")
    given = block.get("splitLines") if isinstance(block, dict) else None
    if isinstance(given, int) and not isinstance(given, bool) and given >= 0:
        return given
    return default


def scout_settings(config):
    """(`scoutDir`, `scoutMaxAgeDays`) of the config (D80): each the schema default when absent or invalid."""
    prop = _schema()["properties"]["scoutDir"]
    folder = config.get("scoutDir")
    if not (isinstance(folder, str) and re.fullmatch(prop["pattern"], folder)):
        folder = prop["default"]
    return folder, _int_key(config, "scoutMaxAgeDays")


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


def whole_read_short_lines(config):
    """The `wholeReadShortLines` key (E85): lines above which a Bash range read of the log or a roadmap file warns
    (0 = every range), the schema default when absent or invalid."""
    given = config.get("wholeReadShortLines")
    if isinstance(given, int) and not isinstance(given, bool) and given >= 0:
        return given
    return _schema()["properties"]["wholeReadShortLines"]["default"]


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


def pending_file(config):
    """The `pendingFile` key (D104): repo-relative path of the file that holds the log's Pending items, or "" when the
    key is absent or empty (the items stay in the log, as before)."""
    given = config.get("pendingFile")
    return given if isinstance(given, str) else ""


def agents_skills_dir(config):
    """The `agentsSkillsDir` key (D7): repo-relative folder where apply.py also copies the skills (opencode, Codex),
    the schema default when absent, "" when empty (off)."""
    given = config.get("agentsSkillsDir")
    if isinstance(given, str):
        return given
    schema = json.loads(schema_path().read_text(encoding="utf-8"))
    return schema["properties"]["agentsSkillsDir"]["default"]


def decisions_file(config):
    """The `decisionsFile` key (D95): repo-relative path of the file with the Decisions section, or "" (the log)."""
    given = config.get("decisionsFile")
    return given if isinstance(given, str) else ""


# What Python re and grep -E do not share (A13): shorthand classes and word boundaries, extension groups, POSIX classes,
# backreferences. agentSignaturePatterns reach both engines, so they are limited to the common subset.
SHARED_REGEX_UNSAFE = re.compile(r"\\[dDsSwWbBAZz<>`'1-9]|\(\?|\[\[:|\[\^?\[:")


def semantic_errors(config):
    """Problems the schema subset cannot express: a relatedTests `paths`, testMap `paths`/`contains` or changeSize
    `exclude`/`pairs`, fullCheckPaths, agentModelShapes or agentSignaturePatterns entry that is not a valid regex (or a pair replacement that does not fit its
    regex), an agentMap prefix that is not one folder name, an instructionLines `warn` above its `fail`, a handoff `cellHardLimit` set by the project (not 0) below its `cellLimit`, an
    ownedFiles pattern that is absolute or has a `..`."""
    errors = []
    people = (config.get("profiles") or {}).get("people") if isinstance(config.get("profiles"), dict) else None
    for key, person in (people or {}).items() if isinstance(people, dict) else ():
        if not EMAIL_HASH.match(key):
            errors.append(f"$.profiles.people: key {key[:3]}... is not the SHA-256 of an e-mail (64 hex digits); never "
                          f"write the address: python3 {HERE / 'profile.py'} assign <email> --role <role> writes the hash")
        elif isinstance(person, dict) and not (person.get("role") or person.get("profile")):
            errors.append(f"$.profiles.people.{key[:12]}...: needs a role or a profile; assign one: "
                          f"python3 {HERE / 'profile.py'} assign <email> (--role <role> | --profile <name>)")
    warn, fail = instruction_lines(config)
    if warn > fail:
        errors.append(f"$.instructionLines: warn ({warn}) must not be above fail ({fail}); lower warn or raise fail "
                      "in .claude/gw.json")
    record_path = task_record(config)["path"] if isinstance(config.get("taskRecord"), dict) else ""
    raw_path = (config.get("taskRecord") or {}).get("path") if isinstance(config.get("taskRecord"), dict) else None
    if isinstance(raw_path, str) and (raw_path.startswith("/") or ".." in posixpath.normpath(raw_path).split("/") or record_path == "."):
        errors.append(f"$.taskRecord.path: {raw_path!r} must be a folder inside the repo, relative to its root; "
                      "write it like \"docs/tasks\" in .claude/gw.json")
    sizes = handoff(config)  # only a cellHardLimit set by the project can be below cellLimit (handoff() raises the default)
    if 0 < sizes["cellHardLimit"] < sizes["cellLimit"]:
        errors.append(f"$.handoff: cellHardLimit ({sizes['cellHardLimit']}) must not be below cellLimit "
                      f"({sizes['cellLimit']}): the hard cap would fail cells the soft limit still accepts; raise "
                      "cellHardLimit, lower cellLimit, or set cellHardLimit to 0 (off) in .claude/gw.json")
    block = config.get("languages") if isinstance(config.get("languages"), dict) else {}
    for part in ("docs", "public"):
        inner = block.get(part) if isinstance(block.get(part), dict) else {}
        primary = inner.get("primary", "en")
        if isinstance(primary, str) and isinstance(inner.get("others"), list) and primary in inner["others"]:
            errors.append(f"$.languages.{part}.others: {primary!r} is already languages.{part}.primary; remove it from "
                          f"`others` in .claude/gw.json")
    agents_dir = config.get("agentsSkillsDir")
    if isinstance(agents_dir, str) and agents_dir:
        norm = posixpath.normpath(agents_dir.replace("\\", "/")).strip("/")
        reason = None
        if "\\" in agents_dir or re.match(r"^[A-Za-z]:", agents_dir):
            reason = "must be a repo-relative path with '/' separators, no backslash or drive letter"
        elif any(norm == d or norm.startswith(d + "/") for d in (".claude/skills", ".git", ".claude/gw")):
            reason = "must not be .claude/skills (the first copy), nor inside .git or .claude/gw"
        if reason:
            errors.append(f"$.agentsSkillsDir: {agents_dir!r} {reason}; use \".agents/skills\" or another folder, or "
                          "\"\" to turn it off, in .claude/gw.json")
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


PROFILE_DENIED = ("$schema", "version", "schemaVersion", "profiles", "languages", "agentsSkillsDir", "projectSkillPrefix",
                  "gitignoreStacks", "ciInstall", "ciPython", "ciNodeDirs", "ciRustDirs", "ciKeepSteps", "ciOnPush",
                  "actionlintVersion", "front")
PROFILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
EMAIL_HASH = re.compile(r"^[0-9a-f]{64}$")
EMAIL_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+$")  # E4: what profile.py accepts as an address to hash
# E4 (Q-27): an address inside free text (doctor.py): a TLD of letters that ends the word, so `prettier@3.0.0` and
# `git@github.com:org/repo` (npm specs, scp-style remotes) are not taken for addresses.
EMAIL_IN_TEXT = re.compile(r'[^@\s"]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![A-Za-z0-9:/@-])')
PROFILE_OBJECT_MSG = "must be a JSON object with the keys it changes, e.g. {\"logSize\": 5000}"


def profile_shape_problems(data, props):
    """The problems of a profile's content before it is merged (one list for apply_profiles and doctor.py): not an
    object, a key the schema (`props`) does not know, or a denied one (PROFILE_DENIED)."""
    if not isinstance(data, dict):
        return [PROFILE_OBJECT_MSG]
    problems = [f"$: unknown key '{k}' (check spelling against schema/gw.schema.json)" for k in data if k not in props]
    problems += [f"$.{k}: a profile cannot change what is installed or the config's shape (it is committed for "
                 f"everyone); change it in {CONFIG_REL} instead" for k in data if k in PROFILE_DENIED]
    return problems


def email_hash(email):
    """E4 (Q-27): the SHA-256 (hex) of an e-mail address, trimmed and in lower case: what `profiles.people` keys."""
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def in_ci():
    """Whether this runs in CI (the CI environment variable set and not false/0): CI always uses the default (Q-28)."""
    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false")


def git_email(root):
    """The `git config user.email` of `root` ("" when unset or git fails)."""
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    try:
        r = subprocess.run(["git", "-C", str(root), "config", "user.email"], capture_output=True, text=True, env=env)
    except OSError:
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def deep_merge(base, over):
    """`base` with `over` on top: objects merge key by key (deep), anything else (lists too) is replaced."""
    out = dict(base)
    for key, value in over.items():
        out[key] = deep_merge(out[key], value) if isinstance(out.get(key), dict) and isinstance(value, dict) else value
    return out


def _read_profile(root, rev, rel):
    """The text of the profile file `rel` in the working tree, or in commit `rev`; None when it is not there."""
    if not rev:
        path = Path(root) / rel
        return path.read_text(encoding="utf-8") if path.is_file() else None
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    try:
        r = subprocess.run(["git", "-C", str(root), "show", f"{rev}:{rel}"], capture_output=True, text=True, env=env)
    except OSError as exc:
        raise ConfigError(f"cannot run git to read {rel} at {rev}: {exc}")
    return r.stdout if r.returncode == 0 else None


def choose_profile(config, email):
    """The profiles that apply to `email` under the config's `profiles` block, as {"layer": "default" | "role" |
    "person", "profile": name or None, "role"?: role, "roleProfile"?: name}, plus "_chain": [names] (role first)."""
    block = config.get("profiles") if isinstance(config.get("profiles"), dict) else {}
    person = (block.get("people") or {}).get(email_hash(email)) if email else None
    if not person:
        return {"layer": "default", "profile": None, "_chain": []}
    role = person.get("role")
    chain, out = [], {}
    if role:
        roles = block.get("roles") or {}
        if role not in roles:
            raise ConfigError(f"profiles: role '{role}' is assigned but has no profile in profiles.roles; give it one: "
                              f"python3 {HERE / 'profile.py'} role {role} <profile>")
        chain.append(roles[role])
        out.update(role=role, roleProfile=roles[role], layer="role", profile=roles[role])
    if person.get("profile"):
        chain.append(person["profile"])
        out.update(layer="person", profile=person["profile"])
    if out.get("layer") == "role":
        del out["roleProfile"]
    out["_chain"] = chain
    return out


def apply_profiles(config, root, rev, schema, email=None, force=False):
    """E4: `config` (raw, already valid) with the profiles of the person (git user.email, or `email`) layered on top,
    each validated; and the choice (choose_profile, for `config.py profile`). CI and no assignment: the config as it
    is. `force` skips the CI and no-assignment shortcuts (profile.py checks a profile chain with it). Raises ConfigError
    (fail closed) for a missing, broken or invalid profile or one naming a denied key."""
    if not force and (in_ci() or not (config.get("profiles") or {}).get("people")):
        return config, {"layer": "default", "profile": None}
    choice = choose_profile(config, git_email(root) if email is None else email)
    folder = (config.get("profiles") or {}).get("dir") or schema["properties"]["profiles"]["default"]["dir"]
    props = schema.get("properties", {})
    for name in choice.pop("_chain"):
        rel = posixpath.join(folder.rstrip("/"), f"{name}.json")
        where = f"{rev}:{rel}" if rev else rel
        text = _read_profile(root, rev, rel)
        if text is None:
            raise ConfigError(f"profile '{name}' ({where}) not found; create it: python3 {HERE / 'profile.py'} new {name}")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{where}: invalid JSON at line {exc.lineno}: {exc.msg}")
        if not isinstance(data, dict):
            raise ConfigError(f"{where}: {PROFILE_OBJECT_MSG}")
        problems = profile_shape_problems(data, props)
        merged = deep_merge(config, data) if not problems else config
        problems = problems or validate(merged, schema) or semantic_errors(merged)
        if problems:
            raise ConfigError(f"{where} is invalid:\n  " + "\n  ".join(problems) +
                              f"\n  fix the profile, then check: python3 {HERE / 'config.py'} profile")
        config = merged
    return config, choice


def load(root=None, rev=None, paths_at=None, profiles=True):
    """Return the validated config with defaults, plus '_root' (Path) and '_schemaFrom' (the schemaVersion it had
    before load() migrated it in memory to SCHEMA_VERSION; an absent one is 0, a newer one fails closed). With `rev`,
    the config as that commit has it instead of the working tree's. `paths_at` (a commit) is where the old-Spanish-path fallback looks for files: a
    policy config read from the protected branch's tip still resolves the paths of the commit being pushed or
    merged, so every reader gets the same path for the same commit; an old path the tip names explicitly follows
    that commit's move to the English default (with_defaults, follow_moves). `profiles=False` skips the profile layers
    (E4: profile.py loads the project's config alone, so its commands can fix a broken profile). Raises ConfigError."""
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
        hint = ""
        if any(e.startswith("$.languages") and "does not match" in e for e in errors):
            hint = ("\n  languages: write two-letter lowercase ISO 639-1 codes (\"es\", \"en\"; `ui` also takes tags like "
                    "\"pt-BR\") in .claude/gw.json, e.g. "
                    "{\"code\": \"en\", \"docs\": {\"primary\": \"es\", \"others\": [\"en\"]}, \"public\": {\"primary\": "
                    "\"en\", \"others\": []}, \"ui\": []}, then validate: python3 " + str(HERE / "config.py") + f" --root {root} validate")
        raise ConfigError(f"{path} is invalid:\n  " + "\n  ".join(errors) + hint)
    config, choice = apply_profiles(config, root, rev, schema) if profiles else (config, {"layer": "default", "profile": None})
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
    config["_profile"] = choice  # E4: the layer and profile applied (config.py profile)
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
    sub.add_parser("agent-language", help="the agent's language for this user (~/.claude/gw.json, A12); a warning goes to stderr")
    sub.add_parser("profile", help="E4: the layer (default, role or person) and profile the config was loaded with, as JSON")
    sub.add_parser("local", help="the validated local file .claude/gw.local.json as JSON (null when absent)")
    related = sub.add_parser("related", help="relatedTests commands that apply to the files on stdin")
    related.add_argument("--kind", choices=("fast", "slow"), required=True)
    related.add_argument("--deleted-file", help="file listing, one per line, the pushed paths that no longer exist")
    scope_p = sub.add_parser("push-scope", help="'full <reason>' or 'related' for a branch push changing the files on stdin")
    scope_p.add_argument("--commits", help="file listing the push's new commits, one sha per line: a .claude/gw.json "
                                           "change then counts only by its keys (fullCheckSkipKeys, E47)")
    ac = sub.add_parser("author-check", help="exit 1 when the commit's author or committer matches authorDeny (E41)")
    ac.add_argument("--commits", help="'-': check the commits on stdin (one sha per line) instead of the next commit")
    sb = sub.add_parser("spike-branch", help="exit 0 when the branch is an exploration branch (spikeBranch, C12)")
    sb.add_argument("name", nargs="?", default="")
    sb.add_argument("--prefix", action="store_true", help="print the prefix as it is applied ('' = off) and exit 0")
    sc = sub.add_parser("spike-check", help="exit 1 when a commit on stdin comes from an exploration branch (C12)")
    sc.add_argument("--commits", required=True, help="'-': the commits on stdin, one sha per line")
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
        if args.command == "agent-language":  # an unusable project config still gets the user file's language, else en
            code, warning = agent_language({"_root": args.root or "."})
            print(f"gw config: {exc}", file=sys.stderr)
            print(code)
            return 0
        print(f"gw config: {exc}", file=sys.stderr)
        return 2
    if args.command == "validate":
        print(f"{args.rev + ':' + CONFIG_REL.as_posix() if args.rev else config['_root'] / CONFIG_REL}: valid")
        return 0
    if args.command == "root":
        print(config["_root"])
        return 0
    if args.command == "agent-language":
        code, warning = agent_language(config)
        if warning:
            print(f"gw config: {warning}", file=sys.stderr)
        print(code)
        return 0
    if args.command == "profile":
        print(json.dumps(config["_profile"], ensure_ascii=False))
        return 0
    if args.command == "local":
        try:
            print(json.dumps(load_local(config["_root"]), ensure_ascii=False))
        except ConfigError as exc:
            print(f"gw config: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.command == "author-check":
        if args.commits:
            shas = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
            code, message = commits_author_check(config["_root"], author_deny(config), shas)
            if message:
                print(f"author-check: {message}", file=sys.stderr)
            return code
        code, message = author_check(config["_root"], author_deny(config))
        if message:
            print(f"pre-commit: {message}", file=sys.stderr)
        return code
    if args.command == "spike-branch" and args.prefix:
        print(spike_prefix(config))
        return 0
    if args.command == "spike-branch":
        return 0 if is_spike_branch(args.name, spike_prefix(config)) else 1
    if args.command == "spike-check":
        shas = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
        code, message = spike_commits(config["_root"], spike_prefix(config), shas)
        if message:
            print(f"spike-check: {message}", file=sys.stderr)
        return code
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
                 selector=_section(config, "selector"),
                 recover=recover(config), handoff=handoff(config), harvest=harvest(config),
                 contextGuard=context_guard(config), modes=modes(config),
                 stopSeverity=stop_severity(config), changeSize=change_size(config),
                 retro=retro(config), redWithoutFix=red_without_fix(config), branchPrefixes=branch_prefixes(config),
                 taskRecord=task_record(config), languages=languages(config))  # inner keys fill from the schema too
    for part in args.key.split("."):
        if not isinstance(value, dict) or part not in value or part.startswith("_"):
            print(f"gw config: key '{args.key}' is not set and has no default", file=sys.stderr)
            return 2
        value = value[part]
    _print_value(value, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
