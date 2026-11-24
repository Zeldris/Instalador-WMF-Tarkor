#!/usr/bin/env python3
# galivelop-workflow v0.9.0
"""E5: the design tokens of a front-end project as data, what is generated from them and the front checks.

  python3 front.py check       # validate the tokens JSON (front.tokens in .claude/gw.json)
  python3 front.py generate    # check, then write into front.out: tokens.css, _tokens.scss,
                               # stylelint.tokens.json and playwright.projects.json
  python3 front.py run fast    # Stylelint, then Playwright without the visual tests (front.visualTag) on the main
                               # breakpoints (front.browsers.all x the main ones): what the pre-push runs
  python3 front.py run full    # Stylelint and the whole matrix, visual tests included: Linux only, or through
                               # Docker (front.dockerImage) elsewhere; otherwise it refuses (exit 3), never a false green
  python3 front.py run full --update-snapshots
                               # the same, rewriting the visual baselines: the new or changed ones (front.snapshotGlob)
                               # come back to the tree and the pinned Playwright goes into front.snapshotStamp (E78)
  python3 front.py install [--package-dir DIR] [--browsers B ...] [--matrix] [--with-deps]
                               # the npm packages of front.dir (or DIR) and, if asked, Playwright's browsers
                               # (--matrix: every browser of front.browsers.all and .main, what `run full` needs; CI)

`run` installs the packages of `front.dir`/package.json with `npm ci` in `<git common dir>/gw/front-node/<hash of
package-lock.json and package.json>/` (never a node_modules in the tree; one folder per lock, under a lock while it
installs; tests/test_front_sample.py uses the same cache) and runs from a temporary copy of the files git tracks (not
what it ignores), with node_modules linked into its `front.dir`, so the working tree is left as it was. Stylelint runs
from the copy's root on `front.stylelintFiles` (repo-relative globs; none matching a tracked file fails) with the
config of `front.dir`. Exit 3 = cannot run here (no node or npm, a browser missing, full outside Linux
without Docker); 1 = a check failed.

The tokens file is a subset of the W3C Design Tokens format (DTCG): nested groups, leaves with `$value` and `$type`
(color, dimension, fontFamily, fontWeight, number, duration; a group's `$type` is inherited by its tokens), aliases
`{group.token}` that must resolve and must not cycle. The group `front.breakpointGroup` holds the breakpoints: each
`$value` a px dimension, the viewport height in `$extensions.gw.height` (default 800). The Playwright matrix is every
breakpoint x `front.browsers.all`, plus `front.mainBreakpoints` (default: the smallest and the largest) x
`front.browsers.main` (E-16).

Output is deterministic (sorted, LF, one trailing newline): two runs give the same bytes, so a project can declare the
files in `generated` (E72) and the check compares them. Without `front.tokens` (null, the default) every subcommand
does nothing and exits 0 (`install --package-dir` excepted). Fails closed: exit 1 = the tokens are invalid, 2 = bad config, path outside the repository
or usage; each message names the command that fixes it. Root: --root, else config.find_root (this script's repo).
Python 3.8+, standard library only.
"""
import argparse
import contextlib
import fnmatch
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import shlex
import tempfile
import time
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, str(HERE))
import config  # noqa: E402  the only reader of .claude/gw.json

TYPES = ("color", "dimension", "fontFamily", "fontWeight", "number", "duration")
NUMBER = r"-?(?:\d+(?:\.\d+)?|\.\d+)"
DIMENSION = re.compile(NUMBER + r"(px|rem|em|%|vw|vh|vmin|vmax|ch|ex|pt|cm|mm|in)")
DURATION = re.compile(r"\d+(\.\d+)?(ms|s)")
PX = re.compile(r"(\d+)px")
ALIAS = re.compile(r"\{([^{}]+)\}")
# DTCG weight names as numbers: CSS font-weight only knows normal, bold, bolder, lighter and numbers
WEIGHTS = {"thin": 100, "hairline": 100, "extra-light": 200, "ultra-light": 200, "light": 300, "normal": 400,
           "regular": 400, "book": 400, "medium": 500, "semi-bold": 600, "demi-bold": 600, "bold": 700,
           "extra-bold": 800, "ultra-bold": 800, "black": 900, "heavy": 900, "extra-black": 950, "ultra-black": 950}
GENERIC_FAMILIES = ("serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif", "ui-sans-serif",
                    "ui-monospace", "ui-rounded", "emoji", "math", "fangsong")
STRICT_VALUE_RULE = "scale-unlimited/declaration-strict-value"
FILES = ("tokens.css", "_tokens.scss", "stylelint.tokens.json", "playwright.projects.json")


class Fail(Exception):
    """A user-facing failure: the message names the command that fixes it. `code` is the exit status."""

    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


HEX_PAIRS = re.compile(r"#([0-9a-fA-F])\1([0-9a-fA-F])\2([0-9a-fA-F])\3(?:([0-9a-fA-F])\4)?")


def short_hex(value):
    """`#ffffff` as `#fff` (and `#ff00ccaa` as `#f0ca`) when every pair repeats a digit: the form Stylelint's standard
    config asks for, so the generated CSS and SCSS pass it. Any other value is returned as is."""
    m = HEX_PAIRS.fullmatch(value)
    return "#" + "".join(g for g in m.groups() if g) if m else value


def command(root, sub="check"):
    return f"python3 {Path(__file__).resolve()} --root {root} {sub}"


def inside(root, rel):
    """The real path of repo-relative `rel` when it stays inside `root` (symlinks followed), else None."""
    if os.path.isabs(rel):
        return None
    base = os.path.realpath(str(root))
    full = os.path.realpath(os.path.join(base, rel))
    return Path(full) if full == base or full.startswith(base + os.sep) else None


def css_part(segment):
    """One name segment as CSS-safe text: accents folded to ASCII, lower case, anything else becomes '-' (also
    '_': Sass treats - and _ in a variable name as the same character)."""
    text = unicodedata.normalize("NFKD", segment)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def css_name(path):
    return "-".join(css_part(p) for p in path)


def dotted(path):
    return ".".join(path)


def non_finite(constant):
    raise ValueError(f"{constant} is not a JSON number (CSS and Sass reject it)")


def no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


class Tokens:
    """The parsed, validated tokens: `leaves` {dotted path: Leaf} in file order."""

    def __init__(self, data, group, root, front):
        self.root = root
        self.front = front
        self.leaves = {}
        self.fix = f"fix the tokens file, then check it with: {command(root)}"
        self.group = group
        self._walk(data, (), None)
        self._names()
        self._aliases()
        self._values()

    # -- structure ---------------------------------------------------------------------------------------------
    def _walk(self, node, path, inherited):
        kind = node.get("$type", inherited)
        children = [(k, v) for k, v in node.items() if not k.startswith("$")]
        if path and "$value" in node:
            if children:
                raise Fail(f"{dotted(path)}: a token with $value cannot also hold tokens ({children[0][0]}); {self.fix}")
            self.leaves[dotted(path)] = {"path": path, "value": node["$value"], "type": kind,
                                         "ext": node.get("$extensions")}
            return
        if path and not children:
            raise Fail(f"{dotted(path)}: a token needs $value (a group needs at least one token); {self.fix}")
        for key, child in children:
            if re.search(r"[.{}]", key):
                raise Fail(f"{dotted(path + (key,))}: a name must not contain '.', '{{' or '}}' "
                           f"(they are the alias syntax); {self.fix}")
            if not isinstance(child, dict):
                raise Fail(f"{dotted(path + (key,))}: expected a token or a group (an object), got "
                           f"{type(child).__name__}; {self.fix}")
            if "$type" in node and not isinstance(node["$type"], str):
                raise Fail(f"{dotted(path) or '(root)'}: $type must be a string; {self.fix}")
            self._walk(child, path + (key,), kind)

    def _names(self):
        seen = {}
        for name, leaf in self.leaves.items():
            for part in leaf["path"]:
                if not css_part(part):
                    raise Fail(f"{name} has no CSS-safe name ('{part}' has no letters or digits once folded to ASCII); "
                               f"rename it, then check: {command(self.root)}")
            css = css_name(leaf["path"])
            if not css[0].isalpha():
                raise Fail(f"{name}: the name '{css}' must start with a letter (a SCSS variable cannot start with a "
                           f"digit); rename it, then check: {command(self.root)}")
            if css in seen:
                raise Fail(f"{seen[css]} and {name} both become --{css}; rename one of them, then check: "
                           f"{command(self.root)}")
            seen[css] = name
            leaf["css"] = css

    # -- aliases -----------------------------------------------------------------------------------------------
    def alias_of(self, value):
        if isinstance(value, str) and ALIAS.fullmatch(value):
            return ALIAS.fullmatch(value).group(1)
        return None

    def _aliases(self):
        for name, leaf in self.leaves.items():
            value = leaf["value"]
            target = self.alias_of(value)
            if target is None and isinstance(value, str) and re.search(r"[{}]", value):
                raise Fail(f"{name}: '{value}' mixes an alias with other text; an alias must be the whole value "
                           f"({{group.token}}); {self.fix}")
            leaf["alias"] = target
        for name in self.leaves:
            self.resolve(name)

    def resolve(self, name):
        """The leaf an alias chain ends at (the token itself when it is not an alias); fails on a missing target, a
        group or a cycle."""
        chain = [name]
        current = self.leaves[name]
        while current["alias"] is not None:
            target = current["alias"]
            if target not in self.leaves:
                if any(k.startswith(target + ".") for k in self.leaves):
                    raise Fail(f"{chain[-1]}: alias {{{target}}} points to a group, not a token; {self.fix}")
                raise Fail(f"{chain[-1]}: alias {{{target}}} does not resolve (no such token); {self.fix}")
            if target in chain:
                raise Fail(f"alias cycle: {' -> '.join(chain + [target])}; break the loop, then check: "
                           f"{command(self.root)}")
            chain.append(target)
            current = self.leaves[target]
        return chain[-1]

    # -- values ------------------------------------------------------------------------------------------------
    def _values(self):
        for name, leaf in self.leaves.items():  # own and inherited types first: an alias takes its target's
            kind = leaf["type"]
            if kind is None and leaf["alias"] is not None:
                continue
            if kind is None:
                raise Fail(f"{name} has no $type (and no group above it sets one); add \"$type\" (one of "
                           f"{', '.join(TYPES)}); {self.fix}")
            if kind not in TYPES:
                raise Fail(f"{name}: $type '{kind}' is not allowed (allowed: {', '.join(TYPES)}); {self.fix}")
        for name, leaf in self.leaves.items():
            if leaf["alias"] is None:
                leaf["text"] = self.render(name, leaf["type"], leaf["value"])
                continue
            end_name = self.resolve(name)
            end = self.leaves[end_name]
            if leaf["type"] is None:
                leaf["type"] = end["type"]  # DTCG: an alias without a type has its target's
            elif end["type"] != leaf["type"]:
                raise Fail(f"{name}: type {leaf['type']} differs from the type of its alias target "
                           f"{{{leaf['alias']}}} ({end['type']}); {self.fix}")

    def unsafe(self, name, text):
        """Fails when `text` could break the CSS or SCSS written from it (a declaration ended early, a block or a
        comment opened, an interpolation, a line break, unbalanced parentheses)."""
        bad = next((c for c in text if c in ";{}\\" or ord(c) < 32 or ord(c) == 127), None)
        reason = None
        if bad is not None:
            reason = f"the character {bad!r} could end or open a declaration, a block or a line in the generated files"
        elif "/*" in text or "*/" in text or "//" in text:
            reason = "a comment marker (/* */ or //) could swallow what follows it in the generated files"
        elif text.count("(") != text.count(")"):
            reason = "its parentheses are not balanced"
        if reason:
            raise Fail(f"{name}: value {text!r} is not safe to write into CSS and SCSS: {reason}; {self.fix}")
        return text

    def render(self, name, kind, value):
        bad = f"; {self.fix}"
        if kind == "color":
            if not isinstance(value, str) or not value.strip():
                raise Fail(f"{name}: color value {value!r} must be a non-empty string{bad}")
            return short_hex(self.unsafe(name, value.strip()))
        if kind == "dimension":
            if not isinstance(value, str) or not (DIMENSION.fullmatch(value) or value in ("0", "-0")):
                raise Fail(f"{name}: dimension value {value!r} is not a number with a unit (or 0), e.g. \"16px\"{bad}")
            return value
        if kind == "duration":
            if not isinstance(value, str) or not DURATION.fullmatch(value):
                raise Fail(f"{name}: duration value {value!r} is not a number of ms or s, e.g. \"150ms\"{bad}")
            return value
        if kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise Fail(f"{name}: number value {value!r} must be a finite JSON number{bad}")
            return str(int(value)) if float(value).is_integer() else repr(float(value))
        if kind == "fontWeight":
            if isinstance(value, str) and value in WEIGHTS:
                return str(WEIGHTS[value])
            if (not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
                    and float(value).is_integer() and 1 <= value <= 1000):
                return str(int(value))
            raise Fail(f"{name}: fontWeight value {value!r} must be a whole number from 1 to 1000 or a name "
                       f"like \"bold\" ({', '.join(sorted(WEIGHTS))}){bad}")
        families = value if isinstance(value, list) else [value]  # fontFamily
        if not families or not all(isinstance(f, str) and f.strip() for f in families):
            raise Fail(f"{name}: fontFamily value {value!r} must be a name or a non-empty list of names{bad}")
        return ", ".join(self._family(self.unsafe(name, f.strip())) for f in families)

    @staticmethod
    def _family(text):
        if text in GENERIC_FAMILIES or re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", text):
            return text
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

    # -- breakpoints -------------------------------------------------------------------------------------------
    def breakpoints(self):
        """[(name, width, height)] sorted by width then name; fails when a breakpoint is not a px dimension."""
        out = []
        prefix = self.group + "."
        for name, leaf in self.leaves.items():
            if not name.startswith(prefix):
                continue
            end = self.leaves[self.resolve(name)]
            match = PX.fullmatch(end["value"]) if isinstance(end["value"], str) and end["type"] == "dimension" else None
            if not match or int(match.group(1)) < 1:
                raise Fail(f"{name} must be a px dimension (a whole number of px, e.g. \"768px\"), got "
                           f"{end['value']!r}; {self.fix}")
            height = self.front["defaultHeight"]
            ext = leaf["ext"]
            gw = ext.get("gw") if isinstance(ext, dict) else None
            if isinstance(gw, dict) and "height" in gw:
                height = gw["height"]
                if isinstance(height, bool) or not isinstance(height, int) or height < 1:
                    raise Fail(f"{name}: $extensions.gw.height must be a positive integer, got {height!r}; {self.fix}")
            out.append((css_name(leaf["path"][len(self.group.split(".")):]), int(match.group(1)), height))
        return sorted(out, key=lambda b: (b[1], b[0]))


def load_tokens(root, front):
    """The validated Tokens of `front.tokens`, or None when the project has no front."""
    rel = front["tokens"]
    if rel is None:
        return None
    path = inside(root, rel)
    if path is None:
        raise Fail(f"front.tokens {rel!r} is outside the repository; set a repo-relative path in .claude/gw.json", 2)
    shown = rel
    if not path.is_file():
        raise Fail(f"{shown} not found; create it or set front.tokens in .claude/gw.json (null = no front), "
                   f"then run: {command(root)}")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise Fail(f"{shown}: cannot read it as UTF-8 ({exc}); fix it, then run: {command(root)}")
    if not text.strip():
        raise Fail(f"{shown} is empty; add the tokens (a JSON object), then run: {command(root)}")
    try:
        data = json.loads(text, object_pairs_hook=no_duplicates, parse_constant=non_finite)
    except json.JSONDecodeError as exc:
        raise Fail(f"{shown}: invalid JSON at line {exc.lineno}: {exc.msg}; fix it, then run: {command(root)}")
    except ValueError as exc:
        raise Fail(f"{shown}: {exc}; fix it, then run: {command(root)}")
    if not isinstance(data, dict):
        raise Fail(f"{shown}: the root must be a JSON object (groups of tokens), got {type(data).__name__}; "
                   f"fix it, then run: {command(root)}")
    group = front["breakpointGroup"]
    node = data
    for part in group.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    fix = f"fix {shown} or front.breakpointGroup, then run: {command(root)}"
    if not isinstance(node, dict):
        raise Fail(f"breakpoint group '{group}' not found in {shown}; {fix}")
    if not _has_leaf(node):
        raise Fail(f"breakpoint group '{group}' has no breakpoints (tokens with $value); {fix}")
    tokens = Tokens(data, group, root, front)
    marks = tokens.breakpoints()
    known = {b[0] for b in marks}
    for name in front["mainBreakpoints"]:
        if css_part(name) not in known:
            raise Fail(f"front.mainBreakpoints names '{name}', which is not a breakpoint of '{group}' "
                       f"(known: {', '.join(sorted(known))}); fix .claude/gw.json, then run: {command(root)}")
    return tokens


def _has_leaf(node):
    return any(isinstance(v, dict) and ("$value" in v or _has_leaf(v)) for k, v in node.items() if not k.startswith("$"))


# -- output ----------------------------------------------------------------------------------------------------------
def depth(tokens, leaf):
    """How many aliases lead from `leaf` to a plain value (0 = a plain value)."""
    steps = 0
    while leaf["alias"] is not None:
        leaf = tokens.leaves[leaf["alias"]]
        steps += 1
    return steps


def declarations(tokens, css):
    """[(name, value)]. CSS: sorted by name (var() resolves late). SCSS: a variable must exist before another one
    uses it, so ordered by alias depth (plain values first), then by name."""
    rows = []
    for leaf in tokens.leaves.values():
        if leaf["alias"] is not None:
            target = tokens.leaves[leaf["alias"]]["css"]
            value = f"var(--{target})" if css else f"${target}"
        else:
            value = leaf["text"]
        rows.append((0 if css else depth(tokens, leaf), leaf["css"], value))
    return [(name, value) for _depth, name, value in sorted(rows)]


def render_css(tokens, source):
    lines = [f"/* Generated by scripts/front.py from {source}: do not edit. */", ":root {"]
    lines += [f"  --{name}: {value};" for name, value in declarations(tokens, True)]
    return "\n".join(lines + ["}"]) + "\n"


def render_scss(tokens, source):
    lines = [f"// Generated by scripts/front.py from {source}: do not edit."]
    lines += [f"${name}: {value};" for name, value in declarations(tokens, False)]
    return "\n".join(lines) + "\n"


def as_json(data):
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def stylelint_fragment(front):
    """Colors, spacing and sizes must be variables (var(--x), $x): functions with literals (rgb(...), calc(13px)) are
    reported too (ignoreFunctions false), and shorthands are expanded so `background: #f00` is checked."""
    rules = front["stylelint"]
    props = rules["colorProperties"] + rules["spacingProperties"] + rules["sizeProperties"]
    options = {"disableFix": True, "expandShorthand": rules["expandShorthand"], "ignoreFunctions": False,
               "ignoreValues": rules["ignoreValues"]}
    return {"plugins": ["stylelint-declaration-strict-value"], "rules": {STRICT_VALUE_RULE: [props, options]}}


def playwright_projects(tokens, front):
    marks = tokens.breakpoints()
    main = set(main_breakpoints(tokens, front))
    out = []
    for name, width, height in marks:
        browsers = list(front["browsers"]["all"])
        if name in main:
            browsers += [b for b in front["browsers"]["main"] if b not in browsers]
        for browser in browsers:
            out.append({"name": f"{browser}-{name}", "browser": browser,
                        "viewport": {"width": width, "height": height}})
    return out


def generated_files(tokens, front):
    source = front["tokens"]
    return {"tokens.css": render_css(tokens, source), "_tokens.scss": render_scss(tokens, source),
            "stylelint.tokens.json": as_json(stylelint_fragment(front)),
            "playwright.projects.json": as_json(playwright_projects(tokens, front))}


def write_files(root, front, files):
    out = inside(root, front["out"])
    if out is None:
        raise Fail(f"front.out {front['out']!r} is outside the repository; set a repo-relative folder in "
                   f".claude/gw.json", 2)
    try:
        out.mkdir(parents=True, exist_ok=True)
        for name, text in sorted(files.items()):
            target = out / name
            data = text.encode("utf-8")
            if not target.is_file() or target.read_bytes() != data:
                tmp = out / f".{name}.tmp"
                try:
                    tmp.write_bytes(data)
                    os.replace(str(tmp), str(target))
                finally:  # a failed write or replace must not leave a stray file in a folder `generated` compares
                    if tmp.exists():
                        tmp.unlink()
    except OSError as exc:
        raise Fail(f"cannot write {front['out']}: {exc}; fix front.out in .claude/gw.json", 2)
    return [f"{front['out'].rstrip('/')}/{name}" for name in sorted(files)]


# -- run (trozo 3) ---------------------------------------------------------------------------------------------------
def run_command(root, mode):
    return f"python3 {Path(__file__).resolve()} --root {root} run {mode}"


def main_breakpoints(tokens, front):
    """The names of the main breakpoints: front.mainBreakpoints, else the smallest and the largest."""
    marks = tokens.breakpoints()
    main = {css_part(n) for n in front["mainBreakpoints"]} or {marks[0][0], marks[-1][0]}
    return [name for name, _w, _h in marks if name in main]


def fast_projects(tokens, front):
    """`run fast`: every browser of front.browsers.all on the main breakpoints only."""
    return [f"{browser}-{name}" for name in main_breakpoints(tokens, front) for browser in front["browsers"]["all"]]


def matrix_browsers(front):
    out = list(front["browsers"]["all"])
    return out + [b for b in front["browsers"]["main"] if b not in out]


def package_files(pkg):
    """The bytes that decide an install: package-lock.json then package.json (the stamp tests/test_front_sample.py
    compares too)."""
    return (pkg / "package-lock.json").read_bytes() + (pkg / "package.json").read_bytes()


def node_cache(root, pkg):
    """<git common dir>/gw/front-node/<hash of the package files>: shared by the main checkout and the pre-push's
    temporary worktrees, one folder per package-lock, so a branch with another lock never rewrites the node_modules a
    run of this one is using."""
    common = config.git_common_dir(root)
    if common is None:
        raise Fail(f"{root} has no git directory for the npm cache; run it inside the repository: {run_command(root, 'fast')}", 2)
    return common / "gw" / "front-node" / hashlib.sha256(package_files(pkg)).hexdigest()[:16]


def package_dir(root, front, given=None):
    rel = given if given is not None else front["dir"]
    path = inside(root, rel)
    if path is None or not (path / "package.json").is_file():
        where = "--package-dir" if given is not None else "front.dir in .claude/gw.json"
        raise Fail(f"no package.json in {rel!r}; copy the workflow's templates/front there (README.md) or fix {where}", 2)
    return path


def pinned_playwright(pkg):
    """The @playwright/test version pinned in <pkg>/package.json, or None."""
    try:
        data = json.loads((pkg / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for key in ("devDependencies", "dependencies"):
        version = (data.get(key) or {}).get("@playwright/test") if isinstance(data, dict) else None
        if isinstance(version, str) and re.fullmatch(r"\d+\.\d+\.\d+", version):
            return version
    return None


def need_node(fix):
    missing = [tool for tool in ("node", "npm") if not shutil.which(tool)]
    if missing:
        raise Fail(f"{' and '.join(missing)} not found; install node 22+ (with npm), then run: {fix}", 3)


@contextlib.contextmanager
def locked(cache):
    cache.mkdir(parents=True, exist_ok=True)
    with open(str(cache / ".lock"), "w") as handle:
        try:
            import fcntl
        except ImportError:  # no flock (Windows): one run at a time is then the user's business
            yield
            return
        fcntl.flock(handle, fcntl.LOCK_EX)  # one npm ci at a time; the others wait for it
        yield


def prune_caches(current, days):
    """front.nodeCacheDays: removes the other caches of front-node/ (16-hex names) whose stamp (touched on every use)
    or, without one, folder is older than that many days, each under its own lock taken without waiting (an install
    in progress holds it, so its cache stays). 0 = never; without flock (Windows), nothing is removed."""
    if days <= 0:
        return
    try:
        import fcntl
    except ImportError:
        return
    limit = time.time() - days * 86400
    for other in sorted(current.parent.iterdir()):
        if other == current or other.is_symlink() or not other.is_dir() or not re.fullmatch(r"[0-9a-f]{16}", other.name):
            continue
        stamp = other / "installed-from"
        try:
            used = (stamp if stamp.exists() else other).stat().st_mtime
            if used > limit:
                continue
            with open(str(other / ".lock"), "a") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                shutil.rmtree(str(other), True)
                print(f"front: removed the package cache {other} (unused for {days}+ days, front.nodeCacheDays)")
        except OSError:  # busy (locked) or gone: left alone
            continue


def install_packages(pkg, root, fix, keep_days=0):
    """npm ci of <pkg> into its cache (node_cache), skipped when the stamp `installed-from` holds the same package
    files (the stamp is then touched: it dates the last use for prune_caches). The stamp goes before anything is
    removed and is written only after a good npm ci: a failed install never leaves a stamp over a half node_modules."""
    lock_file = pkg / "package-lock.json"
    if not lock_file.is_file():
        raise Fail(f"no package-lock.json next to {pkg / 'package.json'}; create it with npm install there and commit "
                   f"it, then run: {fix}", 2)
    wanted = package_files(pkg)
    cache = node_cache(root, pkg)
    with locked(cache):
        stamp = cache / "installed-from"
        if stamp.is_file() and stamp.read_bytes() == wanted and (cache / "node_modules" / ".bin").is_dir():
            os.utime(str(stamp))
            prune_caches(cache, keep_days)
            return cache / "node_modules"
        need_node(fix)
        if stamp.exists():
            stamp.unlink()
        shutil.copy(str(pkg / "package.json"), str(cache / "package.json"))
        shutil.copy(str(lock_file), str(cache / "package-lock.json"))
        shutil.rmtree(str(cache / "node_modules"), True)
        print(f"front: npm ci in {cache}", flush=True)
        done = subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=str(cache), stdin=subprocess.DEVNULL)
        if done.returncode != 0:
            raise Fail(f"npm ci failed in {cache} (above); fix package.json or the network, then run: {fix}", 3)
        stamp.write_bytes(wanted)
    prune_caches(cache, keep_days)
    return cache / "node_modules"


def browsers_path(modules):
    """Where Playwright looks for its browsers, as it resolves it: PLAYWRIGHT_BROWSERS_PATH (0 = inside
    playwright-core), else the per-platform cache folder (Linux: $XDG_CACHE_HOME or ~/.cache; macOS:
    ~/Library/Caches; Windows: %LOCALAPPDATA%) plus ms-playwright."""
    given = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if given == "0":
        return modules / "playwright-core" / ".local-browsers"
    if given:
        return Path(given)
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        base = home / "Library" / "Caches"
    elif system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    return base / "ms-playwright"


def missing_browsers(modules, wanted):
    """The browsers of `wanted` whose build, as the installed Playwright asks for it, is not in the browsers folder.
    A build counts when its folder exists for `revision` or for any of its `revisionOverrides` (the host-specific
    builds; which one applies is Playwright's call, so none of them is taken for missing)."""
    try:
        data = json.loads((modules / "playwright-core" / "browsers.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return list(wanted)
    path = browsers_path(modules)
    missing = []
    for browser in wanted:
        entries = [e for e in data.get("browsers", []) if e.get("name") == browser
                   or (browser == "chromium" and e.get("name") == "chromium-headless-shell")]

        def present(entry):
            builds = [entry.get("revision")] + list((entry.get("revisionOverrides") or {}).values())
            folder = entry["name"].replace("-", "_")
            return any(r and (path / f"{folder}-{r}").is_dir() for r in builds)

        if not entries or not all(present(e) for e in entries):
            missing.append(browser)
    return missing


def docker_ready():
    docker = shutil.which("docker")
    if not docker:
        return None
    done = subprocess.run([docker, "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    return docker if done.returncode == 0 else None


def tracked_files(root):
    """The files git tracks in `root` (the pushed commit's checkout, or the working tree): what is ignored or
    untracked never reaches the checks."""
    done = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        raise Fail(f"cannot list the files git tracks in {root}; check the repository: git -C {root} ls-files", 2)
    return [f for f in done.stdout.decode("utf-8", "surrogateescape").split("\0") if f]


def copy_tracked(root, files, dest):
    """Copy the tracked `files` of `root` into `dest` (symlinks as symlinks; a file deleted in the tree is skipped)."""
    for rel in files:
        src = Path(root) / rel
        target = dest / rel
        if src.is_symlink():
            target.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(os.readlink(str(src)), str(target))
        elif src.is_file():  # a submodule (a folder) or a file deleted in the tree is skipped
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(target))


def glob_regex(pattern):
    """A Stylelint (fast-glob) pattern as a regex on repo paths: `**/` any folders, `*` and `?` within a name,
    `{a,b}` alternatives."""
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "{":
            end = pattern.find("}", i)
            if end > i:
                out.append("(?:" + "|".join(re.escape(x) for x in pattern[i + 1:end].split(",")) + ")")
                i = end + 1
                continue
            out.append(re.escape(c))
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out))


STYLELINT_CONFIGS = (".stylelintrc.json", ".stylelintrc", ".stylelintrc.yaml", ".stylelintrc.yml", ".stylelintrc.js",
                     ".stylelintrc.cjs", ".stylelintrc.mjs", "stylelint.config.js", "stylelint.config.cjs",
                     "stylelint.config.mjs")


def stylelint_config(pkg):
    """The Stylelint config of front.dir, passed with --config so files outside it (src/ next to a front-tests/) use
    it too; None = Stylelint looks for one itself."""
    for name in STYLELINT_CONFIGS:
        if (pkg / name).is_file():
            return name
    return None


def step(cmd, cwd, what, fix):
    print(f"front: {what}: {' '.join(cmd)}", flush=True)
    done = subprocess.run(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        raise Fail(f"{what} failed (exit {done.returncode}, above); fix it and run again: {fix}", 1)


def playwright_args(tokens, front, mode, update=False):
    args = ["test", "--trace", "off", "--forbid-only", "--reporter", "line"] + (["--update-snapshots"] if update else [])
    if mode == "fast":
        args += ["--grep-invert", front["visualTag"]]
        for name in fast_projects(tokens, front):
            args += ["--project", name]
    return args


def snapshot_files(work):
    """The regular files of the copy `work` by repo-relative path (what Playwright may have written), outside
    node_modules."""
    found = {}
    for dirpath, dirnames, names in os.walk(str(work)):
        dirnames[:] = [d for d in dirnames if d != "node_modules"]
        for name in names:
            path = Path(dirpath) / name
            if path.is_file() and not path.is_symlink():
                found[path.relative_to(work).as_posix()] = path
    return found


def bring_back_snapshots(root, front, work, version):
    """E78: the baselines (front.snapshotGlob) that the run wrote or changed in the copy go back to the tree, and the
    pinned Playwright into front.snapshotStamp. Nothing else of the copy comes back, and nothing is committed."""
    updated = []
    for rel, path in sorted(snapshot_files(work).items()):
        if not fnmatch.fnmatch(rel, front["snapshotGlob"]):
            continue
        target = Path(root) / rel
        data = path.read_bytes()
        if target.is_file() and target.read_bytes() == data:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        updated.append(rel)
        print(f"front: updated {rel}")
    stamp = Path(root) / front["snapshotStamp"]
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(version + "\n", encoding="utf-8")
    print(f"front: {len(updated)} baseline(s) updated, Playwright {version} written into {front['snapshotStamp']}; "
          "review them with git diff (and git status for new ones) before the commit")


def run(root, front, tokens, mode, update=False):
    """Stylelint from the root of a copy of the tracked files (front.stylelintFiles are repo-relative globs, with the
    config of front.dir), then Playwright from the copy's front.dir. With `update` (`run full --update-snapshots`,
    E78) Playwright rewrites the baselines and bring_back_snapshots copies them to the tree."""
    fix = run_command(root, mode) + (" --update-snapshots" if update else "")
    if update and mode != "full":
        raise Fail(f"--update-snapshots only goes with `run full` (baselines are only valid from Linux or Docker, "
                   f"E-9); run: {run_command(root, 'full')} --update-snapshots", 2)
    pkg = package_dir(root, front)
    version = pinned_playwright(pkg)
    if update and version is None:
        raise Fail(f"no exact @playwright/test version in {pkg / 'package.json'}, so the baselines cannot be stamped "
                   f"in {front['snapshotStamp']}; pin it (templates/front/package.json), then run: {fix}", 2)
    rel_dir = pkg.relative_to(os.path.realpath(str(root))).as_posix() if pkg != Path(os.path.realpath(str(root))) else "."
    docker = None
    if mode == "full" and platform.system() != "Linux":
        docker = docker_ready()
        if docker is None:
            raise Fail(f"`run full` compares screenshots, which only match on Linux (E-9), and this is "
                       f"{platform.system()} without a running Docker: nothing was checked. Start Docker and run it "
                       f"again ({fix}), or let the CI on Linux run it; here: {run_command(root, 'fast')}", 3)
    files = tracked_files(root)
    globs = front["stylelintFiles"]
    if not any(glob_regex(g).fullmatch(f) for g in globs for f in files):
        raise Fail(f"front.stylelintFiles ({', '.join(globs)}) matches no file git tracks, so Stylelint would check "
                   f"nothing; set repo-relative globs of the project's CSS in .claude/gw.json, then run: {fix}", 2)
    config_name = stylelint_config(pkg)
    lint_args = (["--config", f"{rel_dir}/{config_name}"] if config_name else []) + list(globs)
    tests = playwright_args(tokens, front, mode, update)
    with tempfile.TemporaryDirectory(prefix="gw-front-run-") as tmp:
        work = Path(tmp) / "work"
        work.mkdir()
        copy_tracked(os.path.realpath(str(root)), files, work)
        work_pkg = work / rel_dir
        if docker:
            if version is None:
                raise Fail(f"no exact @playwright/test version in {pkg / 'package.json'} for the Docker image; pin it "
                           f"(templates/front/package.json), then run: {fix}", 2)
            image = front["dockerImage"].replace("{playwright}", version)
            inner = shlex.quote(f"/work/{rel_dir}")
            script = " && ".join([
                f"cd {inner}", "npm ci --no-audit --no-fund", "cd /work",
                " ".join(shlex.quote(a) for a in [f"{rel_dir}/node_modules/.bin/stylelint", *lint_args]),
                f"cd {inner}", "npx playwright " + " ".join(shlex.quote(a) for a in tests)])
            step([docker, "run", "--rm", "--ipc=host", "-v", f"{work}:/work", "-w", "/work", image, "bash", "-c", script],
                 work, f"{mode} checks in Docker ({image})", fix)
        else:
            modules = install_packages(pkg, root, fix, front["nodeCacheDays"])
            need_node(fix)
            wanted = front["browsers"]["all"] if mode == "fast" else matrix_browsers(front)
            missing = missing_browsers(modules, wanted)
            if missing:
                raise Fail(f"Playwright's {', '.join(missing)} not installed; install it with: python3 "
                           f"{Path(__file__).resolve()} --root {root} install --browsers {' '.join(missing)}, "
                           f"then run: {fix}", 3)
            os.symlink(str(modules), str(work_pkg / "node_modules"))
            binary = modules / ".bin"
            step([str(binary / "stylelint"), *lint_args], work, "stylelint", fix)
            step([str(binary / "playwright"), *tests], work_pkg, f"playwright ({mode})", fix)
        if update:
            bring_back_snapshots(os.path.realpath(str(root)), front, work, version)
    print(f"front: run {mode} passed")
    return 0


def install(root, front, package, browsers, with_deps):
    pkg = package_dir(root, front, package)
    fix = f"python3 {Path(__file__).resolve()} --root {root} install" + (f" --package-dir {package}" if package else "")
    modules = install_packages(pkg, root, fix, front["nodeCacheDays"])
    if browsers:
        need_node(fix)
        cmd = [str(modules / ".bin" / "playwright"), "install", *(["--with-deps"] if with_deps else []), *browsers]
        step(cmd, pkg, "playwright install", fix)
    print(f"front: packages of {pkg} installed in {modules}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="front.py", description=__doc__.split("\n")[0])
    parser.add_argument("--root", help="project root (default: the repo of this script)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="validate the tokens JSON")
    sub.add_parser("generate", help="check, then write the generated files into front.out")
    run_p = sub.add_parser("run", help="the front checks: fast (pre-push) or full (CI, Linux or Docker)")
    run_p.add_argument("mode", choices=("fast", "full"))
    run_p.add_argument("--update-snapshots", action="store_true",
                       help="full only: rewrite the visual baselines, copy them to the tree and stamp the pinned "
                            "Playwright in front.snapshotStamp (E78)")
    inst = sub.add_parser("install", help="npm packages (outside the tree) and, if asked, Playwright's browsers")
    inst.add_argument("--package-dir", help="repo-relative folder with package.json (default front.dir; works "
                                           "without front.tokens)")
    inst.add_argument("--browsers", nargs="+", choices=("chromium", "firefox", "webkit"), default=[])
    inst.add_argument("--matrix", action="store_true", help="also every browser of front.browsers.all and .main "
                                                               "(what run full needs; E7)")
    inst.add_argument("--with-deps", action="store_true", help="also the system libraries (needs sudo; CI)")
    args = parser.parse_args(argv)
    try:
        try:
            root = config.find_root(args.root)
            front = config.front(config.load(root))
        except config.ConfigError as exc:
            raise Fail(str(exc), 2)
        if args.cmd == "install" and (args.package_dir or front["tokens"] is not None):
            browsers = args.browsers + (front["browsers"]["all"] + front["browsers"]["main"] if args.matrix else [])
            return install(root, front, args.package_dir, list(dict.fromkeys(browsers)), args.with_deps)
        tokens = load_tokens(root, front)
        if tokens is None:
            return 0
        if args.cmd == "check":
            print(f"front: {front['tokens']} is valid ({len(tokens.leaves)} tokens, "
                  f"{len(tokens.breakpoints())} breakpoints)")
            return 0
        if args.cmd == "run":
            return run(root, front, tokens, args.mode, args.update_snapshots)
        if args.cmd == "install":
            return 0  # not reached: with tokens it installed above
        for path in write_files(root, front, generated_files(tokens, front)):
            print(f"front: wrote {path}")
        return 0
    except Fail as exc:
        print(f"front.py: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
