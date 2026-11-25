#!/usr/bin/env python3
# galivelop-workflow v0.9.0
"""The test files a change calls for, from `testMap` in .claude/gw.json (E21).

  python3 tests-for.py FILE [...]          # the test files, one per line (repo-relative, sorted, no repeats)
  python3 tests-for.py --diff REV [FILE...] # also every file that differs from REV (commits and working tree)
  python3 tests-for.py --run ...           # run them with testMap.command ({files} -> the test files, shell-quoted)
  python3 tests-for.py --why ...           # also say on stderr which changed file and rule brought each test (D118)

Every rule of `testMap.rules` whose `paths` regex is found in a changed path (repo-relative, `/`) and, when it has
`contains`, whose regex is found in that file's text on disk, adds its `tests`: `{name}` is the rule's named group as
matched, `{name:id}` the same with every character that is not a letter, digit or `_` turned into `_`
(`scripts/config-guard.py` -> `tests/test_config_guard.py`), `{path}` the changed path. A test file that does not
exist is left out, so a broad rule costs nothing. A changed file may be absolute or relative to the current directory;
one outside the project is an error. Nothing matched: no output, exit 0 (with --run, a note and exit 0).

Changed `.sh` files that still exist (D106) also get shellcheck: listed on stderr without --run (`shellcheck:
FILES`; stdout stays test names only, tests/old-python.sh reads it), run with --run BEFORE the tests (D116) via
tests/shellcheck.sh (or shellcheck itself if the project has none); a warning there stops the run at once (exit 1,
the tests are not run, and it says so); a missing binary warns and the tests still run, but in CI or a cloud session
it fails and stops, as tests/shellcheck.sh does.

--why (D118), with or without --run, writes to stderr, so stdout keeps the plain mode's test names only: one line per
selected test file and per changed file that brought it, `why: TEST <- CHANGED (rule N: PATHS)`, N the rule's index
in testMap.rules and PATHS its `paths` regex; a rule that brings many tests for one file is a wide rule. Nothing
selected: `why: no test file for these changes`.

Who uses it: the brief of gw-orchestrate-dealer (a subagent runs the tests of what it touches instead of a list
written by hand) and anyone before a commit. It is not a hook: the push runs `check` and `relatedTests`. Project root
and config: config.find_root and config.load. Fails closed: no config, an invalid one, a placeholder the rule has no
group for, or --run with an empty `testMap.command` -> exit 2 with what fixes it. With --run the exit code is the
command's, except a plain `python3 [-B] -m unittest {files}` (optionally with a PYTHONPATH=<dir> prefix, no other env prefix or interpreter): that runs
through test-run.py (one test class per process, `testJobs`), exit 0 passed, 1 failed, 2 cannot run (test-run.py
does not load, or a requested file is not a test_*.py it can discover).

B42: in that parallel mode each unit runs in a session of its own with its output in a temp file, not a pipe, so a
process a test leaves behind holding that output cannot keep the run waiting; a unit that has not ended after
`testUnitTimeout` seconds (0 = no limit) is killed with its process group and fails, naming the unit and the command
that runs it alone with -v (each test named as it starts, so the one that hangs shows). When a unit ends, what it
left in its group is killed too. Stopped itself (SIGINT, SIGTERM, SIGHUP), it starts no more units and kills the
groups of those still running before it exits. Python 3.8+ standard library only.
"""
import argparse
import importlib.util
import os
import posixpath
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
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


def tests_for(root, rules, files, why=None):
    """The existing test files (repo-relative, sorted) the rules give for `files` (repo-relative paths). With a dict
    as `why`, each test file maps to the sorted (rule index, changed file) pairs that brought it (D118)."""
    found = set()
    for index, rule in enumerate(rules):
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
                    if why is not None:
                        why.setdefault(test, set()).add((index, rel))
    if why is not None:
        for test in why:
            why[test] = sorted(why[test])
    return sorted(found)


def print_why(rules, tests, why):
    """D118: on stderr, which changed file and testMap rule brought each selected test file."""
    if not tests:
        print("why: no test file for these changes", file=sys.stderr)
    for test in tests:
        for index, rel in why[test]:
            print(f"why: {test} <- {rel} (rule {index}: {rules[index]['paths']})", file=sys.stderr)


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


LIVE = set()  # the units running now (their Popen), killed with their groups if tests-for is stopped
LOCK = threading.Lock()  # LIVE and STOPPING change together: no unit starts after the stop has killed the others
STOPPING = threading.Event()


def kill_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)  # the unit and every child it left in its group
    except OSError:
        pass


def stopped(signum, _frame):
    raise SystemExit(128 + signum)  # unwinds run_parallel, whose `finally` kills the units still running


def unit_command(unit):
    """The command test-run.py runs for `unit` (its run_unit: one file, or one class with -k)."""
    folder, file, cls, _ = unit
    return [sys.executable, "-B", "-m", "unittest", "discover", "-s", folder, "-p", file] + (
        ["-k", f"*.{cls}.*"] if cls else [])


def run_unit(root, unit, limit, ran_re):
    """B42: run `unit` as test-run.py does, but in its own session, with its output in a temp file (a process it
    leaves behind holding the output cannot keep us waiting) and at most `limit` seconds (0 = no limit). Returns
    (unit, exit code or None when it timed out, seconds, tests ran, output)."""
    start = time.time()
    with tempfile.TemporaryFile() as out:
        with LOCK:
            if STOPPING.is_set():
                return unit, -1, 0.0, 0, "not started: tests-for was stopped"
            proc = subprocess.Popen(unit_command(unit), cwd=str(root), stdout=out, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
            LIVE.add(proc)
        try:
            code = proc.wait(timeout=limit or None)
        except subprocess.TimeoutExpired:
            code = None
        finally:
            kill_group(proc)  # timed out, stopped or ended: nothing it started outlives it in its group
            proc.wait()
            with LOCK:
                LIVE.discard(proc)
        out.seek(0)
        text = out.read().decode("utf-8", errors="replace")
    return unit, code, time.time() - start, sum(int(n) for n in ran_re.findall(text)), text


def alone(unit, pythonpath=None):
    """The command that runs `unit` alone, verbose, from the root (shell-quoted), with testMap.command's PYTHONPATH."""
    prefix = [f"PYTHONPATH={shlex.quote(pythonpath)}"] if pythonpath else []
    return " ".join(prefix + [shlex.quote(a) for a in ["python3"] + unit_command(unit)[1:] + ["-v"]])


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
    try:
        limit = config.test_unit_timeout(cfg)
    except config.ConfigError as exc:
        print(f"tests-for: {exc}", file=sys.stderr)
        return 2
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
    STOPPING.clear()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):  # SIGINT too: a background `cmd &` ignores it
        signal.signal(sig, stopped)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        try:
            for unit, code, _secs, ran, output in pool.map(lambda u: run_unit(root, u, limit, tr.RAN), units):
                ran_total += ran
                if code is None:
                    failed.append(f"{tr.unit_name(unit)} timed out")
                    print(f"---- {tr.unit_name(unit)} (stopped: not ended within {limit}s, testUnitTimeout)\n"
                          f"{output.rstrip()}\n"
                          f"tests-for: {tr.unit_name(unit)} did not end within {limit}s (testUnitTimeout in "
                          f".claude/gw.json); run it alone to see which test hangs: {alone(unit, pythonpath)}", flush=True)
                elif code != 0:
                    failed.append(tr.unit_name(unit))
                    print(f"---- {tr.unit_name(unit)} (exit {code})\n{output.rstrip()}", flush=True)
        finally:
            with LOCK:  # stopped (or failed) here: no unit outlives tests-for in its own session, none starts
                STOPPING.set()
                for proc in list(LIVE):
                    kill_group(proc)
    expected = sum(u[3] for u in units)
    if not failed and not any(u[2] is None for u in units) and ran_total != expected:
        failed.append(f"ran {ran_total} tests, discovered {expected}: a -k pattern missed or repeated a test")
    if failed:
        print(f"tests-for: FAILED ({'; '.join(failed)})")
        return 1
    print("tests-for: OK")
    return 0


def shell_files(root, files):
    """The changed `.sh` files that still exist (a deleted one is skipped), sorted. D152: not the workflow copies
    under `.claude/gw/` of an installed project (the workflow checks its own; the project's own .sh files stay)."""
    clean = {posixpath.normpath(f.replace("\\", "/")) for f in files}  # `./.claude/gw/x.sh` is the same path
    return sorted(f for f in clean if f.endswith(".sh") and not f.startswith(".claude/gw/") and (root / f).is_file())


def run_shellcheck(root, shells):
    """D106: shellcheck over the changed .sh files (D116: before the tests), as the check does (tests/shellcheck.sh: `shellcheckVersion`,
    a missing binary warns locally and fails in CI or a cloud session). Without that script, shellcheck directly."""
    if not shells:
        return 0
    print("tests-for: shellcheck " + " ".join(shells), flush=True)
    script = root / "tests" / "shellcheck.sh"
    if script.is_file():
        code = subprocess.run(["bash", str(script), *shells], cwd=str(root)).returncode
    elif shutil.which("shellcheck"):
        code = subprocess.run(["shellcheck", *shells], cwd=str(root)).returncode
    elif os.environ.get("CI") == "true" or os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        print("tests-for: shellcheck is missing and the check needs it; install it: pip install shellcheck-py",
              file=sys.stderr)
        return 1
    else:
        print("tests-for: warning: shellcheck not installed locally, so the .sh files were not checked; "
              "install it: pip install shellcheck-py")
        return 0
    if code != 0:
        print(f"tests-for: FAILED (shellcheck, exit {code})")
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description="The test files a change calls for (testMap in .claude/gw.json).")
    parser.add_argument("files", nargs="*", help="changed files (absolute or relative to the current directory)")
    parser.add_argument("--diff", metavar="REV", help="add every file that differs from REV, plus untracked ones")
    parser.add_argument("--run", action="store_true", help="run the test files with testMap.command")
    parser.add_argument("--why", action="store_true",
                        help="say on stderr which changed file and testMap rule brought each test file")
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
        why = {}
        tests = tests_for(root, mapping["rules"], sorted(set(files)), why)
    except MapError as exc:
        print(f"tests-for: {exc}", file=sys.stderr)
        return 2
    if not mapping["rules"]:
        print("tests-for: testMap.rules is empty, so no change calls for a test; add rules to .claude/gw.json "
              "(see docs/en/config.md)", file=sys.stderr)
    if args.why:
        print_why(mapping["rules"], tests, why)
    shells = shell_files(root, files)
    if not args.run:
        for test in tests:
            print(test)
        if shells:
            print("shellcheck: " + " ".join(shells) + "  (--run runs it)", file=sys.stderr)
        return 0
    if not mapping["command"]:
        print("tests-for: testMap.command is empty; set it in .claude/gw.json "
              "(e.g. \"PYTHONPATH=tests python3 -B -m unittest {files}\")", file=sys.stderr)
        return 2
    code = run_shellcheck(root, shells)  # D116: before the tests, and its first failure stops the run
    if code != 0:
        print("tests-for: shellcheck failed, so the tests were not run; fix the .sh files and run again")
        return code
    if not tests:
        print("tests-for: no test file for these changes; nothing to run")
        return 0
    return run_tests(root, cfg, mapping, tests)


def run_tests(root, cfg, mapping, tests):
    plain = PLAIN_UNITTEST.match(mapping["command"])
    if plain and (HERE / "test-run.py").is_file():
        return run_parallel(root, cfg, tests, plain.group(1))  # B33: the same tests, one class per process (testJobs)
    command = mapping["command"].replace("{files}", " ".join(shlex.quote(t) for t in tests))
    print(f"tests-for: {command}", flush=True)
    return subprocess.run(["bash", "-c", command], cwd=str(root)).returncode


if __name__ == "__main__":
    sys.exit(main())
