#!/usr/bin/env python3
# galivelop-workflow v0.6.0
"""Reads the GitHub Actions status of a branch or a commit through the API: "look at the CI of the last push" without
opening the web. The same reader review-before-main.sh uses to gate a merge (one place for the token / `gh` logic).

  python3 ci-status.py [--branch BRANCH | --sha SHA] [--repo OWNER/REPO] [--ignore NAME]... [--failed [--lines N]]
                       [--json] [--root PATH]

Default target: the commit HEAD of the working tree. The repo is read from the `origin` remote. The API goes through
`gh api` when gh is on PATH and can read the repo, else through curl with $GITHUB_TOKEN or $GH_TOKEN (decided once).
Every check-run must be completed with success/neutral/skipped and every commit status must be success.
`ciIgnore` of .claude/gw.json (and every --ignore) lists foreign checks (a deploy) that do not count: an exact name, or
a name with `*` standing for any text (`vercel*`); case matters. An ignored check is only left out: it never turns a
red or pending check of the project into green, and a commit where only ignored checks reported counts as no CI.

Exit 0 green; 1 not green (red, pending, or no CI reported); 2 it could not be read (no token, gh missing, API error:
fails closed). With --json, one object: {"repo", "sha", "state": green|red|pending|none|error, "problems": [...],
"ignored": [...], "unstarted": bool, "error"} (and "failed": [...] with --failed). Python 3.8+, stdlib only.

--failed (D56): for each finished red job, the step that failed and its error lines (the end of that step's log, at
most `ciFailedLines` of .claude/gw.json or --lines), plus the URL of the whole log; instead of reading the full job log.
A check that is not a GitHub Actions job (or whose log cannot be read) gives only its URL; the exit code is unchanged.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GREEN_RUNS = ("success", "neutral", "skipped")  # the default of ciGreenConclusions (A13); a caller passes the config's
TIMEOUT = 0  # seconds a gh/curl call may take (ciStatusTimeout, set by main or by a caller that read the config); 0 = no limit
NO_CI = "no CI has reported on this commit yet"
# What GitHub writes on a check-run whose job it refused to start for lack of quota.
NOT_STARTED = ("job was not started because recent account payments have failed", "spending limit needs to be increased")


class ApiError(Exception):
    def __init__(self, message, output=""):
        super().__init__(message)
        self.output = output  # what gh or curl printed, without the request path (a sha may contain "422")


# git exports GIT_DIR and friends to hooks: they would point git at the hook's repo, not at --root.
RUN_ENV = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
RUN_ENV["GIT_TERMINAL_PROMPT"] = "0"


def run(cmd, stdin=None):
    try:
        return subprocess.run(cmd, env=RUN_ENV, capture_output=True, text=True, input=stdin,
                              stdin=None if stdin is not None else subprocess.DEVNULL, timeout=TIMEOUT or None)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"timed out after {TIMEOUT} s (ciStatusTimeout in .claude/gw.json)")
    except OSError as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


_BACKEND = []  # decided once per run: ("gh", None) or ("curl", token); never mixed within a run


def backend(path):
    if not _BACKEND:
        # Reading the repo itself proves the token works for it: `gh api user` answers 403 to a GitHub App
        # installation token that can still read the repo, and `gh auth status` also fails over an unrelated stale
        # account or host.
        m = re.match(r"repos/([^/?]+)/([^/?]+)", path)
        probe = f"repos/{m.group(1)}/{m.group(2)}" if m else path
        if shutil.which("gh") and run(["gh", "api", probe]).returncode == 0:
            _BACKEND.append(("gh", None))
        else:
            token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
            if not token:
                raise ApiError(f"gh is not installed or cannot read {probe}, and neither GITHUB_TOKEN nor GH_TOKEN is set")
            if not shutil.which("curl"):
                raise ApiError("gh is not authenticated and curl is not installed")
            _BACKEND.append(("curl", token))
    return _BACKEND[0]


def api(path):
    text, how = fetch(path)
    try:
        return json.loads(text)
    except ValueError:
        raise ApiError(f"{how} did not return JSON: {text.strip()[:200]}")


def fetch(path):
    """(body, how) of a GET; raises ApiError."""
    kind, token = backend(path)
    if kind == "gh":
        r, how = run(["gh", "api", path]), "gh api " + path
    else:
        # The token goes on stdin (-H @-), never on the command line where other processes could read it.
        r = run(["curl", "-sS", "-f", "-L", "-H", "Accept: application/vnd.github+json",
                 "-H", "X-GitHub-Api-Version: 2022-11-28", "-H", "@-", "https://api.github.com/" + path],
                stdin=f"Authorization: Bearer {token}\n")
        how = "GET https://api.github.com/" + path
    if r.returncode != 0:
        output = (r.stderr or r.stdout).strip()[:300]
        raise ApiError(f"{how} failed: {output}", output)
    return r.stdout, how


# A job log line: "2026-11-10T12:00:00.1234567Z text" (a BOM on the first one).
LOG_STAMP = re.compile(r"^\ufeff?\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z ?")


def log_excerpt(log, cap):
    """(lines, cut): the step of the LAST `##[error]` line (an earlier one may be a continue-on-error step or an
    annotation), from its header (the nearest `##[group]Run ` line above, else the nearest `##[group]`) to that error
    line, without the timestamps nor the header's folded command echo (up to its first `##[endgroup]`; nested groups
    after it stay). Never more than `cap` lines: when longer, the header and the last cap - 1 lines, or, when cap
    leaves no room for the header, only the last `cap` lines; `cut` counts the body lines left out."""
    lines = [LOG_STAMP.sub("", line.rstrip("\r")) for line in log.splitlines()]
    errors = [i for i, line in enumerate(lines) if line.startswith("##[error]")]
    if not errors:
        body = [line for line in lines if line.strip()]
        keep = max(cap, 0)
        cut = max(0, len(body) - keep)
        return body[cut:], cut
    last = errors[-1]
    back = range(last, -1, -1)
    start = next((i for i in back if lines[i].startswith("##[group]Run ")), None)
    if start is None:
        start = next((i for i in back if lines[i].startswith("##[group]")), None)
    head, body, folded = [], [], False
    for i in range(start if start is not None else 0, last + 1):
        line = lines[i]
        if i == start:
            head, folded = [line[len("##[group]"):]], True
        elif folded and not line.startswith("##[error]"):  # an error inside the echo group is still shown
            folded = not line.startswith("##[endgroup]")
        elif line.startswith("##[error]"):
            body.append("error: " + line[len("##[error]"):])
        elif line.strip():
            body.append(line)
    if cap <= len(head):
        keep, head = max(cap, 0), []
    else:
        keep = cap - len(head)
    cut = max(0, len(body) - keep)
    return head + body[cut:], cut


def failure_details(repo, report, cap):
    """For each finished red check-run, {"name", "step", "lines", "cut", "url"}; for each red commit status,
    {"name", "url"} (no log). The log is read only for a GitHub Actions job (a check-run's id is its job's id)."""
    found = []
    for run_ in report["red_runs"]:
        item = {"name": run_.get("name", "?"), "step": None, "lines": [], "cut": 0,
                "url": run_.get("html_url") or run_.get("details_url")}
        try:
            job = api(f"repos/{repo}/actions/jobs/{run_['id']}")
            item["url"] = job.get("html_url") or item["url"]
            item["step"] = next((s.get("name") for s in job.get("steps") or []
                                 if s.get("conclusion") == "failure"), None)
            log, _ = fetch(f"repos/{repo}/actions/jobs/{run_['id']}/logs")
            item["lines"], item["cut"] = log_excerpt(log, cap)
        except (ApiError, KeyError, TypeError, AttributeError) as exc:
            item["error"] = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
        found.append(item)
    for status in report["red_statuses"]:
        found.append({"name": status.get("context", "?"), "step": None, "lines": [], "cut": 0,
                      "url": status.get("target_url")})
    return found


def failure_text(found):
    out = []
    for item in found:
        step = f": step {item['step']!r} failed" if item["step"] else ""
        out.append(f"\n{item['name']}{step}; whole log: {item['url'] or 'no URL'}")
        if item.get("error"):
            out.append(f"  (no log: {item['error']})")
        if item["cut"]:
            out.append(f"  ({item['cut']} earlier line(s) of the step left out: --lines N, or ciFailedLines)")
        out += ["  " + line for line in item["lines"]]
    return "\n".join(out)


def ignored(name, patterns):
    """Is the check `name` named by `patterns`: exact, or with `*` for any text (nothing else is special)."""
    for pat in patterns:
        if "*" not in pat:
            if name == pat:
                return True
        elif re.fullmatch(".*".join(re.escape(part) for part in pat.split("*")), name or "", re.S):
            return True
    return False


def not_started(repo, run_):
    """GitHub closed this check-run as failed without running the job (billing, spending limit)."""
    if run_.get("conclusion") != "failure":
        return False
    out = run_.get("output") or {}
    text = f"{out.get('title')} {out.get('summary')}"
    if not any(m in text for m in NOT_STARTED) and "id" in run_:
        try:
            notes = api(f"repos/{repo}/check-runs/{run_['id']}/annotations")
            text = " ".join(str(n.get("message", "")) for n in notes)
        except (ApiError, AttributeError, TypeError):
            return False  # cannot tell: it stays an ordinary failure
    return any(m in text for m in NOT_STARTED)


def ci_report(repo, sha, ignore=(), green=GREEN_RUNS):
    """{"problems": [...], "ignored": [names left out], "unstarted": True when every problem is a check-run GitHub
    never started, "pending": True when every problem is only unfinished}. Raises ApiError (and KeyError/TypeError
    on an unexpected answer)."""
    runs, page = [], 1
    while True:
        data = api(f"repos/{repo}/commits/{sha}/check-runs?per_page=100&page={page}")
        batch = data["check_runs"]
        runs += batch
        if not batch or len(runs) >= int(data.get("total_count", len(runs))) or page >= 10:
            break
        page += 1
    statuses = api(f"repos/{repo}/commits/{sha}/status?per_page=100")["statuses"]
    left_out = [c.get("name", "?") for c in runs if ignored(c.get("name", "?"), ignore)]
    left_out += [s.get("context", "?") for s in statuses if ignored(s.get("context", "?"), ignore)]
    runs = [c for c in runs if not ignored(c.get("name", "?"), ignore)]
    statuses = [s for s in statuses if not ignored(s.get("context", "?"), ignore)]
    if not runs and not statuses:
        return {"problems": [NO_CI], "ignored": left_out, "unstarted": False, "pending": False, "red_runs": [],
                "red_statuses": []}
    bad_runs = [c for c in runs if c.get("status") != "completed" or c.get("conclusion") not in green]
    bad_statuses = [s for s in statuses if s.get("state") != "success"]
    bad = [f"{c.get('name', '?')}: {c.get('conclusion') or c.get('status')}" for c in bad_runs]
    bad += [f"{s.get('context', '?')}: {s.get('state')}" for s in bad_statuses]
    failed = [c for c in bad_runs if c.get("status") == "completed"] + \
        [s for s in bad_statuses if s.get("state") != "pending"]
    return {"problems": bad, "ignored": left_out, "pending": bool(bad) and not failed,
            "red_runs": [c for c in bad_runs if c.get("status") == "completed"],
            "red_statuses": [s for s in bad_statuses if s.get("state") != "pending"],
            "unstarted": bool(bad_runs) and not bad_statuses and all(not_started(repo, c) for c in bad_runs)}


def ci_problems(repo, sha, ignore=(), green=GREEN_RUNS):
    """(problems, True when every problem is a check-run GitHub never started)."""
    report = ci_report(repo, sha, ignore, green)
    return report["problems"], report["unstarted"]


def origin_repo(root):
    url = run(["git", "-C", root, "remote", "get-url", "origin"]).stdout.strip()
    m = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def main(argv=None):
    ap = argparse.ArgumentParser(description="GitHub Actions status of a branch or commit (exit 0 green, 1 not green, "
                                             "2 could not be read).")
    target = ap.add_mutually_exclusive_group()
    target.add_argument("--branch", help="a branch of the repo on GitHub (default: HEAD of the working tree)")
    target.add_argument("--sha", help="a commit (full or abbreviated sha)")
    ap.add_argument("--repo", help="OWNER/REPO (default: the origin remote)")
    ap.add_argument("--ignore", action="append", default=[], metavar="NAME",
                    help="a foreign check that does not count, on top of ciIgnore (exact, or `*` for any text)")
    ap.add_argument("--failed", action="store_true",
                    help="for each red job, the step that failed, its error lines and the URL of the whole log")
    ap.add_argument("--lines", type=int, metavar="N", help="with --failed, at most N lines per job (default: "
                                                           "ciFailedLines of .claude/gw.json)")
    ap.add_argument("--json", action="store_true", help="one JSON object instead of text")
    ap.add_argument("--root", help="project root (default: resolved from this script)")
    args = ap.parse_args(argv)
    if args.lines is not None and args.lines < 1:
        ap.error("--lines must be 1 or more")
    sys.dont_write_bytecode = True
    sys.path.insert(0, HERE)
    import config
    out = {"repo": args.repo, "sha": args.sha, "state": "error", "problems": [], "ignored": [], "unstarted": False,
           "error": None}

    def finish(code, text):
        if args.json:
            print(json.dumps(out))
        else:
            print(text, file=sys.stderr if code == 2 else sys.stdout)
        return code

    me = os.path.join(HERE, "ci-status.py")
    try:
        root = str(config.find_root(args.root))
        cfg = config.load(root)
        ignore = list(cfg.get("ciIgnore") or []) + args.ignore
        green = config.ci_green_conclusions(cfg)
        global TIMEOUT
        TIMEOUT = config.ci_status_timeout(cfg)
    except config.ConfigError as exc:
        out["error"] = str(exc)
        return finish(2, f"ci-status: {exc}\nfix the config and retry: python3 {os.path.join(HERE, 'config.py')} validate")
    repo = args.repo or origin_repo(root)
    if not repo:
        out["error"] = "cannot tell the GitHub repo from the origin remote"
        return finish(2, f"ci-status: {out['error']}\npass it and retry: python3 {me} --repo OWNER/REPO")
    out["repo"] = repo
    try:
        if args.sha:
            sha = args.sha
        elif args.branch:
            sha = api(f"repos/{repo}/commits/{args.branch}")["sha"]
        else:
            r = run(["git", "-C", root, "rev-parse", "HEAD"])
            sha = r.stdout.strip()
            if r.returncode != 0 or not sha:
                raise ApiError("the working tree has no commit (git rev-parse HEAD failed)")
            try:
                api(f"repos/{repo}/commits/{sha}")
            except ApiError as exc:
                if re.search(r"\b422\b", exc.output) or "No commit found" in exc.output:
                    out["error"] = f"HEAD {sha[:12]} is not on GitHub"
                    return finish(2, f"ci-status: {out['error']}\npush first and retry: git push && python3 {me}")
                raise
        out["sha"] = sha
        report = ci_report(repo, sha, ignore, green)
    except (ApiError, KeyError, TypeError, ValueError) as exc:
        out["error"] = f"could not read the CI status: {exc}"
        return finish(2, f"ci-status: {out['error']}\nauthenticate (gh auth login, or export GITHUB_TOKEN) and retry: "
                         f"python3 {me} --repo {repo} --sha {out['sha'] or 'SHA'}")
    problems = report["problems"]
    out.update(problems=problems, ignored=report["ignored"], unstarted=report["unstarted"])
    out["state"] = "green" if not problems else "none" if problems == [NO_CI] else \
        "pending" if report["pending"] else "red"
    note = f" (ignored: {', '.join(report['ignored'])})" if report["ignored"] else ""
    if out["state"] == "green":
        return finish(0, f"ci-status: {repo} {sha[:12]}: green{note}")
    hint = ""
    if out["state"] == "none" and cfg.get("ciOnPush") is False:  # D54: check.yml only runs on pull requests
        hint = (f"\nciOnPush is false: check.yml runs only on pull requests; open one, or run the CI locally: "
                f"python3 {os.path.join(HERE, 'ci-local.py')} --record")
    if args.failed and out["state"] == "red":
        if report["unstarted"]:
            hint += "\nno log: GitHub never started these jobs (Actions quota or payments)"
        else:
            found = failure_details(repo, report, args.lines or int(cfg.get("ciFailedLines", 40)))
            out["failed"] = found
            hint += failure_text(found)
    elif args.failed and out["state"] == "pending":
        hint += f"\nnothing has failed yet; retry when it finishes: python3 {me} --failed"
    return finish(1, f"ci-status: {repo} {sha[:12]}: {out['state']}: {'; '.join(problems)}{note}{hint}")


if __name__ == "__main__":
    sys.exit(main())
