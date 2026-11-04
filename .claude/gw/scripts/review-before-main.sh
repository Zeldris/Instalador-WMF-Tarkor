#!/usr/bin/env bash
# galivelop-workflow v0.5.0
# Claude Code PreToolUse hook: no pull request reaches the protected branch without /code-review of the same code,
# and none is merged with CI not green (plan §5.2). Reads the hook JSON (tool_name, tool_input) on stdin.
#   - Create: mcp__github__create_pull_request, mcp__github__update_pull_request that sets `base` to the protected
#     branch, and `gh pr create` typed in Bash (no --base = the default branch, taken as protected). The PR head is
#     the branch on GitHub, read with `git ls-remote origin` (never the local HEAD; nothing written under refs/).
#     Its commit must carry the config's `reviewMark` naming an ancestor with no code after it (is-code.sh). A head
#     that brings no code against the protected branch needs no mark. The base is protected when the working tree's
#     config or the base's own tip on origin names it so; `content` and `reviewMark` come from that tip's config (the
#     PR head's only when the base has none yet), so a PR cannot relax the rule that judges it.
#   - Merge: mcp__github__merge_pull_request, mcp__github__enable_pr_auto_merge, and in Bash `gh pr merge` (also
#     `gh -R o/r pr merge`, inside `bash -c`/`eval`, after `xargs`) and `gh api` PUT on repos/<o>/<r>/pulls/<n>/merge
#     (-R/--repo and GH_REPO= name the repo). Same mark rule on the PR head, plus CI green: every check-run completed with success/neutral/skipped and every
#     commit status success (a commit with no CI reported at all is not green; that block names the path the person
#     can confirm instead: the local check, said as "checked only locally"). Check-runs that GitHub closed as failed
#     without starting the job (billing, spending limit) and nothing else failing get that same block. In those two
#     cases only, a green line of the config's `ciLocalLog` (written by ci-local.py --record, committed on the PR
#     head) lets the merge through when its commit is an ancestor of the head with only content after it; a CI that
#     started and failed is never replaced by it.
#   - Anything else (other tools, update_pull_request_branch, other bases, Bash that only mentions `gh pr`) exits 0
#     silently. pushToProtected does not matter: a PR is another way into the protected branch.
#   - A PR that is already closed or merged: blocked with that fact (and `gh pr view`), no config is asked of its branch;
#     an update_pull_request that itself reopens a closed PR (state: open) is judged like any other call on it.
#   - Before python3 starts, a bash pre-filter lets through everything that has no PR tool name and no word `gh` followed
#     by the word `pr`/`pulls` ("github", "projects" do not count). Without python3, a PR create/merge call is blocked
#     with the command that checks it (python3 --version); any other call, `gh pr view` included, passes.
# GitHub API: `gh api` when gh is on PATH and `gh api repos/<owner>/<repo>` answers (a GitHub App token cannot read
# /user but can read the repo), else curl with $GITHUB_TOKEN or $GH_TOKEN, decided once
# per run. No way to ask, or any API error: blocked (fail closed), as is any missing commit, config or script, and a
# Bash command that cannot be parsed but looks like `gh … pr merge|create`.
# Decision: exit 2 with the reason on stderr (Claude Code shows it to the agent); the last line is the command that
# fixes it. Exit 0 lets the call through. Never the JSON permissionDecision, so there is one way to read it.
# Project root: the git top level of this script's folder when it holds .claude/gw.json (the copy in
# .claude/gw/scripts); from the plugin cache, config.py's fallback (it is the only reader of the config).
# Bash 3.2 compatible; the logic is an embedded python3 (3.8+) run isolated (-I) so project files never shadow it.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
prog=""
IFS= read -r -d '' prog <<'PY' || true
import json, os, re, shlex, shutil, subprocess, sys

HERE = sys.argv[1]
NAME = "review-before-main"
GIT_ENV = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
GIT_ENV["GIT_TERMINAL_PROMPT"] = "0"
sys.dont_write_bytecode = True
sys.path.insert(0, HERE)
import importlib.util
# The API reader (token / gh discovery, CI state, ciIgnore) lives in ci-status.py: one place for it. Loaded by
# project() (a missing or broken copy blocks with the command that fixes it), so these names exist from then on.
ci_status = ApiError = api = NO_CI = None


class Blocked(Exception):
    pass


def block(*lines):
    raise Blocked("\n".join(lines))


def run(cmd, cwd=None, stdin=None):
    try:
        return subprocess.run(cmd, cwd=cwd, env=GIT_ENV, capture_output=True, text=True, input=stdin,
                              stdin=None if stdin is not None else subprocess.DEVNULL)
    except OSError as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


# ---- what the tool call does -------------------------------------------------------------------------------------
# Each command segment of a Bash call is tokenised (shlex) and read as a command: past VAR=x assignments, prefixes
# (env, command, exec, time, sudo, nohup, nice, timeout, stdbuf with their options, xargs and its options, shell keywords), into `bash|sh|zsh -c '<script>'` and
# `eval <words>`, then `gh [-R|--repo X] [--hostname X] pr [-R X] create|merge …` or `gh api` PUT on repos/<o>/<r>/pulls/<n>/
# merge. Text that only names it (grep "gh pr merge", echo '…') is an argument of another command, so not guarded.
SEPARATORS = set(";&|()\n")
PREFIXES = {"env", "command", "exec", "time", "sudo", "nohup", "nice", "timeout", "stdbuf", "!", "{", "}", "if", "then",
            "else", "elif", "do", "while", "until"}
# Prefixes that take options (and which options take a value in the next word): `nice -n 5`, `time -p`,
# `timeout -s KILL 5`, `env -u X`, `stdbuf -o0`, `sudo -u root`. `timeout` also takes a duration before the command.
PREFIX_OPTIONS = {
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "nice": {"-n", "--adjustment"},
    "time": {"-f", "--format", "-o", "--output"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "stdbuf": {"-i", "--input", "-o", "--output", "-e", "--error"},
    "sudo": {"-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt", "-C", "-D", "--chdir", "-R", "-r",
             "-t", "-T", "-U"},
    "exec": {"-a"}, "command": set(), "nohup": set(),
}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
XARGS_VALUE = {"-I", "-L", "-n", "-P", "-s", "-d", "-E", "-a", "--delimiter", "--max-args", "--max-procs",
               "--arg-file", "--replace", "--max-lines", "--eof", "--max-chars"}
GH_GLOBAL_VALUE = {"-R", "--repo", "--hostname"}
API_VALUE = {"-X", "--method", "-H", "--header", "-f", "--raw-field", "-F", "--field", "--input", "-q", "--jq", "-t",
             "--template", "--hostname", "-p", "--preview", "--cache"}
API_FIELDS = ("-f", "-F", "--field", "--raw-field", "--input")
API_MERGE = re.compile(r"^/?repos/([^/]+)/([^/]+)/pulls/(\d+)/merge/?$")
MERGE_VALUE_FLAGS = {"-R", "--repo", "-b", "--body", "-F", "--body-file", "-t", "--subject", "-A",
                     "--author-email", "--match-head-commit"}
GH_WORD = re.compile(r"\bgh\b")
PR_WORD = re.compile(r"\bpr\b")
PR_ACTION = re.compile(r"\b(merge|create)\b")
PULLS_TOKEN = re.compile(r"pulls/\S*")


def looks_like_pr_action(command):
    """Does an unparseable command look like `gh ... pr ... merge|create` or `gh ... pulls/...merge`?

    The words must come in that order; the earliest `gh`, then the earliest `pr` after it, is enough. One scan per
    word: a single regex chaining `[\\s\\S]*` between them backtracks without end on a long command (P4 of
    proposal 2026-10-25-repos-x.md; tests/test_review_before_main.py times it)."""
    gh = GH_WORD.search(command)
    if not gh:
        return False
    pr = PR_WORD.search(command, gh.end())
    if pr and PR_ACTION.search(command, pr.end()):
        return True
    return any("merge" in m.group()[len("pulls/"):] for m in PULLS_TOKEN.finditer(command, gh.end()))


def flag(args, names):
    """Value of the last --name value / --name=value / -X value among args, or None."""
    value = None
    for i, a in enumerate(args):
        for n in names:
            if a == n and i + 1 < len(args):
                value = args[i + 1]
            elif n.startswith("--") and a.startswith(n + "="):
                value = a.split("=", 1)[1]
            elif not n.startswith("--") and len(n) == 2 and a.startswith(n) and len(a) > 2 and not a.startswith("--"):
                value = a[2:]
    return value


def segments(command):
    """Lists of words, one per command segment (split on ; & | ( ) and newlines). Raises ValueError (bad quoting)."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""  # a comment would swallow the newline that ends the segment
    out, cur, skip = [], [], False
    for tok in lex:
        if tok and all(c in SEPARATORS for c in tok):
            if cur:
                out.append(cur)
            cur, skip = [], False
        elif tok and all(c in "<>&" for c in tok) and ("<" in tok or ">" in tok):
            skip = True  # a redirection: the next word is its target
        elif skip:
            skip = False
        else:
            cur.append(tok)
    if cur:
        out.append(cur)
    return out


COMMENT_START = re.compile(r"(?:^|[\s;&|()])#")


def join_lines(command, glue, comments_end_lines):
    """The command with its line continuations joined by glue. A newline continues the line only after an odd run of
    backslashes (`\\\\<newline>` is a literal backslash and the newline ends the command); with comments_end_lines, also
    only when the line has no comment (a comment ends at the newline, a backslash in it continues nothing)."""
    lines = command.split("\n")
    out = []
    for n, line in enumerate(lines):
        body = line[:-1] if line.endswith("\r") and n < len(lines) - 1 else line
        run = len(body) - len(body.rstrip("\\"))
        if n < len(lines) - 1 and run % 2 == 1:
            if comments_end_lines and COMMENT_START.search(body):
                out.append(body[:-1] + "\n")  # inert in a comment; dropped so shlex does not glue the newline to a word
            else:
                out.append(body[:-1] + glue)
        else:
            out.append(line + ("\n" if n < len(lines) - 1 else ""))
    return "".join(out)


def from_bash(command, depth=0):
    if depth > 5:
        block("the command nests shells too deeply to check.", "run the gh command directly and retry")
    # Bash joins a backslash-newline continuation (`pulls/7/\\<nl>merge` is `pulls/7/merge`, `gh\\<nl>pr` is `ghpr`),
    # but not after an escaped backslash, and a comment ends at the newline. The reader cannot tell quoting from that
    # apart, so the union of readings is judged: the text as it is, and the continuations joined (glued, or with a
    # space, with and without comments ending their line). Never a physical line alone: a line cut out of a quoted
    # string or a heredoc body would be read as a command (git commit -m "…<nl>gh pr merge 7 …"). When the text as
    # it is parses, a joined reading that does not is ignored. When it does not (an apostrophe in a comment, $'…'),
    # the joined ones fail the same way, so the command is blocked if ANY reading looks like a PR create/merge (a
    # continuation can split the words: `gh pr mer\\<nl>ge 7`). Each action once.
    readings = {command: None}
    for glue in ("", " "):
        for comments in (False, True):
            readings[join_lines(command, glue, comments)] = None
    actions, seen = [], set()
    for text in readings:
        found = from_text(text, depth)
        if found is None:
            if text == command and any(looks_like_pr_action(t) for t in readings):
                block(f"cannot parse the command ({parse_error(command)}) and it looks like a PR create/merge; blocked "
                      "because it could not be checked.",
                      "write it as a plain command and retry, e.g.: gh pr merge <number> -R <owner>/<repo>")
            continue
        for action in found:
            key = json.dumps(action, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                actions.append(action)
    return actions


def parse_error(command):
    try:
        segments(command)
    except ValueError as exc:
        return str(exc)
    return "bad quoting"


def from_text(command, depth):
    """The actions of one reading, or None when it cannot be parsed."""
    try:
        segs = segments(command)
    except ValueError:
        return None
    actions = []
    for words in segs:
        actions += from_words(words, depth)
    return actions


def from_words(words, depth):
    env_repo = None
    i = 0
    while i < len(words):
        w = words[i].lstrip("`")
        if not w or w == "$":
            i += 1
        elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w):
            if w.startswith("GH_REPO="):
                env_repo = w.split("=", 1)[1] or None
            i += 1
        elif w in PREFIXES:
            i += 1
            if w in PREFIX_OPTIONS:
                while i < len(words) and words[i].startswith("-") and words[i] != "-":
                    opt = words[i]
                    # `-u X`, and combined short flags whose last letter takes the value (`sudo -Eu root`)
                    takes = opt in PREFIX_OPTIONS[w] or (
                        len(opt) > 2 and opt[1] != "-" and "-" + opt[-1] in PREFIX_OPTIONS[w])
                    i += 2 if takes else 1
                    if opt == "--":
                        break
                if w == "timeout" and i < len(words):
                    i += 1  # the duration
        elif os.path.basename(w) == "xargs":
            i += 1
            while i < len(words) and words[i].startswith("-"):
                i += 2 if words[i] in XARGS_VALUE else 1
        else:
            break
    if i >= len(words):
        return []
    cmd, args = os.path.basename(words[i].lstrip("`")), [a.rstrip("`") for a in words[i + 1:]]
    if cmd in SHELLS:
        for j, a in enumerate(args):
            if re.match(r"^-[A-Za-z]*c[A-Za-z]*$", a) and j + 1 < len(args):
                return from_bash(args[j + 1], depth + 1)
        return []
    if cmd == "eval":
        return from_bash(" ".join(args), depth + 1)
    if cmd != "gh":
        return []
    j, repo = gh_flags(args, 0, env_repo)
    rest = args[j:]
    if rest and rest[0] == "pr":  # `gh pr --repo o/r merge 7`: -R/--repo also goes between `pr` and the subcommand
        j, repo = gh_flags(rest, 1, repo)
        rest = ["pr"] + rest[j:]
    if len(rest) >= 2 and rest[0] == "pr" and rest[1] in ("create", "merge"):
        return [pr_action(rest[1], rest[2:], repo)]
    if rest and rest[0] == "api":
        return api_action(rest[1:], repo)
    return []


def gh_flags(args, j, repo):
    """Skip the leading flags of args from index j (-R/--repo/--hostname take a value); returns (index, repo)."""
    while j < len(args) and args[j].startswith("-"):
        a = args[j]
        if a in GH_GLOBAL_VALUE and j + 1 < len(args):
            if a in ("-R", "--repo"):
                repo = args[j + 1]
            j += 2
            continue
        if a.startswith("--repo="):
            repo = a.split("=", 1)[1]
        elif a.startswith("-R") and len(a) > 2:
            repo = a[2:]
        j += 1
    return j, repo


def pr_action(kind, args, repo):
    repo = flag(args, ("-R", "--repo")) or repo
    if kind == "create":
        return {"kind": "create", "base": flag(args, ("-B", "--base")), "head": flag(args, ("-H", "--head")),
                "repo": repo, "number": None, "how": "gh pr create"}
    selector, skip = None, False
    for a in args:
        if skip:
            skip = False
        elif a in MERGE_VALUE_FLAGS:
            skip = True
        elif not a.startswith("-") and selector is None:
            selector = a
    number, branch = None, None
    if selector:
        url = re.search(r"github\.com/([^/]+/[^/]+)/pull/(\d+)", selector)
        if url:
            repo, number = repo or url.group(1), url.group(2)
        elif selector.lstrip("#").isdigit():
            number = selector.lstrip("#")
        else:
            branch = selector
    return {"kind": "merge", "base": None, "head": branch, "repo": repo, "number": number, "how": "gh pr merge"}


def api_action(args, repo):
    method, fields, path, skip = None, False, None, False
    for i, a in enumerate(args):
        if skip:
            skip = False
            continue
        if a in ("-X", "--method"):
            method = args[i + 1] if i + 1 < len(args) else None
            skip = True
        elif a.startswith("--method="):
            method = a.split("=", 1)[1]
        elif a.startswith("-X") and len(a) > 2:
            method = a[2:]
        elif a in API_FIELDS or any(a.startswith(f + "=") for f in API_FIELDS if f.startswith("--")) or \
                (a[:2] in ("-f", "-F") and len(a) > 2):
            fields = True
            skip = a in API_FIELDS
        elif a in API_VALUE:
            skip = True
        elif not a.startswith("-") and path is None:
            path = a
    m = API_MERGE.match(path or "")
    if not m or not ((method or "").upper() == "PUT" or (method is None and fields)):
        return []
    owner, name = m.group(1), m.group(2)
    if "{" not in owner + name:  # {owner}/{repo} placeholders: gh fills them from the current repo
        repo = f"{owner}/{name}"
    return [{"kind": "merge", "base": None, "head": None, "repo": repo, "number": m.group(3),
             "how": f"gh api PUT {path}"}]


def classify(event):
    tool = str(event.get("tool_name") or "")
    data = event.get("tool_input") or {}
    if not isinstance(data, dict):
        data = {}
    if tool == "Bash":
        return from_bash(str(data.get("command") or ""))
    if not tool.startswith("mcp__"):
        return []
    name = tool.rsplit("__", 1)[-1]
    repo = None
    if data.get("owner") and data.get("repo"):
        repo = f"{data['owner']}/{data['repo']}"
    number = str(data["pullNumber"]) if data.get("pullNumber") not in (None, "") else None
    if name == "create_pull_request":
        return [{"kind": "create", "base": data.get("base") or None, "head": data.get("head") or None, "repo": repo,
                 "number": None, "how": "create_pull_request"}]
    if name == "update_pull_request":
        if not data.get("base"):
            return []  # editing title/body/state takes nothing to another branch
        return [{"kind": "retarget", "base": data["base"], "head": None, "repo": repo, "number": number,
                 "how": "update_pull_request", "reopens": data.get("state") == "open"}]
    if name in ("merge_pull_request", "enable_pr_auto_merge"):
        return [{"kind": "merge", "base": None, "head": None, "repo": repo, "number": number, "how": name}]
    return []  # update_pull_request_branch and the rest bring nothing new to the protected branch


# ---- project, git and GitHub -------------------------------------------------------------------------------------
def project():
    sys.dont_write_bytecode = True  # never leave __pycache__ in the project's scripts folder
    sys.path.insert(0, HERE)
    try:
        import config  # the only reader of .claude/gw.json
    except ImportError as exc:
        block(f"cannot load config.py next to {HERE} ({exc}).", "reinstall the workflow: /gw-update")
    global ci_status, ApiError, api, NO_CI
    try:
        spec = importlib.util.spec_from_file_location("ci_status", os.path.join(HERE, "ci-status.py"))
        ci_status = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ci_status)
    except Exception as exc:  # missing file, syntax error...
        block(f"cannot load ci-status.py next to {HERE} ({exc}).", "reinstall the workflow: /gw-update")
    ApiError, api, NO_CI = ci_status.ApiError, ci_status.api, ci_status.NO_CI
    try:
        cfg = config.load()
    except config.ConfigError as exc:
        block(f"cannot read the project config: {exc}",
              f"fix it and retry: python3 {os.path.join(HERE, 'config.py')} validate")
    root = str(cfg["_root"])
    own = run(["git", "-C", HERE, "rev-parse", "--show-toplevel"]).stdout.strip()
    candidates = [os.path.join(root, ".claude", "gw", "scripts")]
    if own and os.path.realpath(own) == os.path.realpath(root):
        candidates.append(HERE)
    scripts = next((c for c in candidates if os.path.isfile(os.path.join(c, "is-code.sh"))), None)
    if scripts is None:
        block(f"the workflow scripts are missing in {root} (.claude/gw/scripts/is-code.sh).",
              "reinstall them: /gw-update")
    return cfg, root, scripts


def git(root, *args):
    return run(["git", "-C", root, *args])


def has_commit(root, sha):
    return git(root, "cat-file", "-e", sha + "^{commit}").returncode == 0


def remote_sha(root, branch):
    r = git(root, "ls-remote", "origin", "refs/heads/" + branch)
    if r.returncode != 0:
        block(f"cannot query origin for {branch}: {(r.stderr or r.stdout).strip()[:300]}",
              f"check the remote and the network, then retry: git -C {root} ls-remote origin refs/heads/{branch}")
    words = r.stdout.split()
    return words[0] if words else None


def ensure(root, sha, refs):
    """Make sha present locally, fetching refs from origin without writing any ref (nor FETCH_HEAD when possible)."""
    if has_commit(root, sha):
        return True
    for ref in refs:
        if not ref:
            continue
        # --refmap= stops git updating refs/remotes/origin/<branch> on its own.
        r = git(root, "fetch", "-q", "--no-write-fetch-head", "--refmap=", "origin", ref)
        if r.returncode != 0 and "no-write-fetch-head" in r.stderr:
            git(root, "fetch", "-q", "--refmap=", "origin", ref)  # git < 2.29: FETCH_HEAD only, still no ref
        if has_commit(root, sha):
            return True
    return False


def origin_repo(root):
    url = git(root, "remote", "get-url", "origin").stdout.strip()
    m = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def pr_info(repo, number):
    try:
        info = api(f"repos/{repo}/pulls/{number}")
        return {"base": info["base"]["ref"], "sha": info["head"]["sha"], "ref": info["head"]["ref"],
                "url": info.get("html_url") or f"https://github.com/{repo}/pull/{number}",
                "state": info.get("state") or "open", "merged": bool(info.get("merged") or info.get("merged_at"))}
    except ApiError as exc:
        block(f"cannot read PR #{number} of {repo}: {exc}",
              "authenticate (gh auth login, or export GITHUB_TOKEN) and retry; blocked because it could not be checked")
    except (KeyError, TypeError) as exc:
        block(f"PR #{number} of {repo}: unexpected API answer (missing {exc}).",
              f"check the PR at https://github.com/{repo}/pull/{number} and retry")


# ---- the rules ---------------------------------------------------------------------------------------------------
# A green line of ci-local.py --record on a clean tree: `- <date> · `<sha>` · green (` (a dirty tree adds
# " (uncommitted changes)" after the sha, so it never matches).
LOCAL_GREEN = re.compile(r"^- \S+ · `([0-9a-f]{7,40})` · green \(", re.M)


def ci_local_green(root, scripts, head, policy):
    """The commit of the newest green local CI run recorded on `head` that is an ancestor of it with only content
    after it, or None."""
    log = config_at(root, policy, paths_at=head)["ciLocalLog"]
    text = git(root, "show", f"{head}:{log}").stdout
    for short in reversed(LOCAL_GREEN.findall(text)):
        r = git(root, "rev-parse", "-q", "--verify", short + "^{commit}")
        sha = r.stdout.strip()
        if r.returncode == 0 and git(root, "merge-base", "--is-ancestor", sha, head).returncode == 0 \
                and not es_codigo(root, scripts, sha, head, policy):
            return sha
    return None


def es_codigo(root, scripts, a, b, rev):
    r = run(["bash", os.path.join(scripts, "is-code.sh"), "--rev", rev, a, b], cwd=root)
    if r.returncode != 0:
        block(f"cannot tell code from content: {r.stderr.strip()[:400]}",
              f"fix the error above and retry: git -C {root} fetch origin")
    return [line for line in r.stdout.splitlines() if line.strip()]


_configs = {}


def config_at(root, rev, strict=True, paths_at=None):
    """The config as commit `rev` has it, or None when that commit has no .claude/gw.json. An invalid one blocks, or
    with strict=False is None too (it names no protected branch). Loaded once per commit. `paths_at`: the commit whose
    files decide the old-Spanish-path fallback (the PR head), so the same commit gets the same paths everywhere."""
    import config  # on sys.path since project()
    key = (rev, paths_at)
    if key not in _configs:
        if git(root, "cat-file", "-e", f"{rev}:.claude/gw.json").returncode != 0:
            _configs[key] = (None, None)
        else:
            try:
                _configs[key] = (config.load(root, rev=rev, paths_at=paths_at), None)
            except config.ConfigError as exc:
                _configs[key] = (None, exc)
    cfg, error = _configs[key]
    if error is not None and strict:
        block(f"cannot read the config of {rev[:12]}: {error}",
              f"fix it on that branch and retry: python3 {os.path.join(HERE, 'config.py')} --rev {rev[:12]} validate")
    return cfg


def protected_tip(cfg, root, base):
    """The origin tip of `base` when the PR goes to a protected branch, as the working tree's config or that tip's own
    config names it (a PR cannot unprotect its base by renaming protectedBranch); None when the base is not protected.
    Returns (protected, tip): tip is None for a protected branch not on origin yet."""
    tip = remote_sha(root, base)
    if base == cfg["protectedBranch"]:
        return True, tip
    if tip and ensure(root, tip, [base]):
        remote = config_at(root, tip, strict=False)  # an invalid one there must not block a PR to an open branch
        if remote is not None and remote["protectedBranch"] == base:
            return True, tip
    return False, tip


def check_mark(cfg, root, scripts, head, refs, what, protected, tip):
    if not ensure(root, head, refs):
        block(f"the PR head {head[:12]} ({what}) is not in this clone and could not be fetched from origin.",
              f"fetch it and retry: git -C {root} fetch origin {refs[0] if refs else ''}".rstrip())
    base, policy = "", head
    if tip:
        if not ensure(root, tip, [protected]):
            block(f"origin/{protected} is at {tip[:12]}, which this clone cannot fetch.",
                  f"fetch it and retry: git -C {root} fetch origin {protected}")
        mb = git(root, "merge-base", tip, head)
        base = mb.stdout.strip() if mb.returncode == 0 else ""
        if config_at(root, tip) is not None:
            policy = tip  # what is content and where the mark lives: the protected branch decides, not the PR
    if policy == head and config_at(root, head) is None:
        block(f"neither origin/{protected} nor the PR head {head[:12]} ({what}) has a .claude/gw.json.",
              "commit a valid one on the PR branch and retry: git add .claude/gw.json && git commit && git push")
    mark_file = config_at(root, policy, paths_at=head)["reviewMark"]
    fix = (f"run /code-review of the diff against origin/{protected}, push the fixes, then mark and push: "
           f"bash {os.path.join(scripts, 'reviewed.sh')} && git push")
    code = es_codigo(root, scripts, base, head, policy)
    if not code:
        return  # only content against the protected branch: no review needed
    mark = "".join(git(root, "show", f"{head}:{mark_file}").stdout.split())
    if not mark:
        reason = f"the PR head {head[:12]} ({what}) has no review mark ({mark_file})"
    elif not has_commit(root, mark):
        reason = f"the review mark ({mark_file}) names {mark[:12]}, which is not a commit in this clone"
    elif git(root, "merge-base", "--is-ancestor", mark, head).returncode != 0:
        reason = f"the review mark ({mark[:12]}) is not an ancestor of the PR head {head[:12]} ({what})"
    else:
        after = es_codigo(root, scripts, mark, head, policy)
        if not after:
            return
        reason, code = f"code changed after the review mark ({mark[:12]}) on the PR head {head[:12]} ({what})", after
    listed = [f"  {path}" for path in code[:10]] + ([f"  … and {len(code) - 10} more"] if len(code) > 10 else [])
    block(f"Blocked: {reason}; this PR brings unreviewed code to {protected}:", *listed, fix)


def head_from_branch(root, branch, how):
    branch = branch.split(":")[-1]  # head may come as owner:branch
    sha = remote_sha(root, branch)
    if not sha:
        block(f"the PR branch {branch} is not on origin ({how}), so its reviewed commit cannot be checked.",
              f"push it and retry: git push -u origin {branch}")
    return sha, branch


def need_repo(action, root):
    repo = action["repo"] or origin_repo(root)
    if not repo:
        block(f"cannot tell the GitHub owner/repo for {action['how']} (no owner/repo in the call, origin is not "
              "a github.com URL).", "pass it explicitly and retry, e.g.: gh pr merge <number> -R <owner>/<repo>")
    return repo


def handle(action, cfg, root, scripts):
    if action["kind"] in ("create", "retarget"):
        protected = action["base"] or cfg["protectedBranch"]  # no base: the default branch, guarded as protected
        guarded, tip = protected_tip(cfg, root, protected)
        if not guarded:
            return
    if action["kind"] == "create":
        branch = action["head"]
        if not branch:
            branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            if not branch or branch == "HEAD":
                block(f"{action['how']}: no --head given and the checkout is not on a branch.",
                      "switch to the PR branch and retry: git switch <branch>")
        sha, branch = head_from_branch(root, branch, action["how"])
        check_mark(cfg, root, scripts, sha, [branch], f"origin/{branch}", protected, tip)
        return
    repo = need_repo(action, root)
    number = action["number"]
    if number is None and action["kind"] == "merge":
        branch = action["head"] or git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        owner = repo.split("/")[0]
        try:
            found = api(f"repos/{repo}/pulls?head={owner}:{branch}&state=open")
            number = str(found[0]["number"]) if found else None
        except (ApiError, KeyError, TypeError, IndexError) as exc:
            block(f"cannot find the open PR of {branch} in {repo}: {exc}",
                  "pass the PR number and retry: gh pr merge <number>")
        if number is None:
            block(f"no open PR for {branch} in {repo}.", "pass the PR number and retry: gh pr merge <number>")
    if number is None:
        block(f"{action['how']} without a PR number; cannot check it.", "pass pullNumber and retry")
    info = pr_info(repo, number)
    reopened = action.get("reopens") and not info["merged"]  # the call itself reopens it: judge it as open
    if info["state"] != "open" and not reopened:  # nothing to guard: say so instead of asking for a gw.json on a finished branch
        done = "already merged" if info["merged"] else "closed"
        block(f"PR #{number} of {repo} is {done}, so {action['how']} has nothing to do.",
              f"check it: gh pr view {number} -R {repo}" + ("" if info["merged"] else " (reopen it if it should still be merged)"))
    if action["kind"] == "merge":
        protected = info["base"]
        guarded, tip = protected_tip(cfg, root, protected)
        if not guarded:
            return
    refs = [info["ref"], f"refs/pull/{number}/head"]
    check_mark(cfg, root, scripts, info["sha"], refs, f"PR #{number}", protected, tip)
    if action["kind"] != "merge":
        return
    try:
        policy = tip if tip and config_at(root, tip) is not None else info["sha"]
        ignore = config_at(root, policy, paths_at=info["sha"])["ciIgnore"]  # the protected branch decides
        bad, unstarted = ci_status.ci_problems(repo, info["sha"], ignore)
    except (ApiError, KeyError, TypeError, ValueError) as exc:
        block(f"Blocked: could not verify CI of PR #{number} ({info['sha'][:12]}): {exc}",
              f"check CI in the PR ({info['url']}); once it is all green, authenticate (gh auth login, or export "
              "GITHUB_TOKEN) and retry the merge")
    if bad == [NO_CI] or (bad and unstarted):
        if ci_local_green(root, scripts, info["sha"], policy):
            return  # the CI run locally, green, on this code: the person confirmed it ("checked only locally")
        log = config_at(root, policy, paths_at=info["sha"])["ciLocalLog"]
        what = f"no CI has reported on PR #{number} ({info['sha'][:12]})" if bad == [NO_CI] else \
            f"GitHub did not start the CI of PR #{number} ({info['sha'][:12]}): billing or spending limit; nothing ran"
        block(f"Blocked: {what}, and {log} on the PR head has no green local run of this code (a clean tree, an "
              "ancestor of the head with only content after it).",
              f"if CI does not start (no Actions quota, no runners), tell the person: with their confirmation the CI "
              f"run locally counts, said as 'checked only locally'; then run it, commit and push the log, and retry: "
              f"python3 {os.path.join(scripts, 'ci-local.py')} --record && git add {log} && "
              f"git commit -m 'CI run locally' && git push")
    if bad:
        block(f"Blocked: CI of PR #{number} ({info['sha'][:12]}) is not green: {'; '.join(bad)}",
              f"wait until every check passes ({info['url']}), fix what failed if needed, then retry the merge")


def main():
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except ValueError as exc:
        block(f"the hook input is not JSON ({exc}).", "report it: Claude Code sent an unexpected payload")
    actions = classify(event if isinstance(event, dict) else {})
    if not actions:
        return
    cfg, root, scripts = project()
    for action in actions:
        handle(action, cfg, root, scripts)


try:
    main()
except Blocked as exc:
    for line in str(exc).splitlines():
        print(f"{NAME}: {line}", file=sys.stderr)
    sys.exit(2)
except Exception as exc:  # fail closed on anything unexpected
    print(f"{NAME}: unexpected error ({type(exc).__name__}: {exc}); blocked because it could not be checked.",
          file=sys.stderr)
    print(f"{NAME}: fix or report it, then retry: bash {os.path.join(HERE, 'review-before-main.sh')} < input.json",
          file=sys.stderr)
    sys.exit(2)
PY
input="$(cat)"
# Cheap pre-filter, in bash with no external tools: the matcher includes every Bash call, so what cannot be a PR action
# leaves here without python3 (a missing python3 must not block unrelated commands). It goes on for the PR tools, and
# for text with the word `gh` (not "github") followed by the word `pr` or `pulls` (not "projects").
# A word separator: anything but a letter, digit, _ or -; and the JSON escapes of a tab, newline or carriage return
# (backslash + letter in the raw input, also after a backslash continuation), which separate words like a space.
word='(\\([tnr]|u000[9aAdD])|[^[:alnum:]_-])'
tool='"tool_name"[[:space:]]*:[[:space:]]*'
pr_tools="${tool}\"mcp__[^\"]*(create_pull_request|update_pull_request|merge_pull_request|enable_pr_auto_merge)\""
bash_tool="${tool}\"Bash\""
gh="(^|$word)gh$word"
end="($word|\$)"
any_pr="(^|$word)(pr|pulls)${end}"
pr_word="(^|$word)pr$word"
pr_action="(^|$word)(create|merge)${end}"
# One regex per word, each on what follows the previous match: a single regex with `.*` between the words backtracks
# quadratically on a long command (P4 of proposal 2026-10-25-repos-x.md; tests/test_review_before_main.py times it).
# after_first <text> <regex> sets `after` to the text following the first match of the regex, or fails.
after=""
after_first() {
  [[ $1 =~ $2 ]] || return 1
  local lit="${BASH_REMATCH[0]}" before
  before="${1%%"$lit"*}"
  after="${1:$((${#before} + ${#lit}))}"
}
# gh creating/merging: `gh ... pr ... create|merge` or `gh ... pulls/... merge`, the words in that order.
gh_does_pr() {
  local rest
  after_first "$1" "$gh" || return 1
  rest="$after"
  if after_first "$rest" "$pr_word" && [[ $after =~ $pr_action ]]; then return 0; fi
  # pulls/ and then merge, anywhere after it (not only in the same word): the regex for "in the same word" backtracks
  # quadratically on one long word. A looser match here only makes python3 run, or a call without python3 be refused.
  local before="${rest%%pulls/*}"
  [[ ${#before} -lt ${#rest} ]] || return 1
  rest="${rest:$((${#before} + 6))}"
  [[ $rest == *merge* ]]
}
own=""  # 1 when the call is one this hook decides on (a PR tool, or gh creating/merging), for the python3-missing case
if [[ $input =~ $pr_tools ]]; then own=1
elif [[ $input =~ $bash_tool ]]; then
  # A backslash-newline continuation can split a word (`g\<nl>h pr merge 7` is `gh pr merge 7`); in the raw JSON it is
  # backslash, backslash, backslash + n (or + r, backslash, n). The text with them removed is looked at too; a wrong
  # join only makes python3 run. sed, not ${input//…/}: bash's replace is quadratic in the number of continuations.
  cont_crlf='\\\r\n'; cont_lf='\\\n'; joined="$input"
  case $input in *'\\\n'* | *'\\\r\n'*)
    # Without sed (or if it fails), the slow join in bash: never skip the joined text.
    joined="$(printf '%s' "$input" | sed -e 's/\\\\\\r\\n//g' -e 's/\\\\\\n//g' 2>/dev/null)" ||
      { joined="${input//"$cont_crlf"/}"; joined="${joined//"$cont_lf"/}"; } ;;
  esac
  for text in "$input" "$joined"; do
    if after_first "$text" "$gh" && [[ $after =~ $any_pr ]]; then
      if gh_does_pr "$text"; then own=1; elif [ "$own" != "1" ]; then own=0; fi
    fi
  done
  [ -n "$own" ] || exit 0
else exit 0
fi
if ! command -v python3 >/dev/null 2>&1; then
  if [ "$own" = "1" ]; then
    echo "review-before-main: python3 is missing, so this PR call cannot be checked; blocked. Install python3 3.8+ and retry: python3 --version" >&2
    exit 2
  fi
  exit 0  # gh pr view/list/…: not a call this hook decides on
fi
printf '%s' "$input" | python3 -I -c "$prog" "$here"
status=$?
if [ "$status" -ne 0 ] && [ "$status" -ne 2 ]; then  # python3 crashed: still fail closed
  echo "review-before-main: the check could not run (exit $status); blocked. Check python3 3.8+ and retry: python3 --version" >&2
  exit 2
fi
exit "$status"
