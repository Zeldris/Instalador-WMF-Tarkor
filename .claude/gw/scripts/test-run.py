#!/usr/bin/env python3
# galivelop-workflow v0.9.0
"""Run the Python test suites in parallel, one test class per process (E45).

  python3 test-run.py [DIR ...] [--jobs N] [--python CMD] [--times N]

DIR: the folders whose `test_*.py` are run, each discovered on its own as `unittest discover -s DIR` does (default:
`tests` and every `skills/*/scripts` holding a tracked `test_*.py`). Each test class is one unit, run in its own
`python -B -m unittest discover -s DIR -p <file> -k '*.<Class>.*'`; the units go to `--jobs` processes at once
(default `testJobs` in .claude/gw.json; 0 = one per CPU), the slowest first by the times of the last run, kept in
<git common dir>/gw/test-times.json. A file that does not import is run whole, so its error shows. `--python` runs
them with another interpreter (E22); `--times N` lists the N slowest units at the end.

Flaky units (E35): a unit that fails is run again (`flaky.retries` times, default 1; 0 = no retry, no record). If it
passes on a retry it counts as passed but is a FLAKY: one JSON line {unit, date, commit, output} is appended to
<git common dir>/gw/flaky.jsonl and `test-run: flaky: <unit> (passed on retry; <n> times recorded)` is printed; from
`flaky.proposeAfter` records on, the line also gives the command that runs the unit alone with -v, to fix it. If every
retry fails too, it is a normal failure and the output of both runs is shown. A file that does not import is not rerun.

Output: the full output of every unit that failed, then one line `test-run: <n> tests in <u> units, <j> jobs, <s> s:
OK` (or `FAILED (<units>)`). Fails closed: a unit that fails, or a total of tests run that is not the number
discovered (a test that no unit ran, or ran twice), exits 1; a bad config or DIR, 2. Project root and config:
config.find_root and config.load. Python 3.8+ standard library only.
"""
import argparse
import datetime
import json
import os
import re
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, str(HERE))
import config  # noqa: E402

RAN = re.compile(r"^Ran (\d+) tests? in ", re.M)
CLASS_SKIP = re.compile(r"^OK \(skipped=\d+\)$", re.M)
# Printed by the child: one test id per line; a module that does not import shows as unittest.loader._FailedTest.
LIST = (
    "import sys, unittest\n"
    "def walk(s):\n"
    "    for t in s:\n"
    "        if isinstance(t, unittest.TestSuite):\n"
    "            yield from walk(t)\n"
    "        else:\n"
    "            yield t\n"
    "suite = unittest.TestLoader().discover(sys.argv[1], pattern='test_*.py', top_level_dir=sys.argv[1])\n"
    "for t in walk(suite):\n"
    "    print(type(t).__module__ + '\\t' + type(t).__qualname__ + '\\t' + t.id())\n"
)


class RunError(Exception):
    pass


def default_dirs(root):
    out = subprocess.run(["git", "ls-files", "--", "skills/*/scripts/test_*.py"], cwd=str(root),
                         stdout=subprocess.PIPE, text=True, check=False).stdout.split()
    dirs = ["tests"] if (root / "tests").is_dir() else []
    return dirs + sorted({str(Path(f).parent.as_posix()) for f in out})


def discover(root, python, folder):
    """The units of `folder`: [(folder, file, class or None, n tests)] (class None = the whole file)."""
    p = subprocess.run([python, "-B", "-c", LIST, folder], cwd=str(root), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, check=False)
    if p.returncode != 0:
        raise RunError(f"cannot list the tests of {folder}: {p.stderr.strip()[-500:]}")
    units = {}
    broken = set()
    for line in p.stdout.splitlines():
        module, cls, test_id = line.split("\t")
        if module.startswith("unittest."):  # an import error: the id's last part is the module that failed
            broken.add(test_id.rsplit(".", 1)[-1])
            continue
        key = (module.rsplit(".", 1)[-1], cls)
        units[key] = units.get(key, 0) + 1
    out = [(folder, f"{m}.py", c, n) for (m, c), n in units.items() if m not in broken]
    out += [(folder, f"{m}.py", None, 0) for m in sorted(broken)]
    return out


def unit_name(unit):
    folder, file, cls, _ = unit
    return f"{folder}/{file}" + (f"::{cls}" if cls else "")


def run_unit(root, python, unit):
    folder, file, cls, _ = unit
    cmd = [python, "-B", "-m", "unittest", "discover", "-s", folder, "-p", file]
    if cls:
        cmd += ["-k", f"*.{cls}.*"]
    start = time.time()
    p = subprocess.run(cmd, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                       check=False)
    ran = sum(int(n) for n in RAN.findall(p.stdout))
    if cls and ran == 0 and p.returncode == 0 and CLASS_SKIP.search(p.stdout):
        ran = unit[3]  # setUpClass raised SkipTest: unittest counts no test, but the class's tests were all skipped
    return unit, p.returncode, time.time() - start, ran, p.stdout


def times_path(root):
    common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=str(root), stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, check=False).stdout.strip()
    return (root / common / "gw" / "test-times.json") if common else None


def flaky_path(root):
    times = times_path(root)
    return times.with_name("flaky.jsonl") if times else None


def run_with_retry(root, python, unit, retries):
    """run_unit, and while it fails (and is a test class) up to `retries` more runs. Returns run_unit's tuple plus the
    first failure's output when a retry passed (a flaky), else None; when all fail, the output holds every run."""
    result = run_unit(root, python, unit)
    if result[1] == 0 or unit[2] is None or retries <= 0:
        return result + (None,)
    first, outputs, total = result[4], [result[4]], result[2]
    for i in range(retries):
        again = run_unit(root, python, unit)
        total += again[2]
        if again[1] == 0:
            return (again[0], 0, total, again[3], again[4], first)
        outputs.append(again[4])
    joined = "".join(f"--- run {i + 1} of {len(outputs)}\n{o.rstrip()}\n" for i, o in enumerate(outputs))
    return (unit, result[1], total, result[3], joined, None)


def record_flaky(root, path, unit, first_output, trim):
    """Append the record to `path`; returns how many times `unit` is recorded, or a str saying why it is not (None
    path = no git common dir; an OSError)."""
    if path is None:
        return "no git common dir"
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(root), stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True, check=False).stdout.strip()
    lines = first_output.rstrip().splitlines()[-trim:]
    record = {"unit": unit_name(unit), "date": datetime.datetime.now().isoformat(timespec="seconds"),
              "commit": head, "output": "\n".join(lines)}
    count = 1
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    count += json.loads(line).get("unit") == record["unit"]
                except (ValueError, AttributeError):
                    pass
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError as exc:
        return f"{exc.strerror or exc}"  # a registry: losing a line must not fail the run
    return count


def alone_command(unit):
    folder, file, cls, _ = unit
    args = ["python3", "-B", "-m", "unittest", "discover", "-s", folder, "-p", file]
    if cls:
        args += ["-k", f"*.{cls}.*"]
    return " ".join(shlex.quote(a) for a in args + ["-v"])


def load_times(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def save_times(path, times):
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(times, indent=0, sort_keys=True), encoding="utf-8")
    except OSError:
        pass  # a cache: losing it only costs the order


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dirs", nargs="*")
    ap.add_argument("--jobs", type=int)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--times", type=int, default=0)
    ap.add_argument("--root")
    args = ap.parse_args(argv)
    try:
        root = config.find_root(args.root)
        cfg = config.load(root)
    except config.ConfigError as exc:
        print(f"test-run: {exc}", file=sys.stderr)
        return 2
    jobs = args.jobs if args.jobs is not None else cfg.get("testJobs", 0)
    if not isinstance(jobs, int) or isinstance(jobs, bool) or jobs < 0:
        print("test-run: testJobs must be an integer >= 0 (0 = one per CPU); fix --jobs or .claude/gw.json", file=sys.stderr)
        return 2
    jobs = jobs or os.cpu_count() or 1
    flaky = config._section(cfg, "flaky")  # the schema (config.load above) has refused a bad value
    dirs = args.dirs or default_dirs(root)
    for d in dirs:
        if not (root / d).is_dir():
            print(f"test-run: {d} is not a folder of {root}; pass the folders that hold test_*.py", file=sys.stderr)
            return 2
    start = time.time()
    try:
        units = [u for d in dirs for u in discover(root, args.python, d)]
    except RunError as exc:
        print(f"test-run: {exc}", file=sys.stderr)
        return 1
    tpath = times_path(root)
    fpath = flaky_path(root)
    times = load_times(tpath) if tpath else {}
    # Slowest first (longest-processing-time order); a unit with no time yet goes first, by its number of tests.
    units.sort(key=lambda u: (times.get(unit_name(u), float("inf")), u[3]), reverse=True)
    expected = sum(u[3] for u in units)
    failed, ran_total, done = [], 0, []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for unit, code, secs, ran, output, first in pool.map(lambda u: run_with_retry(root, args.python, u, flaky["retries"]), units):
            done.append((secs, unit_name(unit)))
            ran_total += ran
            if first is not None:
                n = record_flaky(root, fpath, unit, first, 10)
                recorded = f"{n} times recorded" if isinstance(n, int) else f"not recorded: {n}"
                msg = f"test-run: flaky: {unit_name(unit)} (passed on retry; {recorded})"
                if isinstance(n, int) and n >= flaky["proposeAfter"]:
                    msg += f"; flaky {n} times, fix it: run it alone with {alone_command(unit)}"
                print(msg, flush=True)
            if code != 0 or unit[2] is None:
                if code != 0:
                    failed.append(unit_name(unit))
                print(f"---- {unit_name(unit)} (exit {code})\n{output.rstrip()}", flush=True)
    times.update({name: round(secs, 2) for secs, name in done})
    save_times(tpath, times)
    if args.times:
        for secs, name in sorted(done, reverse=True)[:args.times]:
            print(f"{secs:8.1f} s  {name}")
    whole = sum(1 for u in units if u[2] is None)
    if not failed and not whole and ran_total != expected:
        failed.append(f"ran {ran_total} tests, discovered {expected}: a -k pattern missed or repeated a test; "
                      "run the folder with unittest discover to compare")
    head = f"test-run: {ran_total} tests in {len(units)} units, {jobs} jobs, {time.time() - start:.0f} s"
    if failed:
        print(f"{head}: FAILED ({'; '.join(failed)})")
        return 1
    print(f"{head}: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
