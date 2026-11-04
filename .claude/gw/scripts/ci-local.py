#!/usr/bin/env python3
# galivelop-workflow v0.5.0
"""Runs the project's GitHub Actions CI on this machine, for when GitHub does not start it (no Actions quota, no
runners), and with --record records the result in the config's `ciLocalLog` (default docs/records/ci-local.md).
The PR hook (review-before-main.sh) takes a committed green record as the CI of a PR whose CI never started; a CI
that started and failed is never replaced this way. Recording one is the person's call ("checked only locally").

  python3 ci-local.py [--event pull_request|push] [--plan] [--record] [--root PATH]

What runs: the workflows of `ciLocalWorkflows`, or else every .github/workflows/*.yml|yaml triggered by the event
(default pull_request, the one a PR merge waits for; branch and path filters honoured), on the working tree as it is.
Of each one, the jobs whose `runs-on` is this machine's OS (ubuntu/linux on Linux, macos on macOS), one per matrix
combination, in `needs` order. Each `run:` step goes through its shell (bash, sh or python) in its working-directory,
with the workflow, job and step `env`, `${{ }}` replaced, and CI=true plus the usual GITHUB_* / RUNNER_* variables
(GITHUB_BASE_REF = protectedBranch for a pull_request); GITHUB_ENV and GITHUB_PATH carry over between steps. A
failing step stops its job (later steps run only with always() or failure()); `continue-on-error` is honoured.
Not run, on purpose: `uses:` steps and system-package installs (sudo, apt-get, brew, choco...): this machine is
expected to have the toolchain already. Not covered, and listed as such: jobs for another OS, with `services` or a
`container`, and anything whose `if:` or `${{ }}` this script cannot evaluate (secrets, steps.*, needs.*, fromJSON...).
Green = every step that ran passed, at least one ran and no job was left out for lack of evaluation (a matrix from
an expression runs once, with this machine's toolchain; other-OS, `services` and `container` jobs stay only listed). Exit 0 green, 1 not green, 2 no workflow or a bad config.
The YAML reader covers what workflows use (block maps and lists, flow [..] {..}, quotes, | and > scalars, comments);
no anchors or tags. Python 3.8+, stdlib only. Root from this script's path (config.find_root).
"""
import argparse
import datetime
import fnmatch
import hashlib
import itertools
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True  # no __pycache__: it would make the tree look dirty
import config  # noqa: E402  the only reader of .claude/gw.json

SYSTEM_PACKAGES = re.compile(r"(^|[\s;&|(])(sudo|apt-get|apt|yum|dnf|apk|brew|choco|winget|snap)\s")
HEADER = ("# CI run locally\n\n"
          "Written by `ci-local.py --record`: one line per local run of the GitHub CI (green or red, with what it\n"
          "did not cover). The PR hook takes a green line whose commit has only content after it as the CI that\n"
          "GitHub did not start; the person confirms it first (\"checked only locally\").\n\n")


class YamlError(Exception):
    pass


class Unknown(Exception):
    """An expression this script cannot evaluate: the job or step is not covered."""


# ---- YAML subset ---------------------------------------------------------------------------------------------------
KEY = re.compile(r"""("(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^\s'"#\[\]{},&*!|>%@`-][^:#]*?|-[^\s:#][^:#]*?)\s*:(?:\s+|$)""")


def strip_comment(line):
    quote = None
    for i, c in enumerate(line):
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"" and (i == 0 or line[i - 1] in " \t:-[{,"):
            quote = c
        elif c == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def unquote(s):
    if len(s) >= 2 and s[0] == s[-1] == "'":
        return s[1:-1].replace("''", "'")
    if len(s) >= 2 and s[0] == s[-1] == '"':
        try:
            return json.loads(s)
        except ValueError:
            return s[1:-1]
    return s


def plain(s):
    s = s.strip()
    if s[:1] in ("'", '"'):
        return unquote(s)
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    if s in ("", "~", "null", "Null", "NULL"):
        return None
    if re.fullmatch(r"[-+]?\d+", s):
        return int(s)
    if re.fullmatch(r"[-+]?\d*\.\d+", s):
        return float(s)
    return s


def flow(s):
    """A flow collection ([a, b] or {a: b}) or a plain scalar."""
    pos = [0]

    def ws():
        while pos[0] < len(s) and s[pos[0]] in " \t\n":
            pos[0] += 1

    def item(stop):
        ws()
        if pos[0] < len(s) and s[pos[0]] in "[{":
            return coll()
        start, quote = pos[0], None
        while pos[0] < len(s):
            c = s[pos[0]]
            if quote:
                if c == quote:
                    quote = None
            elif c in "'\"" and pos[0] == start:
                quote = c
            elif c in stop:
                break
            pos[0] += 1
        return s[start:pos[0]].strip()

    def coll():
        opening = s[pos[0]]
        closing = "]" if opening == "[" else "}"
        pos[0] += 1
        out = [] if opening == "[" else {}
        while True:
            ws()
            if pos[0] >= len(s):
                raise YamlError(f"unclosed {opening} in {s!r}")
            if s[pos[0]] == closing:
                pos[0] += 1
                return out
            if opening == "[":
                value = item(",]")
                out.append(value if isinstance(value, (list, dict)) else plain(value))
            else:
                key = item(":,}")
                if isinstance(key, (list, dict)):
                    raise YamlError(f"a collection as a key in {s!r}")
                if pos[0] < len(s) and s[pos[0]] == ":":
                    pos[0] += 1
                    value = item(",}")
                    out[str(plain(key))] = value if isinstance(value, (list, dict)) else plain(value)
                else:
                    out[str(plain(key))] = None
            ws()
            if pos[0] < len(s) and s[pos[0]] == ",":
                pos[0] += 1

    if s[:1] in "[{":
        value = coll()
        ws()
        if pos[0] != len(s):
            raise YamlError(f"text after the end of {s!r}")
        return value
    return plain(s)


class Yaml:
    def __init__(self, text):
        self.lines = text.splitlines()
        self.i = 0

    def error(self, what):
        raise YamlError(f"line {self.i + 1}: {what}")

    def peek(self):
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if "\t" in line[:len(line) - len(line.lstrip())]:
                self.error("tab in indentation")
            s = strip_comment(line).strip()
            if s and s not in ("---", "..."):
                return len(line) - len(line.lstrip(" ")), s
            self.i += 1
        return None

    def node(self, indent):
        p = self.peek()
        if p is None or p[0] < indent:
            return None
        if p[1] == "-" or p[1].startswith("- "):
            return self.seq(p[0])
        if KEY.match(p[1]):
            return self.map(p[0])
        self.i += 1
        return self.scalar(p[1], p[0] - 1)

    def seq(self, ind):
        out = []
        while True:
            p = self.peek()
            if p is None or p[0] < ind:
                return out
            if p[0] > ind or not (p[1] == "-" or p[1].startswith("- ")):
                self.error("bad indentation in a list")
            rest = p[1][1:].lstrip()
            if not rest:
                self.i += 1
                out.append(self.node(ind + 1))
            elif KEY.match(rest) or rest.startswith("- "):
                line = self.lines[self.i]
                self.lines[self.i] = line[:ind] + " " + line[ind + 1:]  # the item's map starts after "- "
                out.append(self.node(ind + 1))
            else:
                self.i += 1
                out.append(self.scalar(rest, ind))

    def map(self, ind):
        out = {}
        while True:
            p = self.peek()
            if p is None or p[0] < ind:
                return out
            if p[0] > ind:
                self.error("bad indentation")
            m = KEY.match(p[1])
            if not m:
                if p[1] == "-" or p[1].startswith("- "):
                    return out  # a list item of the parent list
                self.error(f"expected 'key: value', found {p[1]!r}")
            key, rest = str(plain(m.group(1))), p[1][m.end():].strip()
            self.i += 1
            if not rest:
                nxt = self.peek()
                if nxt and nxt[0] > ind:
                    out[key] = self.node(nxt[0])
                elif nxt and nxt[0] == ind and (nxt[1] == "-" or nxt[1].startswith("- ")):
                    out[key] = self.seq(ind)
                else:
                    out[key] = None
            else:
                out[key] = self.scalar(rest, ind)

    def scalar(self, rest, parent):
        """The value `rest` (already read) of a key or list item at column `parent`; block scalars and multi-line
        plain or flow values read their continuation lines (indented past `parent`)."""
        if rest[0] in "|>":
            return self.block(rest, parent)
        while rest[0] in "[{" and rest.count(rest[0]) > rest.count("]" if rest[0] == "[" else "}"):
            p = self.peek()
            if p is None or p[0] <= parent:
                break
            rest += " " + p[1]
            self.i += 1
        if rest[0] not in "[{'\"":
            while True:
                p = self.peek()
                if p is None or p[0] <= parent:
                    break
                rest += " " + p[1]
                self.i += 1
        return flow(rest)

    def block(self, header, parent):
        m = re.fullmatch(r"([|>])([-+]?)(\d?)([-+]?)", header)
        if not m:
            self.error(f"bad block scalar header {header!r}")
        style, chomp = m.group(1), m.group(2) or m.group(4)
        raw = []
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if line.strip() and len(line) - len(line.lstrip(" ")) <= parent:
                break
            raw.append(line)
            self.i += 1
        while raw and not raw[-1].strip():
            raw.pop()
        width = int(m.group(3)) + parent if m.group(3) else min(
            (len(x) - len(x.lstrip(" ")) for x in raw if x.strip()), default=0)
        lines = [x[width:] if x.strip() else "" for x in raw]
        if style == "|":
            text = "\n".join(lines)
        else:
            text, prev_blank = "", True
            for x in lines:
                if not x:
                    text += "\n"
                    prev_blank = True
                elif x.startswith((" ", "\t")):
                    text += ("" if prev_blank or text.endswith("\n") else "\n") + x + "\n"
                    prev_blank = True
                else:
                    text += ("" if prev_blank or text.endswith("\n") else " ") + x
                    prev_blank = False
            text = text.rstrip("\n")
        return text + ("" if chomp == "-" or not text else "\n")


def load_yaml(text):
    y = Yaml(text)
    value = y.node(0)
    if y.peek() is not None:
        y.error("unexpected text")
    return value


# ---- ${{ }} expressions --------------------------------------------------------------------------------------------
TOKEN = re.compile(r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<str>'(?:[^']|'')*')|(?P<op>==|!=|<=|>=|&&|\|\||[!<>().,\[\]*])"
                   r"|(?P<id>[A-Za-z_][A-Za-z0-9_-]*))")


def tokens(text):
    out, pos = [], 0
    text = text.strip()
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise Unknown(f"cannot read the expression {text!r}")
        kind = m.lastgroup
        value = m.group(kind)
        out.append((kind, value))
        pos = m.end()
    return out


def truthy(v):
    return v not in (None, False, 0, 0.0, "")


def number(v):
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip()) if v.strip() else 0.0
        except ValueError:
            return float("nan")
    return float("nan")


def compare(a, op, b):
    if isinstance(a, str) and isinstance(b, str):
        a, b = a.casefold(), b.casefold()
    elif type(a) is not type(b) or a is None:
        a, b = number(a), number(b)
    try:
        return {"==": a == b, "!=": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
    except TypeError:
        return op == "!="


def text_of(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (list, dict)):
        return json.dumps(v)
    return str(v)


class Expr:
    """A recursive-descent evaluator of GitHub's expression syntax over `ctx` (dicts of known values; a missing
    context or key raises Unknown) and `funcs` (callables by lower-case name)."""

    def __init__(self, text, ctx, funcs):
        self.toks, self.pos, self.ctx, self.funcs = tokens(text), 0, ctx, funcs

    def peek(self):
        return self.toks[self.pos] if self.pos < len(self.toks) else (None, None)

    def take(self, value=None):
        tok = self.peek()
        if tok[0] is None or (value is not None and tok[1] != value):
            raise Unknown(f"expected {value or 'more'} in the expression")
        self.pos += 1
        return tok

    def run(self):
        v = self.or_()
        if self.pos != len(self.toks):
            raise Unknown("text after the end of the expression")
        return v

    def or_(self):
        v = self.and_()
        while self.peek()[1] == "||":
            self.take()
            w = self.and_()
            v = v if truthy(v) else w
        return v

    def and_(self):
        v = self.cmp()
        while self.peek()[1] == "&&":
            self.take()
            w = self.cmp()
            v = w if truthy(v) else v
        return v

    def cmp(self):
        v = self.unary()
        while self.peek()[1] in ("==", "!=", "<", ">", "<=", ">="):
            op = self.take()[1]
            v = compare(v, op, self.unary())
        return v

    def unary(self):
        if self.peek()[1] == "!":
            self.take()
            return not truthy(self.unary())
        return self.primary()

    def primary(self):
        kind, value = self.take()
        if kind == "num":
            return float(value) if "." in value else int(value)
        if kind == "str":
            return value[1:-1].replace("''", "'")
        if value == "(":
            v = self.or_()
            self.take(")")
            return v
        if kind != "id":
            raise Unknown(f"unexpected {value!r} in the expression")
        if value in ("true", "false"):
            return value == "true"
        if value == "null":
            return None
        if self.peek()[1] == "(":
            self.take()
            args = []
            while self.peek()[1] != ")":
                args.append(self.or_())
                if self.peek()[1] == ",":
                    self.take()
            self.take(")")
            fn = self.funcs.get(value.lower())
            if fn is None:
                raise Unknown(f"function {value}() is not known here")
            return fn(*args)
        if value not in self.ctx:
            raise Unknown(f"the context {value} is not available locally")
        v, path = self.ctx[value], value
        while self.peek()[1] in (".", "["):
            if self.take()[1] == ".":
                name = self.take()[1]
            else:
                name = text_of(self.or_())
                self.take("]")
            path += "." + name
            if isinstance(v, dict) and name in v:
                v = v[name]
            elif isinstance(v, dict) and v.get("*open*"):
                v = None  # matrix and env: a missing key is null, as on GitHub
            else:
                raise Unknown(f"{path} is not available locally")
        return v


def substitute(text, ev):
    """`text` with each ${{ expr }} replaced by its value."""
    if not isinstance(text, str):
        return text_of(text)
    return re.sub(r"\$\{\{(.*?)\}\}", lambda m: text_of(ev(m.group(1))), text, flags=re.S)


def condition(raw, ev, status):
    """Whether an `if:` passes. Without a status function it is success() && (raw), as on GitHub."""
    if raw is None:
        return status["success"]
    if isinstance(raw, bool):
        return raw and status["success"]
    text = str(raw).strip()
    m = re.fullmatch(r"\$\{\{(.*)\}\}", text, flags=re.S)
    text = m.group(1) if m else text
    if not re.search(r"\b(success|failure|always|cancelled)\s*\(", text):
        text = f"success() && ({text})"
    return truthy(ev(text))


# ---- the project ---------------------------------------------------------------------------------------------------
def git(root, *args):
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env)


def host_os():
    name = platform.system()
    return {"Linux": "Linux", "Darwin": "macOS"}.get(name, name)


def runs_here(runs_on, os_name):
    labels = runs_on if isinstance(runs_on, list) else [runs_on]
    labels = [str(x).lower() for x in labels if str(x).lower() != "self-hosted"]
    want = ("ubuntu", "linux") if os_name == "Linux" else ("macos", "osx") if os_name == "macOS" else ("\0",)
    return bool(labels) and all(any(lab.startswith(w) for w in want) for lab in labels)


def branch_filter(globs, name):
    """GitHub's branches/paths patterns: `*` stays in one segment, `**` crosses them, a leading `!` negates."""
    ok = False
    for g in globs:
        neg = str(g).startswith("!")
        g = str(g)[1:] if neg else str(g)
        if config.glob_regex(g).match(name) or fnmatch.fnmatchcase(name, g):
            ok = not neg
    return ok


def triggered(on, event, root, cfg, branch, changed):
    if isinstance(on, str):
        on = {on: None}
    elif isinstance(on, list):
        on = {str(x): None for x in on}
    if not isinstance(on, dict) or event not in on:
        return False
    spec = on[event] if isinstance(on[event], dict) else {}
    ref = cfg["protectedBranch"] if event == "pull_request" else branch
    if "branches" in spec and not branch_filter(spec["branches"] or [], ref):
        return False
    if "branches-ignore" in spec and branch_filter(spec["branches-ignore"] or [], ref):
        return False
    if changed is not None:
        if "paths" in spec and not any(branch_filter(spec["paths"] or [], f) for f in changed):
            return False
        if "paths-ignore" in spec and changed and all(branch_filter(spec["paths-ignore"] or [], f) for f in changed):
            return False
    return True


def changed_files(root, base):
    mb = git(root, "merge-base", f"origin/{base}", "HEAD")
    if mb.returncode != 0:
        return None  # no base to compare with: path filters are taken as matching
    out = git(root, "diff", "--name-only", mb.stdout.strip())
    extra = git(root, "ls-files", "--others", "--exclude-standard")
    if out.returncode != 0:
        return None
    return sorted(set(out.stdout.split("\n") + extra.stdout.split("\n")) - {""})


def matrix_combos(strategy, ev):
    """The matrix combinations of a job ([{}] without a matrix); raises Unknown for one built by an expression."""
    matrix = (strategy or {}).get("matrix") if isinstance(strategy, dict) else None
    if matrix is None:
        return [{}]
    if not isinstance(matrix, dict):
        raise Unknown("the matrix comes from an expression")
    axes = {k: v for k, v in matrix.items() if k not in ("include", "exclude")}
    for k, v in axes.items():
        if not isinstance(v, list):
            raise Unknown(f"matrix.{k} comes from an expression")
    combos = [dict(zip(axes, values)) for values in itertools.product(*axes.values())] if axes else []
    for ex in matrix.get("exclude") or []:
        combos = [c for c in combos if not all(c.get(k) == v for k, v in ex.items())]
    originals = [dict(c) for c in combos]
    for inc in matrix.get("include") or []:
        hit = False
        for c, orig in zip(combos, originals):
            if orig is not None and all(orig.get(k, v) == v for k, v in inc.items() if k in orig):
                c.update(inc)
                hit = True
        if not hit:
            combos.append(dict(inc))
            originals.append(None)  # a combination of its own: later includes do not extend it
    return combos or [{}]


class Run:
    def __init__(self, root, cfg, event, plan_only):
        self.root, self.cfg, self.event, self.plan_only = root, cfg, event, plan_only
        self.os = host_os()
        self.branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "HEAD"
        self.sha = git(root, "rev-parse", "HEAD").stdout.strip()
        self.ran, self.failed, self.not_run, self.not_covered = 0, [], [], []
        self.unrun = []  # jobs this script could not evaluate (not other-OS or services): they forbid a green
        self.tmp = tempfile.mkdtemp(prefix="gw-ci-local-")
        base = cfg["protectedBranch"]
        self.github = {
            "event_name": event, "sha": self.sha, "workspace": str(root), "repository": "",
            "ref": "refs/pull/local/merge" if event == "pull_request" else f"refs/heads/{self.branch}",
            "ref_name": "local/merge" if event == "pull_request" else self.branch,
            "base_ref": base if event == "pull_request" else "",
            "head_ref": self.branch if event == "pull_request" else "",
            "event": {"pull_request": {"base": {"ref": base}, "head": {"ref": self.branch, "sha": self.sha}}}
            if event == "pull_request" else {},
        }

    def funcs(self, status):
        def hash_files(*globs):
            files = git(self.root, "ls-files", "-co", "--exclude-standard").stdout.splitlines()
            pos = [config.glob_regex(g) for g in globs if not str(g).startswith("!")]
            neg = [config.glob_regex(str(g)[1:]) for g in globs if str(g).startswith("!")]
            hit = [f for f in files if any(r.match(f) for r in pos) and not any(r.match(f) for r in neg)
                   and os.path.isfile(os.path.join(self.root, f))]
            if not hit:
                return ""
            h = hashlib.sha256()
            for f in sorted(hit):
                with open(os.path.join(self.root, f), "rb") as fh:
                    h.update(hashlib.sha256(fh.read()).digest())
            return h.hexdigest()

        def fmt(template, *args):
            return re.sub(r"\{(\d+)\}", lambda m: text_of(args[int(m.group(1))]), str(template))

        return {
            "success": lambda: status["success"], "failure": lambda: status["failure"],
            "always": lambda: True, "cancelled": lambda: False, "hashfiles": hash_files, "format": fmt,
            "contains": lambda a, b: (any(compare(x, "==", b) for x in a) if isinstance(a, list)
                                      else text_of(b).casefold() in text_of(a).casefold()),
            "startswith": lambda a, b: text_of(a).casefold().startswith(text_of(b).casefold()),
            "endswith": lambda a, b: text_of(a).casefold().endswith(text_of(b).casefold()),
            "tojson": lambda v: json.dumps(v, indent=2),
        }

    def evaluator(self, matrix, env, status):
        ctx = {"github": self.github, "runner": {"os": self.os, "temp": self.tmp},
               "matrix": dict(matrix, **{"*open*": True}), "env": dict(env, **{"*open*": True})}
        funcs = self.funcs(status)
        return lambda text: Expr(text, ctx, funcs).run()

    def say(self, text):
        print(f"ci-local: {text}", flush=True)

    def workflow(self, path, doc):
        if not isinstance(doc, dict) or not isinstance(doc.get("jobs"), dict):
            self.not_covered.append(f"{path} (no jobs)")
            return
        env0 = {k: text_of(v) for k, v in (doc.get("env") or {}).items()}
        defaults0 = ((doc.get("defaults") or {}).get("run") or {})
        done = {}  # job id -> "success" | "failure" | "skipped" | "not covered"
        pending = dict(doc["jobs"])
        while pending:
            ready = [j for j, spec in pending.items()
                     if all(n in done or n not in doc["jobs"] for n in self.needs(spec))]
            ready = ready or [next(iter(pending))]  # a cycle: run in file order and let GitHub's rules say the rest
            for job_id in ready:
                spec = pending.pop(job_id)
                done[job_id] = self.job(path, job_id, spec or {}, env0, defaults0, done)

    @staticmethod
    def needs(spec):
        n = (spec or {}).get("needs") or []
        return [n] if isinstance(n, str) else [str(x) for x in n]

    def job(self, path, job_id, spec, env0, defaults0, done):
        name = str(spec.get("name") or job_id)
        label = f"{os.path.basename(path)} / {job_id if '${{' in name else name}"  # an expression name is not a label
        needs = self.needs(spec)
        missing = [n for n in needs if n not in done]
        if missing:
            self.not_covered.append(f"{label} (needs unknown job {', '.join(missing)})")
            self.unrun.append(label)
            return "not covered"
        status = {"success": all(done[n] in ("success", "not covered") for n in needs),
                  "failure": any(done[n] == "failure" for n in needs)}
        try:
            combos = matrix_combos(spec.get("strategy"), None)
        except Unknown as exc:
            if "expression" not in str(exc):
                self.not_covered.append(f"{label} ({exc})")
                self.unrun.append(label)
                return "not covered"
            # A matrix built by an expression (fromJSON(needs...)) cannot be expanded here: run the job once, with the
            # toolchain this machine has, instead of leaving it out of a green.
            self.say(f"{label}: matrix from expression: run once locally")
            combos = [{}]
        results = []
        for matrix in combos:
            name = label + (f" ({', '.join(text_of(v) for v in matrix.values())})" if matrix else "")
            results.append(self.combo(name, spec, matrix, env0, defaults0, status))
        if "failure" in results:
            return "failure"
        return "success" if "success" in results else results[0] if results else "skipped"

    def combo(self, name, spec, matrix, env0, defaults0, status):
        ev = self.evaluator(matrix, env0, status)
        try:
            runs_on = spec.get("runs-on")
            runs_on = [substitute(x, ev) for x in runs_on] if isinstance(runs_on, list) else substitute(runs_on, ev)
            if not runs_here(runs_on, self.os):
                self.not_covered.append(f"{name} (runs on {text_of(runs_on)})")
                return "not covered"
            if spec.get("services") or spec.get("container"):
                self.not_covered.append(f"{name} (needs {'services' if spec.get('services') else 'a container'})")
                return "not covered"
            if not condition(spec.get("if"), ev, status):
                self.say(f"{name}: skipped (its if: is false)")
                return "skipped"
            env = dict(env0)
            env.update({k: substitute(v, self.evaluator(matrix, env, status)) for k, v in (spec.get("env") or {}).items()})
            defaults = dict(defaults0, **((spec.get("defaults") or {}).get("run") or {}))
        except Unknown as exc:
            self.not_covered.append(f"{name} ({exc})")
            self.unrun.append(name)
            return "not covered"
        tolerate_job = text_of(spec.get("continue-on-error")) == "true"
        self.say(f"== job {name}")
        state = {"success": True, "failure": False}
        extra_env, extra_path = {}, []
        for i, step in enumerate(spec.get("steps") or []):
            step = step or {}
            sname = step.get("name") or step.get("uses") or (str(step.get("run") or "").splitlines() or [f"step {i + 1}"])[0]
            sname = f"{name} › {sname}"
            step_env = dict(env, **extra_env)
            ev = self.evaluator(matrix, step_env, state)
            try:
                if not condition(step.get("if"), ev, state):
                    continue
                if "uses" in step:
                    self.not_run.append(sname)
                    self.say(f"{sname}: not run (uses: {step['uses']}; this machine must have it already)")
                    continue
                script = substitute(step.get("run"), ev)
                if SYSTEM_PACKAGES.search(script):
                    self.not_run.append(sname)
                    self.say(f"{sname}: not run (system packages; this machine must have them already)")
                    continue
                for k, v in (step.get("env") or {}).items():
                    step_env[k] = substitute(v, self.evaluator(matrix, step_env, state))
                shell = substitute(step.get("shell") or defaults.get("shell") or "", ev)
                wd = substitute(step.get("working-directory") or defaults.get("working-directory") or ".", ev)
                tolerate = text_of(substitute(step.get("continue-on-error"), ev)) == "true"
                timeout = step.get("timeout-minutes")
            except Unknown as exc:
                self.not_covered.append(f"{sname} ({exc})")
                continue
            command = self.shell_command(shell)
            if command is None:
                self.not_covered.append(f"{sname} (shell {shell} is not supported here)")
                continue
            self.ran += 1
            if self.plan_only:
                self.say(f"{sname}: would run in {wd}")
                continue
            code = self.execute(sname, script, command, wd, step_env, extra_path, timeout)
            extra_env.update(self.read_env_file())
            extra_path[:0] = self.read_path_file()
            if code != 0:
                if tolerate:
                    self.say(f"{sname}: failed (exit {code}), continue-on-error")
                    continue
                state = {"success": False, "failure": True}
                if not tolerate_job:
                    self.failed.append(f"{sname} (exit {code})")
        return "failure" if state["failure"] and not tolerate_job else "success"

    @staticmethod
    def shell_command(shell):
        shell = shell.strip()
        if shell in ("", "bash"):
            return ["bash", "--noprofile", "--norc", "-e" if not shell else "-eo", *([] if not shell else ["pipefail"])]
        if shell == "sh":
            return ["sh", "-e"]
        if shell == "python":
            return [sys.executable]
        return None

    def read_env_file(self):
        out, path = {}, os.path.join(self.tmp, "env")
        if not os.path.isfile(path):
            return out
        lines = open(path, encoding="utf-8").read().splitlines()
        os.remove(path)
        i = 0
        while i < len(lines):
            m = re.match(r"([^=<]+)<<(.+)$", lines[i])
            if m:
                end = lines.index(m.group(2), i + 1) if m.group(2) in lines[i + 1:] else len(lines)
                out[m.group(1)] = "\n".join(lines[i + 1:end])
                i = end + 1
                continue
            if "=" in lines[i]:
                k, v = lines[i].split("=", 1)
                out[k] = v
            i += 1
        return out

    def read_path_file(self):
        path = os.path.join(self.tmp, "path")
        if not os.path.isfile(path):
            return []
        lines = [x for x in open(path, encoding="utf-8").read().splitlines() if x.strip()]
        os.remove(path)
        return list(reversed(lines))

    def execute(self, sname, script, command, wd, step_env, extra_path, timeout):
        cwd = os.path.normpath(os.path.join(self.root, wd))
        if not os.path.isdir(cwd):
            self.say(f"{sname}: working-directory {wd} does not exist")
            return 1
        file = os.path.join(self.tmp, "step.py" if command[0] == sys.executable else "step.sh")
        with open(file, "w", encoding="utf-8") as fh:
            fh.write(script)
        env = dict(os.environ)
        env.update(step_env)
        env.update(CI="true", GITHUB_EVENT_NAME=self.event, GITHUB_BASE_REF=self.github["base_ref"],
                   GITHUB_HEAD_REF=self.github["head_ref"], GITHUB_REF=self.github["ref"],
                   GITHUB_REF_NAME=self.github["ref_name"], GITHUB_SHA=self.sha, GITHUB_WORKSPACE=str(self.root),
                   RUNNER_OS=self.os, RUNNER_TEMP=self.tmp, GITHUB_ENV=os.path.join(self.tmp, "env"),
                   GITHUB_PATH=os.path.join(self.tmp, "path"), GITHUB_OUTPUT=os.path.join(self.tmp, "output"),
                   GITHUB_STEP_SUMMARY=os.path.join(self.tmp, "summary"))
        if extra_path:
            env["PATH"] = os.pathsep.join(extra_path + [env.get("PATH", "")])
        self.say(f"-- {sname}")
        try:
            r = subprocess.run([*command, file], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               timeout=float(timeout) * 60 if isinstance(timeout, (int, float)) else None)
            return r.returncode
        except subprocess.TimeoutExpired:
            self.say(f"{sname}: timed out after {timeout} min")
            return 124
        except OSError as exc:
            self.say(f"{sname}: cannot start {command[0]}: {exc}")
            return 127


def workflows(root, cfg, event, branch):
    folder = os.path.join(root, ".github", "workflows")
    listed = cfg.get("ciLocalWorkflows") or []
    if listed:
        return [(p, True) for p in listed]
    if not os.path.isdir(folder):
        return []
    return [(os.path.join(".github", "workflows", f), False) for f in sorted(os.listdir(folder))
            if f.endswith((".yml", ".yaml"))]


def dirty(root, log):
    out = git(root, "status", "--porcelain", "--untracked-files=all").stdout.splitlines()
    return any(line[3:].strip('"') != log for line in out if line.strip())


def record(root, log, line):
    path = os.path.join(root, log)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    text = open(path, encoding="utf-8").read() if os.path.isfile(path) else HEADER
    if text and not text.endswith("\n"):
        text += "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text + line + "\n")


def summary(run):
    parts = []
    if run.failed:
        parts.append("red: " + "; ".join(run.failed))
    elif not run.ran:
        parts.append("not green: no step ran")
    elif run.unrun:
        parts.append("not green: did not run: " + "; ".join(run.unrun))
    else:
        parts.append(f"green ({run.ran} step{'s' if run.ran != 1 else ''} run, event {run.event})")
    if run.not_run:
        parts.append(f"not run: {len(run.not_run)} setup step{'s' if len(run.not_run) != 1 else ''}")
    parts.append("not covered: " + "; ".join(run.not_covered) if run.not_covered else "all covered")
    return "; ".join(parts)


def main(argv=None):
    argv = config.legacy_flags(sys.argv[1:] if argv is None else argv, {"--apuntar": "--record"}, "ci-local")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root")
    p.add_argument("--event", default="pull_request", choices=("pull_request", "push"))
    p.add_argument("--plan", action="store_true", help="say what would run, run nothing")
    p.add_argument("--record", action="store_true", help="append the result to ciLocalLog")
    args = p.parse_args(argv)
    try:
        root = config.find_root(args.root)
        cfg = config.load(root)
    except config.ConfigError as exc:
        print(f"ci-local: {exc}; fix the config: python3 {os.path.join(HERE, 'config.py')} validate", file=sys.stderr)
        return 2
    if args.plan and args.record:
        print("ci-local: --plan runs nothing, so there is nothing to record; drop one: "
              f"python3 {os.path.join(HERE, 'ci-local.py')} --record", file=sys.stderr)
        return 2
    log = cfg["ciLocalLog"]
    was_dirty = dirty(root, log)
    run = Run(root, cfg, args.event, args.plan)
    try:
        found = workflows(root, cfg, args.event, run.branch)
        changed = changed_files(root, cfg["protectedBranch"])
        picked = 0
        for rel, listed in found:
            full = os.path.join(root, rel)
            if not os.path.isfile(full):
                print(f"ci-local: {rel} (ciLocalWorkflows) does not exist; fix the list: "
                      f"python3 {os.path.join(HERE, 'config.py')} get ciLocalWorkflows", file=sys.stderr)
                return 2
            try:
                doc = load_yaml(open(full, encoding="utf-8").read())
            except YamlError as exc:
                run.not_covered.append(f"{rel} (cannot read it: {exc})")
                picked += 1
                continue
            jobs = doc.get("jobs") if isinstance(doc, dict) else None
            odd = [n for n, spec in jobs.items() if not isinstance(spec, dict)] if isinstance(jobs, dict) else None
            if odd is None or odd:
                why = "not a workflow" if odd is None else "not a workflow: job " + ", ".join(map(str, odd)) + \
                    " is not a mapping"
                run.not_covered.append(f"{rel} ({why})")
                picked += 1
                continue
            if not listed and not triggered(doc.get("on"), args.event, root, cfg, run.branch, changed):
                continue
            picked += 1
            run.say(f"workflow {rel}")
            run.workflow(rel, doc)
        if not picked:
            print(f"ci-local: no workflow in .github/workflows runs on {args.event}; list the ones to run in "
                  f"ciLocalWorkflows of .claude/gw.json, or try: python3 {os.path.join(HERE, 'ci-local.py')} "
                  "--event push", file=sys.stderr)
            return 2
    finally:
        shutil.rmtree(run.tmp, ignore_errors=True)
    result = summary(run)
    for item in run.not_covered:
        run.say(f"not covered: {item}")
    green = not run.failed and run.ran > 0 and not run.unrun
    if run.unrun and not run.failed:
        run.say("not green: a job could not be evaluated, so it did not run: " + "; ".join(run.unrun))
    if args.plan:
        run.say(f"plan: {run.ran} step(s) would run; {len(run.not_run)} not run; {len(run.not_covered)} not covered")
        return 0
    run.say(result)
    if args.record:
        date = datetime.date.today().isoformat()
        line = f"- {date} · `{run.sha[:12]}`{' (uncommitted changes)' if was_dirty else ''} · {result}"
        record(root, log, line)
        run.say(f"recorded in {log}; commit and push it: git add {log} && git commit -m 'CI run locally' && git push")
        if was_dirty:
            run.say("the tree had uncommitted changes, so the PR hook will not take this line; commit and rerun")
    elif green:
        run.say(f"to record it: python3 {os.path.join(HERE, 'ci-local.py')} --record")
    return 0 if green else 1


if __name__ == "__main__":
    sys.exit(main())
