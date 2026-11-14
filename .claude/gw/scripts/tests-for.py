#!/usr/bin/env python3
# galivelop-workflow v0.6.0
"""The test files a change calls for, from `testMap` in .claude/gw.json (E21).

  python3 tests-for.py FILE [...]          # the test files, one per line (repo-relative, sorted, no repeats)
  python3 tests-for.py --diff REV [FILE...] # also every file that differs from REV (commits and working tree)
  python3 tests-for.py --run ...           # run them with testMap.command ({files} -> the test files, shell-quoted)

Every rule of `testMap.rules` whose `paths` regex is found in a changed path (repo-relative, `/`) and, when it has
`contains`, whose regex is found in that file's text on disk, adds its `tests`: `{name}` is the rule's named group as
matched, `{name:id}` the same with every character that is not a letter, digit or `_` turned into `_`
(`scripts/config-guard.py` -> `tests/test_config_guard.py`), `{path}` the changed path. A test file that does not
exist is left out, so a broad rule costs nothing. A changed file may be absolute or relative to the current directory;
one outside the project is an error. Nothing matched: no output, exit 0 (with --run, a note and exit 0).

Who uses it: the brief of gw-orchestrate-dealer (a subagent runs the tests of what it touches instead of a list
written by hand) and anyone before a commit. It is not a hook: the push runs `check` and `relatedTests`. Project root
and config: config.find_root and config.load. Fails closed: no config, an invalid one, a placeholder the rule has no
group for, or --run with an empty `testMap.command` -> exit 2 with what fixes it. With --run the exit code is the
command's, except a plain `python3 [-B] -m unittest {files}` (optionally with a PYTHONPATH=<dir> prefix, no other env prefix or interpreter): that runs
through test-run.py (one test class per process, `testJobs`), exit 0 passed, 1 failed, 2 cannot run (test-run.py
does not load, or a requested file is not a test_*.py it can discover). Python 3.8+ standard library only.
"""
import argparse
import importlib.util
import os
import re
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, str(HERE))
import config  # noqa: E402

PLACEHOLDER = re.compile(r"\{(\w+)(?::(id))?\}")


class MapError(Exception):
    pass


def expand(template, match, path):
    """`template` with its placeholders filled from `match` (named groups) and `path`; MapError on an unknown one."""
    groups = match.groupdict()

    def fill(m):
        name, ident = m.group(1), m.group(2)
        if name == "path":
            value = path
        elif name in groups:
            value = groups[name] or ""
        else:
            raise MapError(f"{{{name}}} in {template!r} names no group of its rule's `paths`; add (?P<{name}>...) to "
                           "it or fix the placeholder in testMap of .claude/gw.json")
        return re.sub(r"[^A-Za-z0-9_]", "_", value) if ident else value

    return PLACEHOLDER.sub(fill, template)


def text_of(root, rel):
    try:
        return (root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def tests_for(root, rules, files):
    """The existing test files (repo-relative, sorted) the rules give for `files` (repo-relative paths)."""
    found = set()
    for rule in rules:
        paths = re.compile(rule["paths"])
        contains = re.compile(rule["contains"]) if rule.get("contains") else None
        for rel in files:
            match = paths.search(rel)
            if not match:
                continue
            if contains is not None:
                text = text_of(root, rel)
                if text is None or not contains.search(text):
                    continue
            for template in rule["tests"]:
                test = expand(template, match, rel)
                if (root / test).is_file():
                    found.add(test)
    return sorted(found)


def relative(root, name):
    """`name` (absolute or relative to the current directory) as a repo-relative path with `/`."""
    full = Path(os.path.abspath(name))
    for candidate in (full, Path(os.path.realpath(full.parent)) / full.name):  # a symlinked path to the root
        try:
            return candidate.relative_to(root).as_posix()
        except ValueError:
            pass
    raise MapError(f"{name} is outside the project {root}; pass files of this project")


def diff_files(root, rev):
    r = subprocess.run(["git", "-C", str(root), "diff", "--name-only", "--no-renames", rev, "--"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise MapError(f"cannot diff against {rev!r} ({r.stderr.strip()}); fetch it first: git fetch origin")
    untracked = subprocess.run(["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
                               capture_output=True, text=True)
    return [f for f in (r.stdout + untracked.stdout).splitlines() if f]


# A testMap.command that is just unittest over {files}: test-run.py runs those same files in parallel instead.
# Only what is equivalent to test-run.py's own `python3 -m unittest discover`: an optional PYTHONPATH=<dir> prefix (passed
# on in the environment), no other env prefix, no other interpreter.
PLAIN_UNITTEST = re.compile(r"^\s*(?:PYTHONPATH=([\w./:-]+)\s+)?python3\s+(?:-B\s+)?-m\s+unittest\s+\{files\}\s*$")


def run_parallel(root, cfg, tests, pythonpath=None):
    """Run the test files through scripts/test-run.py (units, `testJobs`); exit 0 all passed, 1 some failed, 2 cannot run."""
    try:
        spec = importlib.util.spec_from_file_location("gw_test_run", HERE / "test-run.py")
        tr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tr)
    except Exception as exc:  # a broken test-run.py is "cannot run", not "some tests failed"
        print(f"tests-for: cannot load test-run.py ({exc}); reinstall the workflow: /gw-update", file=sys.stderr)
        return 2
    if pythonpath:
        os.environ["PYTHONPATH"] = pythonpath  # the units run with cwd=root, as the serial command would
    jobs = cfg.get("testJobs", 0)
    if not isinstance(jobs, int) or isinstance(jobs, bool) or jobs < 0:
        print("tests-for: testJobs must be an integer >= 0 (0 = one per CPU); fix .claude/gw.json", file=sys.stderr)
        return 2
    jobs = jobs or os.cpu_count() or 1
    wanted = {}
    for t in tests:
        wanted.setdefault(str(Path(t).parent.as_posix()), set()).add(Path(t).name)
    try:
        units = [u for folder, names in sorted(wanted.items()) for u in tr.discover(root, sys.executable, folder)
                 if u[1] in names]
    except tr.RunError as exc:
        print(f"tests-for: {exc}", file=sys.stderr)
        return 2
    found = {os.path.normpath(f"{u[0]}/{u[1]}") for u in units}
    missing = [t for t in tests if os.path.normpath(t) not in found]
    if missing:
        print(f"tests-for: {', '.join(missing)} is not a test_*.py test-run.py can discover; name it test_*.py "
              "or use a testMap.command other than plain unittest", file=sys.stderr)
        return 2
    print(f"tests-for: test-run.py: {len(tests)} test files, {len(units)} units, {jobs} jobs", flush=True)
    failed, ran_total = [], 0
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for unit, code, _secs, ran, output in pool.map(lambda u: tr.run_unit(root, sys.executable, u), units):
            ran_total += ran
            if code != 0:
                failed.append(tr.unit_name(unit))
                print(f"---- {tr.unit_name(unit)} (exit {code})\n{output.rstrip()}", flush=True)
    expected = sum(u[3] for u in units)
    if not failed and not any(u[2] is None for u in units) and ran_total != expected:
        failed.append(f"ran {ran_total} tests, discovered {expected}: a -k pattern missed or repeated a test")
    if failed:
        print(f"tests-for: FAILED ({'; '.join(failed)})")
        return 1
    print("tests-for: OK")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="The test files a change calls for (testMap in .claude/gw.json).")
    parser.add_argument("files", nargs="*", help="changed files (absolute or relative to the current directory)")
    parser.add_argument("--diff", metavar="REV", help="add every file that differs from REV, plus untracked ones")
    parser.add_argument("--run", action="store_true", help="run the test files with testMap.command")
    parser.add_argument("--root", help="project root (default: config.find_root)")
    args = parser.parse_args(argv)
    try:
        root = Path(config.find_root(args.root)).resolve()
        cfg = config.load(root)
    except config.ConfigError as exc:
        print(f"tests-for: {exc}", file=sys.stderr)
        return 2
    mapping = config.test_map(cfg)
    try:
        files = [relative(root, f) for f in args.files]
        if args.diff:
            files += diff_files(root, args.diff)
        tests = tests_for(root, mapping["rules"], sorted(set(files)))
    except MapError as exc:
        print(f"tests-for: {exc}", file=sys.stderr)
        return 2
    if not mapping["rules"]:
        print("tests-for: testMap.rules is empty, so no change calls for a test; add rules to .claude/gw.json "
              "(see docs/en/config.md)", file=sys.stderr)
    if not args.run:
        for test in tests:
            print(test)
        return 0
    if not mapping["command"]:
        print("tests-for: testMap.command is empty; set it in .claude/gw.json "
              "(e.g. \"PYTHONPATH=tests python3 -B -m unittest {files}\")", file=sys.stderr)
        return 2
    if not tests:
        print("tests-for: no test file for these changes; nothing to run")
        return 0
    plain = PLAIN_UNITTEST.match(mapping["command"])
    if plain and (HERE / "test-run.py").is_file():
        return run_parallel(root, cfg, tests, plain.group(1))  # B33: the same tests, one class per process (testJobs)
    command = mapping["command"].replace("{files}", " ".join(shlex.quote(t) for t in tests))
    print(f"tests-for: {command}", flush=True)
    return subprocess.run(["bash", "-c", command], cwd=str(root)).returncode


if __name__ == "__main__":
    sys.exit(main())
