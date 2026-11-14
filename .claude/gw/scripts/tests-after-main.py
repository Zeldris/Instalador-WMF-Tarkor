#!/usr/bin/env python3
# galivelop-workflow v0.6.0
"""A unittest TestCase defined after the `unittest.main()` call never runs, and the check stays green (a check for CI).

`unittest.main()` runs the tests that exist when it is called and then exits. A `class X(unittest.TestCase)` written
below it (usually inside `if __name__ == "__main__":`, or after it by a bad merge) is never collected, so the tests look
present and do not run. This script parses every test file with `ast` and fails when a TestCase subclass is defined
after a statement that calls `unittest.main(...)` (also `from unittest import main [as m]` and `import unittest as u`).
A class that inherits from a TestCase subclass of the same file counts too, and so does any base whose name ends in
`TestCase` (IsolatedAsyncioTestCase, a framework's TestCase). A file that does not parse (a fixture, newer syntax) is
only warned about, with its line: running the tests is what catches a real syntax error.

  python3 tests-after-main.py [--root PATH] [FILE ...]

Without FILE it checks the tracked `test_*.py` and `*_test.py` files of the repo (the untracked ones outside a git repo).
Exit 0 if every file is clean (or there are no test files, or some only warned); 1 if some class comes after `main`. Python 3.8+, stdlib only.
"""
import argparse
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# The walk outside git skips these folders when config.py cannot be loaded; otherwise the `testScanSkipDirs` key (A13).
# It stays apart from doctorTestDirsIgnore on purpose: that list is longer (env, site-packages, .claude/gw, ...) and has
# another job, so merging them would change what is scanned.
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".tox"}


def skip_dirs(root):
    """The folder names the walk outside git skips: the project's `testScanSkipDirs` (the schema default without a
    config), SKIP_DIRS when config.py or the schema cannot be loaded. config.py cannot load a config outside a git
    repo (the very case of this walk), so then the raw `.claude/gw.json` goes through the same getter, which checks the
    value itself."""
    try:
        import config
    except ImportError:
        return SKIP_DIRS
    try:
        try:
            return set(config.test_scan_skip_dirs(config.load(root)))
        except (config.ConfigError, OSError, ValueError, KeyError):
            with open(os.path.join(root, ".claude", "gw.json"), encoding="utf-8") as fh:
                raw = json.load(fh)
            return set(config.test_scan_skip_dirs(raw if isinstance(raw, dict) else {}))
    except (OSError, ValueError, KeyError):
        try:
            return set(config.test_scan_skip_dirs({}))
        except (OSError, ValueError, KeyError, AttributeError):
            return SKIP_DIRS
    except AttributeError:
        return SKIP_DIRS


class Scan:
    """Walks one module in execution order and collects the TestCase classes defined after a `main` call."""

    def __init__(self):
        self.modules = set()   # names bound to the unittest module
        self.main_names = set()  # names bound to unittest.main
        self.case_names = set()  # names bound to unittest.TestCase, plus TestCase classes of this file
        self.found = []          # (line, class name, line of the main call)
        self.main_line = None

    def imports(self, tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "unittest":
                        self.modules.add(a.asname or "unittest")
            elif isinstance(node, ast.ImportFrom) and node.module == "unittest" and node.level == 0:
                for a in node.names:
                    if a.name == "main":
                        self.main_names.add(a.asname or "main")
                    elif a.name.endswith("TestCase"):
                        self.case_names.add(a.asname or a.name)
        if not self.modules and not self.main_names:
            self.modules.add("unittest")

    def is_case(self, base):
        if isinstance(base, ast.Name):
            return base.id in self.case_names or base.id.endswith("TestCase")
        return isinstance(base, ast.Attribute) and base.attr.endswith("TestCase")

    def main_call(self, node):
        """Line of the first `main(...)` call in a simple statement (not inside a def, class or lambda), or None."""
        todo = [node]
        while todo:
            n = todo.pop()
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(n, ast.Call):
                f = n.func
                if (isinstance(f, ast.Name) and f.id in self.main_names) or (
                        isinstance(f, ast.Attribute) and f.attr == "main" and isinstance(f.value, ast.Name)
                        and f.value.id in self.modules):
                    return n.lineno
            todo.extend(ast.iter_child_nodes(n))
        return None

    def block(self, body, seen):
        for stmt in body:
            seen = self.stmt(stmt, seen)
        return seen

    def stmt(self, stmt, seen):
        if isinstance(stmt, ast.ClassDef):
            if any(self.is_case(b) for b in stmt.bases):
                self.case_names.add(stmt.name)
                if seen:
                    self.found.append((stmt.lineno, stmt.name, self.main_line))
            return seen
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return seen
        if isinstance(stmt, ast.If):
            return self.block(stmt.body, seen) | self.block(stmt.orelse, seen)
        if isinstance(stmt, ast.Try):
            seen = self.block(stmt.body, seen)
            for h in stmt.handlers:
                seen |= self.block(h.body, seen)
            return self.block(stmt.finalbody, self.block(stmt.orelse, seen))
        if isinstance(stmt, (ast.With, ast.AsyncWith, ast.For, ast.AsyncFor, ast.While)):
            return self.block(stmt.body, seen)
        line = self.main_call(stmt)
        if line is not None and not seen:
            self.main_line = line
        return seen or line is not None


def check_file(path, warnings=None):
    """Messages (a list of strings) for one file; empty if it is clean. A file that cannot be read or parsed adds a
    message to `warnings` (when given) instead: it does not fail the check."""
    try:
        source = Path(path).read_bytes()
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        note = (f"{path}:{e.lineno or 1}: WARNING: cannot parse the test file ({e.msg}), so it was not checked; "
                f"if it is a real test, fix it: python3 -m py_compile {path}")
    except (OSError, ValueError) as e:
        note = f"{path}:1: WARNING: cannot read the test file ({e}), so it was not checked; check the path: ls -l {path}"
    else:
        note = None
    if note is not None:
        if warnings is None:
            return [note.replace(": WARNING: ", ": ", 1)]
        warnings.append(note)
        return []
    scan = Scan()
    scan.imports(tree)
    scan.block(tree.body, False)
    return [f"{path}:{line}: class {name} is defined after the unittest.main() call at line {main_line}, so it never "
            f"runs and the check stays green; move it above the `if __name__ == \"__main__\":` block (or above "
            f"the main() call)" for line, name, main_line in scan.found]


def is_test_file(name):
    base = os.path.basename(name)
    return base.endswith(".py") and (base.startswith("test_") or base.endswith("_test.py"))


def discover(root):
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--", "*.py"], capture_output=True,
                             check=True).stdout.decode("utf-8", "replace")
        return sorted(f for f in out.split("\0") if f and is_test_file(f))
    except (OSError, subprocess.CalledProcessError):
        found = []
        skip = skip_dirs(root)
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if x not in skip]
            found += [os.path.relpath(os.path.join(d, f), root) for f in files if is_test_file(f)]
        return sorted(found)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="project path (default: the git top level, else the current folder)")
    parser.add_argument("files", nargs="*", help="test files to check (default: every tracked test file)")
    args = parser.parse_args(argv)
    root = args.root
    if not root:
        try:
            root = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, check=True,
                                  text=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            root = os.getcwd()
    files = args.files or discover(root)
    base = Path(root)
    problems, warnings = [], []
    for f in files:
        problems += check_file(f, None) if args.files else check_file(base / f, warnings)  # a named file must parse
    if warnings:
        print("\n".join(warnings), file=sys.stderr)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"tests-after-main: {len(files)} test file(s) checked, no TestCase after unittest.main()")
    return 0


if __name__ == "__main__":
    sys.exit(main())
