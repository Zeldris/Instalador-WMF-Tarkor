#!/usr/bin/env python3
# galivelop-workflow v0.6.0
"""Check that a project has the workflow set up (used by /gw-doctor and CI). No AI, no network.

  python3 doctor.py            # one line per check: OK / WARN / FAIL, each problem with the command that fixes it
  python3 doctor.py --json     # the same as a JSON list of {status, check, message, fix}
  python3 doctor.py --root R   # check the project at R (default: config.find_root)

Exit 1 if any check FAILs (WARNs do not fail). Checks: the config; core.hooksPath and other hook managers; the git
hooks (present, executable, version); the log and its next step; the `check`, `install` and `setup` commands exist (and a
`bash -n`/`sh -n` `check` command that reads only one file: `check syntax-only`); a CI
workflow; .claude/settings.json (WMF P4: SessionStart matchers, `compact` only runs recover.py --state, hook
commands point to existing files, the PR guard on PreToolUse); AGENTS.md/CLAUDE.md authorise dealing work to
subagents (private-project-1 P1); copied skills at the config's version; a session opened outside the repo (private-project-1 P3);
in a cloud session (CLAUDE_CODE_REMOTE=true), the compaction window the project's settings.json sets is in the
environment; a skill script under .claude/skills/*/scripts/ without a test_<name>.py next to it (WMF 2026-10-25 P2); and,
only in a project that uses gw-media-content (its note .claude/gw/gw-media-content.md or its folder exists), node,
Playwright and ImageMagick with WebP (WMF 2026-10-25 P1), and a leftover docs/difusion (the folder before A8; warns
while the note names no other); and, when `origin` is on GitHub, a way to read the CI state
(`gh` logged in, or GITHUB_TOKEN/GH_TOKEN set); and (B11, `models.checkLevers`) no global variable that overrides the model
or effort picked per agent (CLAUDE_CODE_EFFORT_LEVEL, CLAUDE_CODE_SUBAGENT_MODEL with _FORCE, CLAUDE_CODE_SUBAGENT_EFFORT)
in the environment or the env block of .claude/settings.json, .claude/settings.local.json or ~/.claude/settings.json;
and (E43) a folder holding test_*.py that no `check` command runs (`test dirs`, see check_test_dirs; the folders to skip
are the `doctorTestDirsIgnore` key).
The compaction check, the session one, the levers one, the media tools one and the CI
access one read the machine running doctor, not only the project, so their lines can differ between a person's machine,
CI and a cloud session.
Python 3.8+ standard library only.
"""
import argparse
import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, str(HERE))
import config  # noqa: E402
import session_log  # noqa: E402

HEADER = re.compile(r"^# galivelop-workflow v(\S+)\s*$", re.M)
NEXT_STEP = re.compile(r"siguientes? pasos?|next steps?", re.I)
PR_TOOLS = ("create_pull_request", "merge_pull_request")
PR_GUARD = "review-before-main.sh"
INTERPRETERS = {"bash", "sh", "zsh", "python", "python3", "node", "env", "exec"}
SOURCES = re.compile(r"galivelop|workflow|mattpocock", re.I)
PROPOSAL = ".gw-new"  # apply.py's proposals for files with local edits
OLD_PROPOSAL = ".gw-nuevo"  # A8 (0.x): the suffix before the rename; still recognized, with a warning
FLOW_HOOK_SCRIPTS = ("session-start.sh", "recover.py", "review-before-main.sh", "before-stop.py",
                     "config-guard.py", "subagent-cap.py", "agent-signatures.py", "metrics.py",
                     "whole-read.py")  # the settings template's
# Zero-width, bidi and BOM characters, written as escapes so the fix command can embed them. A zero width joiner (U+200D)
# is fine only inside an emoji sequence (family, profession, flag, heart): after an emoji, a variation selector or a
# skin tone, and before an emoji. Between letters, accents or punctuation (`и‍г`, `é‍ñ`), next to ASCII, a line edge
# or another invisible character it is flagged like the rest, since it can hide a split inside a word.
ALWAYS_INVISIBLE = r"\u200b\u200c\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff"  # flagged wherever they are
EMOJI = r"\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff"  # symbols and pictographs, dingbats, arrows and stars
BEFORE_JOINER = rf"{EMOJI}\ufe0f\U0001f3fb-\U0001f3ff"  # an emoji, its variation selector or a skin tone
INVISIBLE_PATTERN = (rf"[{ALWAYS_INVISIBLE}]"
                     rf"|(?<![{BEFORE_JOINER}])\u200d"
                     rf"|\u200d(?![{EMOJI}])")
INVISIBLE = re.compile(INVISIBLE_PATTERN)
MEDIA_NOTE = ".claude/gw/gw-media-content.md"  # the project's note of gw-media-content (skills/gw-media-content/note.md)
MEDIA_FOLDER = "docs/media"  # its default `Folder`
OLD_MEDIA_FOLDER = "docs/difusion"  # A8 (0.x): the default before the rename; used, with a warning, while it is the only one
SKILL_LICENSE = "LICENSE-mattpocock-skills"  # apply.py copies it next to the skills that cite it


class Report:
    def __init__(self):
        self.items = []

    def add(self, status, check, message, fix=""):
        self.items.append({"status": status, "check": check, "message": message, "fix": fix})

    def ok(self, check, message):
        self.add("OK", check, message)

    def warn(self, check, message, fix):
        self.add("WARN", check, message, fix)

    def fail(self, check, message, fix):
        self.add("FAIL", check, message, fix)

    def failed(self):
        return any(i["status"] == "FAIL" for i in self.items)

    def lines(self):
        for i in self.items:
            text = f"{i['status']:<4} {i['check']}: {i['message']}"
            yield text + (f"; fix: {i['fix']}" if i["fix"] else "")


def git(root, *args):
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def header_version(path):
    try:
        m = HEADER.search("\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[:5]))
    except OSError:
        return None
    return m.group(1) if m else None


def chain_hint(hooks_dir):
    return (f"add as the last line of {hooks_dir}/pre-push, {hooks_dir}/pre-commit and {hooks_dir}/commit-msg (with <hook> = the file's "
            f"name): \"$(git rev-parse --show-toplevel)/.githooks/<hook>\" \"$@\" || exit 1")


def first_word(command):
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    for w in words:
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w):  # FOO=bar cmd
            continue
        return w
    return None


def resolves(word, root):
    if word is None:
        return False
    if "/" in word:
        return (root / word).exists() or Path(word).exists()
    if shutil.which(word):
        return True
    try:  # shell builtins and functions (cd, test, source...)
        return subprocess.run(["bash", "-c", f"command -v -- {shlex.quote(word)}"], capture_output=True,
                              cwd=str(root)).returncode == 0
    except OSError:
        return False


# ---------------------------------------------------------------- checks

def check_config(rep, root):
    try:
        cfg = config.load(root)
    except config.ConfigError as exc:
        rep.fail("config", str(exc).splitlines()[0], f"python3 {HERE / 'config.py'} --root {root} validate")
        return None
    rep.ok("config", f".claude/gw.json valid (version {cfg['version']})")
    found = cfg.get("_schemaFrom", config.SCHEMA_VERSION)
    if found < config.SCHEMA_VERSION:  # a newer one already failed in config.load
        rep.warn("config schema", f".claude/gw.json has schemaVersion {found} (absent = 0) and the workflow's format is "
                 f"{config.SCHEMA_VERSION}; it is migrated in memory on every read until it is written",
                 "run /gw-update (apply.py writes the migrated config)")
    else:
        rep.ok("config schema", f".claude/gw.json schemaVersion {found} is the workflow's format")
    return cfg

# What a commit must carry for the workflow to work; a `.gitignore` with `.claude/*` would leave it out.
MUST_BE_TRACKED = (".claude/gw.json", ".claude/gw/scripts/config.py", ".claude/settings.json",
                   ".claude/skills/gw-selector/SKILL.md", ".githooks/pre-push")


def must_be_tracked(root):
    """MUST_BE_TRACKED plus the config's `reviewMark` file: git ignoring it breaks the pre-push without saying why."""
    paths = list(MUST_BE_TRACKED)
    new, old = ".claude/skills/gw-selector/SKILL.md", ".claude/skills/selector/SKILL.md"  # A8: both names in 0.x
    if not (root / new).is_file() and (root / old).is_file():
        paths[paths.index(new)] = old
    try:
        mark = config.load(root).get("reviewMark")
    except config.ConfigError:
        mark = None  # the config check reports it
    if mark and mark not in paths:
        paths.append(mark)
    return paths


def ignored_paths(root):
    """[(path, the .gitignore rule that ignores it)] for must_be_tracked(root); a tracked file is never ignored."""
    out = []
    for rel in must_be_tracked(root):
        r = subprocess.run(["git", "-C", str(root), "check-ignore", "-v", "--", rel], capture_output=True, text=True)
        # -v also prints (and exits 0 on) a matching `!` rule, which un-ignores the path: <source>:<line>:<pattern>
        rule = r.stdout.split("\t")[0].strip()
        if r.returncode == 0 and not rule.split(":", 2)[-1].startswith("!"):
            out.append((rel, rule))
    return out


def check_ignored(rep, root):
    found = ignored_paths(root)
    if found:
        rules = "; ".join(f"{rel} by {rule}" for rel, rule in found)
        rep.fail("ignored", f"git ignores workflow files, so a commit leaves them out: {rules}",
                 "add to .gitignore: " + " ".join(f"!{rel}" for rel, _ in found)
                 + " (and git check-ignore -v <path> until none is ignored)")
    else:
        rep.ok("ignored", "no workflow file is git-ignored")


def check_hooks_path(rep, root):
    current = git(root, "config", "--get", "core.hooksPath")
    if current and os.path.isabs(current) and Path(current).name == ".githooks":
        # config is shared by every worktree: an absolute path makes each one run the hooks of the checkout it names
        linked = (git(root, "worktree", "list", "--porcelain") or "").count("\n\n")
        why = ("every worktree runs the hooks of that checkout (another branch's hooks) instead of its own" if linked
               else "any worktree you add will run the hooks of that checkout instead of its own")
        rep.warn("hooks-path", f"core.hooksPath is the absolute path '{current}', so {why}",
                 "git config core.hooksPath .githooks")
    elif current == ".githooks":
        rep.ok("hooks-path", "core.hooksPath is .githooks")
    elif not current and os.environ.get("GITHUB_ACTIONS") == "true":
        rep.warn("hooks-path", "core.hooksPath is unset (GitHub Actions run: git hooks are not installed there, so "
                 "this is not a failure); locally it is a FAIL", "git config core.hooksPath .githooks")
    elif not current:
        rep.fail("hooks-path", "core.hooksPath is unset, so the workflow's git hooks do not run",
                 "git config core.hooksPath .githooks")
    else:
        rep.warn("hooks-path", f"core.hooksPath is '{current}' (another hook manager); the workflow's hooks run "
                 f"only if chained", chain_hint(current))


def had_own_commits(root, branch):
    """True when the branch ever moved past the commit it was created at (its oldest reflog entry is not its tip);
    False when it never did, and also when there is no reflog to tell: a branch just created from the protected branch
    looks merged once that branch moves on."""
    entries = (git(root, "reflog", "show", "--format=%H", branch) or "").split()
    return bool(entries) and entries[-1] != entries[0]


def check_worktrees(rep, root, cfg):
    """WARN with every worktree whose branch is already merged into the protected branch, local or origin/ (it only
    takes disk and clutters `git worktree list`), with the command that removes it. Branches that never had a commit of
    their own are skipped (just created). Squash and rebase merges are not detected (the check is `merge-base
    --is-ancestor`)."""
    protected = (cfg or {}).get("protectedBranch") or "main"
    targets = [r for r in (f"refs/heads/{protected}", f"refs/remotes/origin/{protected}")
               if git(root, "rev-parse", "--verify", "-q", r + "^{commit}")]
    listing = git(root, "worktree", "list", "--porcelain")
    if listing is None:
        rep.warn("worktree", "cannot check worktrees: `git worktree list` failed", f"git -C {shlex.quote(str(root))} worktree list")
        return
    if not targets:
        rep.warn("worktree", f"cannot check worktrees: neither {protected} nor origin/{protected} exists here",
                 f"git fetch origin {protected}")
        return
    top = os.path.realpath(str(root))
    merged = []
    for block in listing.split("\n\n")[1:]:  # the first one is the main checkout
        lines = block.splitlines()
        fields = dict(l.split(" ", 1) for l in lines if " " in l)
        path, branch = fields.get("worktree"), fields.get("branch", "")
        if not path or not branch.startswith("refs/heads/") or os.path.realpath(path) == top:
            continue
        name = branch[len("refs/heads/"):]
        if name == protected or not had_own_commits(root, branch):
            continue
        into = next((t for t in targets if subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", branch, t],
                                                          capture_output=True).returncode == 0), None)
        if into:
            merged.append((path, name, into.replace("refs/heads/", "").replace("refs/remotes/", ""),
                           any(l == "locked" or l.startswith("locked ") for l in lines)))
    for path, name, into, locked in merged:
        force = "-f -f " if locked else ""  # a locked worktree is removed only with the flag twice
        rep.warn("worktree", f"worktree {path} has branch '{name}', already merged into {into}" +
                 (" (it is locked)" if locked else ""),
                 f"git worktree remove {force}{shlex.quote(path)} && git branch -d {shlex.quote(name)}")
    if not merged:
        rep.ok("worktree", f"no worktree with a branch already merged into {protected}")


CD_ENTER = re.compile(r"""(?:^|[;&|(])\s*cd\s+("[^"]+"|'[^']+'|[^\s;&|)"']+)\s*&&""")


def linkable():
    """The dependency folders the pre-push worktree lacks (untracked): the schema default of `worktreeLinks`, which
    is the list apply.py seeds (one list, A13)."""
    return tuple(config.schema_default("worktreeLinks"))


def check_worktree_links(rep, root, cfg):
    """WARN when a `check` command does `cd <folder> && …` into a folder with node_modules or .venv that
    `worktreeLinks` does not link: the pre-push runs the check in a temporary worktree where that folder is missing."""
    if cfg is None:
        rep.warn("worktree links", "cannot check worktreeLinks: .claude/gw.json is not valid",
                 f"python3 {HERE / 'config.py'} --root {root} validate")
        return
    links = [Path(os.path.normpath(l)).as_posix() for l in cfg.get("worktreeLinks") or []]
    found = False
    for command in cfg.get("check") or []:
        for m in CD_ENTER.finditer(command):
            folder = Path(os.path.normpath(m.group(1).strip("\"'"))).as_posix()
            if os.path.isabs(folder) or folder.startswith("..") or folder == ".":
                continue
            for name in linkable():
                rel = f"{folder}/{name}"
                covered = any(rel == l or rel.startswith(l + "/") for l in links)
                if (root / rel).exists() and not covered:
                    found = True
                    rep.warn("worktree links", f"'{command}' enters {folder}, which has {name}, but worktreeLinks "
                             f"does not link {rel}: the pre-push worktree will not have it",
                             f'add "{rel}" to worktreeLinks in .claude/gw.json')
    if not found:
        rep.ok("worktree links", "every `cd <folder> &&` in check has its dependency folders in worktreeLinks")


def check_githooks(rep, root, version, cfg=None):
    for name in ("pre-push", "pre-commit", "commit-msg"):
        path = root / ".githooks" / name
        check = f"githook {name}"
        if not path.is_file():
            rep.fail(check, f".githooks/{name} is missing", "/gw-update")
            continue
        if not os.access(str(path), os.X_OK):
            rep.fail(check, f".githooks/{name} is not executable", f"chmod +x .githooks/{name}")
            continue
        found = header_version(path)
        if version and found != version and cfg and config.owned(cfg, f".githooks/{name}"):
            rep.ok(check, f".githooks/{name} present and executable; owned by the project (ownedFiles)")
        elif version and found != version:
            rep.warn(check, f".githooks/{name} is version {found or '(no header)'}, the config says {version}",
                     "/gw-update")
        else:
            rep.ok(check, f".githooks/{name} present and executable" + (f" (v{found})" if found else ""))


def check_legacy_paths(rep, cfg):
    """A key absent from gw.json that config.py filled with an old Spanish path (0.x compatibility, A8): warn."""
    legacy = (cfg or {}).get("_legacy") or {}
    for key in sorted(legacy):
        rep.warn("legacy-paths", f"{key} is absent from .claude/gw.json and falls back to the old path {legacy[key]} "
                 "(the English name is the default now)", "run /gw-update to move it to the English name")
    if not legacy:
        rep.ok("legacy-paths", "no key falls back to an old Spanish path")


def check_log(rep, root, cfg):
    if cfg is None:
        return
    path = root / cfg["log"]
    if not path.is_file():
        rep.fail("log", f"{cfg['log']} does not exist", "create it from the workflow's log template: /gw-update")
        return
    if not NEXT_STEP.search(path.read_text(encoding="utf-8", errors="replace")):
        rep.fail("log", f"{cfg['log']} has no next-step line, so the next session cannot pick up",
                 f"add a 'Next step' (or 'Siguiente paso') line to {cfg['log']}")
        return
    rep.ok("log", f"{cfg['log']} has a next step")


def syntax_only(command):
    """For a plain `bash -n ...` / `sh -n ...` command that checks fewer files than it seems to, return
    (interpreter, args, why), else None. `why` is "several" (more than one file: only the first is read), "glob"
    (an argument has `*`, `?` or `[`) or "subst" (`$(...)` or a backtick). A `for`, `;`, `&&`, `|`, a redirection or
    any other shell structure is not a plain command, so it is left alone."""
    subst = "$(" in command or "`" in command
    try:
        if subst:
            words = shlex.split(command)
            ops = any(w in (";", "&&", "||", "|", "&") for w in words)
        else:
            lex = shlex.shlex(command, posix=True, punctuation_chars=True)
            lex.whitespace_split = True
            words = list(lex)
            ops = any(re.fullmatch(r"[;&|<>()]+|\d+>.*", w) for w in words)
    except ValueError:
        return None
    if ops or len(words) < 3 or os.path.basename(words[0]) not in ("bash", "sh") or words[1] != "-n":
        return None
    interp = os.path.basename(words[0])
    args = [w for w in words[2:] if not w.startswith("-")]
    if subst:
        return interp, [command.split(None, 2)[2]], "subst"
    if any(c in w for w in args for c in "*?["):
        return interp, args, "glob"
    if len(args) > 1:
        return interp, args, "several"
    return None


def check_commands(rep, root, cfg):
    if cfg is None:
        return
    wrapper = (cfg.get("checkWrapper") or "").strip()
    if wrapper:
        word = first_word(wrapper)
        if resolves(word, root):
            rep.ok("checkWrapper", f"'{wrapper}' ({word} found)")
        else:
            rep.fail("checkWrapper", f"'{wrapper}': '{word}' is not a command on PATH nor a file in the repo",
                     f"fix checkWrapper in .claude/gw.json, then: python3 {HERE / 'doctor.py'}")
    for command in cfg.get("check") or []:
        found = syntax_only(command)
        if found:
            interp, args, why = found
            if why == "several":
                msg = (f"'{command}': {interp} -n reads only the first file ({args[0]}); the other {len(args) - 1} are "
                       f"passed as arguments and never checked")
                loop = " ".join(shlex.quote(a) for a in args)
            else:
                what = "a command substitution" if why == "subst" else "a glob"
                msg = (f"'{command}': {interp} -n reads only the first file, and {what} in the arguments may expand "
                       f"to several files, so the others are never checked")
                loop = " ".join(args)
            rep.warn("check syntax-only", msg,
                     f"use one `{interp} -n <file>` command per file in 'check' in .claude/gw.json, or one command: "
                     f'for f in {loop}; do {interp} -n "$f"; done')
    for key, bad in (("check", rep.fail), ("install", rep.warn), ("setup", rep.warn)):
        for command in cfg.get(key) or []:
            word = first_word(command)
            if resolves(word, root):
                rep.ok(f"{key} command", f"'{command}' ({word} found)")
            else:
                bad(f"{key} command", f"'{command}': '{word}' is not a command on PATH nor a file in the repo",
                    f"install {word} or fix '{key}' in .claude/gw.json, then: python3 {HERE / 'doctor.py'}")


def runs_check(text, cfg):
    """True when a workflow's text runs the project's check: it reads `check` through config.py, is the workflow's
    own check.yml, or spells out one of the `check` commands."""
    pre_commit = re.search(r"pre-commit\s+--(range|rango)\b", text)  # --rango: the name before A8
    if "config.py get check" in text or ("galivelop-workflow v" in text and pre_commit):
        return True
    code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    return any(c.strip() and re.search(r"(?<![\w./-])" + re.escape(c.strip()) + r"(?![\w./-])", code)
               for c in (cfg or {}).get("check") or [])


def check_ci(rep, root, cfg=None):
    wf = root / ".github" / "workflows"
    found = sorted(p for p in wf.glob("*.y*ml")) if wf.is_dir() else []
    if not found:
        rep.warn("ci", "no CI workflow under .github/workflows, so nothing checks pushes outside this machine",
                 "copy the workflow's CI template: mkdir -p .github/workflows && cp <workflow>/templates/github/"
                 "check.yml .github/workflows/")
        return
    names = ", ".join(p.name for p in found)
    if any(p.name == "comprobar.yml" for p in found):
        rep.warn("ci", "comprobar.yml is the old name of check.yml (A8)",
                 "run /gw-update: it renames the workflow's CI file to check.yml")
    running = [p.name for p in found if runs_check(p.read_text(encoding="utf-8", errors="replace"), cfg)]
    if running:
        rep.ok("ci", f"CI workflow(s): {names}; {', '.join(running)} run(s) the check")
    else:
        rep.warn("ci", f"CI workflow(s) {names}, but none seems to run the project's `check` commands",
                 "add the check to one of them, or copy the workflow's CI template (mkdir -p .github/workflows && cp "
                 "<workflow>/templates/github/check.yml .github/workflows/); to keep your own CI, add only its "
                 "step that runs the base branch's .githooks/pre-commit --range (docs/en/apply.md, Existing CI)")


def hook_files(command, root):
    """Files a hook command runs: words that use $CLAUDE_PROJECT_DIR, or a path given as the program itself."""
    expanded = command.replace("${CLAUDE_PROJECT_DIR}", str(root)).replace("$CLAUDE_PROJECT_DIR", str(root))
    try:
        words = shlex.split(expanded)
    except ValueError:
        return []
    files = [w for w in words if w.startswith(str(root) + "/")]
    if words and "/" in words[0] and words[0] not in files and Path(words[0]).name not in INTERPRETERS:
        files.append(words[0] if os.path.isabs(words[0]) else str(root / words[0]))
    return files


def is_flow_script(command, root):
    """True when the command runs a script of the workflow: a file named like one of FLOW_HOOK_SCRIPTS that carries
    the workflow's header (`# galivelop-workflow vX`). A project's own script with the same name is not one; a file
    that does not exist is not decided here (the settings check already fails on it)."""
    expanded = command.replace("${CLAUDE_PROJECT_DIR}", str(root)).replace("$CLAUDE_PROJECT_DIR", str(root))
    try:
        words = shlex.split(expanded)
    except ValueError:
        return False
    for w in words:
        if Path(w).name in FLOW_HOOK_SCRIPTS:
            path = Path(w) if os.path.isabs(w) else Path(root) / w
            if path.is_file() and header_version(path):
                return True
    return False


def stale_flow_hooks(hooks, root):
    """[(event, command)] of SessionStart/PreToolUse/Stop hooks that run a workflow script (by name and by its
    header) from another folder."""
    out = []
    for event in ("SessionStart", "PreToolUse", "Stop"):
        for entry in hooks.get(event) or []:
            for h in (entry.get("hooks") or []) if isinstance(entry, dict) else []:
                command = h.get("command", "") if isinstance(h, dict) else ""
                if (any(re.search(rf"(^|[/\s\"']){re.escape(n)}\b", command) for n in FLOW_HOOK_SCRIPTS)
                        and ".claude/gw/scripts/" not in command and is_flow_script(command, root)):
                    out.append((event, command))
    return out


def check_proposals(rep, root):
    """WARN with every pending *.gw-new (or the old *.gw-nuevo, A8, 0.x); returns them."""
    listed = git(root, "ls-files", "-co", "--exclude-standard") or ""
    found = sorted(f for f in listed.splitlines() if f.endswith((PROPOSAL, OLD_PROPOSAL)))
    if found:
        first = next((f for f in found if f.endswith(PROPOSAL)), found[0])
        suffix = PROPOSAL if first.endswith(PROPOSAL) else OLD_PROPOSAL
        base = first[:-len(suffix)]
        old = [f for f in found if f.endswith(OLD_PROPOSAL)]
        rep.warn("proposals", f"{len(found)} pending {PROPOSAL} proposal(s), not reviewed: {', '.join(found[:10])}"
                 + (" …" if len(found) > 10 else "")
                 + (f" ({len(old)} with the old suffix {OLD_PROPOSAL}, still recognized until 1.0)" if old else ""),
                 f"merge each by hand and delete it; see one: git diff --no-index {base} {base}{suffix}")
    else:
        rep.ok("proposals", f"no pending {PROPOSAL} proposal")
    return found


def check_settings(rep, root):
    path = root / ".claude" / "settings.json"
    if not path.is_file():
        rep.fail("settings", ".claude/settings.json is missing, so no Claude Code hook runs", "/gw-update")
        return
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        rep.fail("settings", f".claude/settings.json: invalid JSON at line {exc.lineno}: {exc.msg}",
                 "fix it and check: python3 -m json.tool .claude/settings.json")
        return
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    hooks = hooks if isinstance(hooks, dict) else {}
    problems = 0
    for i, entry in enumerate(hooks.get("SessionStart") or []):
        matcher = entry.get("matcher") if isinstance(entry, dict) else None
        if not matcher:
            problems += 1
            rep.fail("settings SessionStart", f"entry {i} has no matcher, so it runs on every start, resume, clear "
                     f"and compact", "give it one in .claude/settings.json, e.g. \"matcher\": \"startup|resume|clear\"")
            continue
        if "compact" in matcher.split("|"):
            others = [h.get("command", "") for h in entry.get("hooks") or []
                      if isinstance(h, dict) and not re.search(r"recover\.py[\"']?\s+--(state|estado)\b", h.get("command", ""))]
            if others:
                problems += 1
                rep.fail("settings SessionStart", f"entry {i} ({matcher}) runs '{others[0]}' on compact; after a "
                         f"compaction only recover.py --state should run (the rest re-runs setup mid-task)",
                         "move that command to a \"startup|resume|clear\" entry in .claude/settings.json")
    for event, entries in hooks.items():
        for entry in entries if isinstance(entries, list) else []:
            for h in (entry.get("hooks") or []) if isinstance(entry, dict) else []:
                if not isinstance(h, dict):
                    continue
                for f in hook_files(h.get("command", ""), root):
                    if not os.path.exists(f):
                        problems += 1
                        rel = os.path.relpath(f, str(root))
                        rep.fail(f"settings {event}", f"hook command points to {rel}, which does not exist",
                                 "restore it (/gw-update) or fix the command in .claude/settings.json")
    for event, command in stale_flow_hooks(hooks, root):
        problems += 1
        rep.warn(f"settings {event}", f"'{command}' runs a workflow script from outside .claude/gw/scripts/ "
                 f"(an older copy?), so it may run twice", "delete that entry from .claude/settings.json")
    guard = any(isinstance(e, dict) and all(t in (e.get("matcher") or "") for t in PR_TOOLS)
                and any(PR_GUARD in (h.get("command") or "") for h in e.get("hooks") or [] if isinstance(h, dict))
                for e in hooks.get("PreToolUse") or [])
    if not guard:
        problems += 1
        rep.fail("settings PreToolUse", f"no PreToolUse entry for {' and '.join(PR_TOOLS)} running {PR_GUARD}, so "
                 f"pull requests to the protected branch are not guarded",
                 "add it from the workflow's templates/claude/settings.json (/gw-update)")
    if not problems:
        rep.ok("settings", ".claude/settings.json hooks look right")


def check_subagents(rep, root):
    texts = []
    for name in ("AGENTS.md", "CLAUDE.md"):
        p = root / name
        if p.is_file():
            texts.append(p.read_text(encoding="utf-8", errors="replace"))
    if not texts:
        rep.fail("agents", "neither AGENTS.md nor CLAUDE.md exists, so agents get no workflow rules", "/gw-init")
    elif any("orchestrate-dealer" in t for t in texts):  # also matches gw-orchestrate-dealer: both names in 0.x
        rep.ok("agents", "AGENTS.md/CLAUDE.md authorise dealing work to subagents (gw-orchestrate-dealer)")
    else:
        rep.warn("agents", "neither AGENTS.md nor CLAUDE.md mentions gw-orchestrate-dealer, so the session may not deal "
                 "work to subagents", "add to AGENTS.md: 'Multi-step work is dealt to subagents (skill "
                 "gw-orchestrate-dealer); the main session plans, decides and reviews.'")


def check_glossary(rep, root):
    """WARN when the same `**Term**:` is defined twice in GLOSSARY.md (case and spacing do not matter)."""
    path = root / "GLOSSARY.md"
    if not path.is_file():
        return
    seen, dup = {}, []
    for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        m = re.match(r"^\s*(?:[-*]\s+)?\*\*(.+?)\*\*\s*:", line)
        if not m:
            continue
        key = " ".join(m.group(1).lower().split())
        if key in seen and m.group(1) not in dup:
            dup.append(m.group(1))
        seen.setdefault(key, n)
    if dup:
        where = ", ".join(f"{t} (line {seen[' '.join(t.lower().split())]})" for t in dup)
        rep.warn("glossary", f"GLOSSARY.md defines the same term twice: {where}",
                 "merge the entries into one in GLOSSARY.md (grep -n '\\*\\*<term>\\*\\*:' GLOSSARY.md)")
    else:
        rep.ok("glossary", "GLOSSARY.md has no repeated term")


def skill_metadata(path):
    meta, inside = {}, False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return meta
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    for line in (m.group(1).splitlines() if m else []):
        if re.match(r"^metadata:\s*$", line):
            inside = True
            continue
        if inside:
            sub = re.match(r"^\s+([A-Za-z_-]+):\s*(.*)$", line)
            if not sub:
                break
            meta[sub.group(1)] = sub.group(2).strip().strip("\"'")
    return meta


def check_skills(rep, root, version, proposals=(), cfg=None):
    base = root / ".claude" / "skills"
    if not version or not base.is_dir():
        return
    stale = []
    for skill in sorted(base.glob("*/SKILL.md")):
        meta = skill_metadata(skill)
        if cfg and config.owned(cfg, skill.relative_to(root).as_posix()):
            continue
        if SOURCES.search(meta.get("source", "")) and meta.get("version") != version:
            stale.append(f"{skill.parent.name} ({meta.get('version') or 'no version'})")
    cites = [s.parent.name for s in sorted(base.glob("*/SKILL.md"))
             if SKILL_LICENSE in s.read_text(encoding="utf-8", errors="replace")]
    if cites and not (base / SKILL_LICENSE).is_file():
        rep.warn("skills", f"{', '.join(cites)} cite {SKILL_LICENSE}, missing from .claude/skills/", "/gw-update")
    if stale:
        rep.warn("skills", f"copied workflow skills not at version {version}: {', '.join(stale)}", "/gw-update")
    elif any(p.startswith(".claude/skills/") for p in proposals):
        rep.warn("skills", "copied workflow skills at their version, with pending proposals (above)",
                 "review the .claude/skills/ proposals first")
    else:
        rep.ok("skills", f"copied workflow skills at version {version}")


def check_session(rep, root):
    folder = session_log.opened_outside(root)
    if session_log.cloud_start(folder):
        rep.ok("session", "cloud session: it starts in /home/user, not in the repo; its compaction window is "
               "checked under compaction")
    elif folder:
        rep.warn("session", f"the newest session transcript is in {folder}: that session was opened outside the "
                 f"repo and may not have loaded .claude/settings.json", f"restart Claude Code from the repo: cd {root} && claude")
    else:
        rep.ok("session", "no session opened outside the repo")


def check_compaction(rep, root):
    """A cloud session starts in /home/user, often with several repos, so it does not load .claude/settings.json and
    its compaction window: only the environment's own variables reach it."""
    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        return
    key = "CLAUDE_CODE_AUTO_COMPACT_WINDOW"
    try:
        value = json.loads((root / ".claude" / "settings.json").read_text())["env"][key]
    except (OSError, ValueError, KeyError, TypeError):
        return  # the project sets no window: nothing to carry over to the cloud environment
    if os.environ.get(key):
        rep.ok("compaction", f"cloud session with {key}={os.environ[key]} in its environment")
        return
    rep.warn("compaction", f"cloud session without {key} in its environment: .claude/settings.json may not load "
             f"(session started in /home/user or with several repos), so the context grows with no cap",
             f"add {key}={value} to the cloud environment's variables (environment menu > Edit); new sessions get it")


EFFORT_VAR = "CLAUDE_CODE_EFFORT_LEVEL"
SUBAGENT_MODEL_VAR = "CLAUDE_CODE_SUBAGENT_MODEL"
FORCE_VAR = "CLAUDE_CODE_SUBAGENT_MODEL_FORCE"
SUBAGENT_EFFORT_VAR = "CLAUDE_CODE_SUBAGENT_EFFORT"


def lever_sources(root):
    """[(where, env)]: the session's environment and the env blocks of the project and user settings files."""
    sources = [("the environment", dict(os.environ))]
    for where, path in ((".claude/settings.json", root / ".claude" / "settings.json"),
                        (".claude/settings.local.json", root / ".claude" / "settings.local.json"),
                        ("~/.claude/settings.json", Path.home() / ".claude" / "settings.json")):
        try:
            env = json.loads(path.read_text(encoding="utf-8")).get("env")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(env, dict):
            sources.append((where, {k: str(v) for k, v in env.items()}))
    return sources


def check_levers(rep, root, cfg):
    """B11: model and effort are picked per agent (gw-selector); a global variable that overrides them is warned."""
    try:
        if cfg is not None and not config.models(cfg)["checkLevers"]:
            return
    except (config.ConfigError, KeyError, OSError, ValueError):
        pass  # the check stays on: it only warns
    found = 0
    for where, env in lever_sources(root):
        effort = env.get(EFFORT_VAR, "").strip()
        if effort and effort.lower() not in ("auto", "unset"):
            found += 1
            rep.warn("levers", f"{EFFORT_VAR}={effort} in {where} beats every other effort: the effort gw-selector "
                     f"passes to each agent and the session's /effort", f"remove {EFFORT_VAR} from {where} "
                     f"(or set models.checkLevers false in .claude/gw.json if it is on purpose)")
        if env.get(FORCE_VAR, "").strip().lower() in ("1", "true") and env.get(SUBAGENT_MODEL_VAR, "").strip():
            found += 1
            rep.warn("levers", f"{SUBAGENT_MODEL_VAR}={env[SUBAGENT_MODEL_VAR].strip()} with {FORCE_VAR} in {where} "
                     f"forces one model on every subagent, over the `model` each call passes (only for a "
                     f"restricted-tokens mode)", f"remove {FORCE_VAR} from {where}")
        if env.get(SUBAGENT_EFFORT_VAR, "").strip():
            found += 1
            rep.warn("levers", f"{SUBAGENT_EFFORT_VAR} in {where} is not a documented Claude Code variable, so it "
                     f"may do nothing", f"remove it from {where}; pass `effort` in each Agent call (gw-selector)")
    if not found:
        rep.ok("levers", "no global variable overrides the model or effort picked per agent")


def invisible_chars(text):
    """[(line, column, 'U+XXXX')] of invisible characters in text; a BOM as the very first character is fine."""
    found = []
    for n, line in enumerate(text.split("\n"), 1):
        for m in INVISIBLE.finditer(line):
            if n == 1 and m.start() == 0 and m.group() == "\ufeff":
                continue
            found.append((n, m.start() + 1, f"U+{ord(m.group()):04X}"))
    return found


def strip_invisible_command(name):
    return ("python3 -c 'import re,sys;p=sys.argv[1];t=open(p,encoding=\"utf-8\").read();"
            f"open(p,\"w\",encoding=\"utf-8\").write(re.sub(\"{INVISIBLE_PATTERN}\",\"\",t))' {name}")


def check_instructions(rep, root, cfg=None):
    """Invisible characters in the files agents obey (a hidden instruction is an injection) and the size of
    AGENTS.md/CLAUDE.md (P7 of proposal 2026-10-25-repos-x.md)."""
    warn_lines, fail_lines = config.instruction_lines(cfg or {})  # every session loads AGENTS.md/CLAUDE.md whole
    files = [root / n for n in ("AGENTS.md", "CLAUDE.md") if (root / n).is_file()]
    files += sorted((root / ".claude" / "skills").glob("*/SKILL.md"))
    bad = False
    for path in files:
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        found = invisible_chars(text)
        if found:
            bad = True
            where = ", ".join(f"line {n} col {c} {cp}" for n, c, cp in found[:5])
            rep.fail("invisible", f"{rel} has invisible or bidirectional characters ({where}"
                     f"{', ...' if len(found) > 5 else ''}); an agent obeys what a person cannot see",
                     f"remove them: {strip_invisible_command(rel)}")
        lines = len(text.splitlines())
        if path.name in ("AGENTS.md", "CLAUDE.md") and lines > warn_lines:
            bad = True
            report = rep.fail if lines > fail_lines else rep.warn
            report("size", f"{rel} has {lines} lines (warn above {warn_lines}, fail above {fail_lines}); every "
                   "session loads it whole", f"move detail out of {rel} into docs/ and link it from there, or raise "
                   "instructionLines in .claude/gw.json")
    if not bad:
        rep.ok("instructions", "AGENTS.md/CLAUDE.md and skills: no invisible characters, size within limits")


def skill_scripts_without_test(skills_dir):
    """Paths of the skills_dir/*/scripts/*.py that have no test_<name>.py next to them (test_*.py and __init__.py need
    none; subfolders are not looked at). The repo's own test_skills.py applies it to skills/ too."""
    return [path for path in sorted(skills_dir.glob("*/scripts/*.py")) if skills_dir.is_dir()
            and path.name != "__init__.py" and not path.name.startswith("test_")
            and not (path.parent / f"test_{path.name}").is_file()]


def check_skill_tests(rep, root):
    """WARN with every .claude/skills/*/scripts/*.py that has no test_<name>.py next to it: a skill born in the project
    is code too (P2 of proposal 2026-10-25-world-maker-fantasy-2.md)."""
    missing = skill_scripts_without_test(root / ".claude" / "skills")
    for path in missing:
        rel = path.relative_to(root).as_posix()
        folder, name = rel.rsplit("/", 1)
        rep.warn("skill tests", f"{rel} has no test next to it", f"write {folder}/test_{name} "
                 f"(python3 -m unittest discover -s {folder} -p 'test_*.py' runs it)")
    if not missing:
        rep.ok("skill tests", "every skill script has its test_<name>.py")


def test_dirs(root, ignore):
    """Repo-relative folders (posix, "." for the root) that directly hold a test_*.py, skipping the folders the
    `doctorTestDirsIgnore` patterns match (fnmatch on the path or on its tail, so "node_modules" also skips
    "a/node_modules") and any folder with a pyvenv.cfg (a virtualenv)."""
    found = []
    for base, dirs, files in os.walk(root):
        rel = Path(base).relative_to(root).as_posix()
        if any(f.startswith("test_") and f.endswith(".py") for f in files):
            found.append(rel)
        keep = []
        for d in sorted(dirs):
            sub = d if rel == "." else f"{rel}/{d}"
            if any(fnmatch.fnmatchcase(sub, pat) or fnmatch.fnmatchcase(sub, "*/" + pat) for pat in ignore) \
                    or (Path(base) / d / "pyvenv.cfg").is_file():
                continue
            keep.append(d)
        dirs[:] = keep
    return found


def check_run_text(root, cfg):
    """What the `check` commands run, as text: the commands, the testMap test paths, and the content of each script or
    Makefile a command names (one level: `bash tests/check.sh`, `make check`); only files inside the repo are read."""
    parts = list(cfg.get("check") or [])
    for rule in (cfg.get("testMap") or {}).get("rules") or []:
        parts.extend(t for t in rule.get("tests") or [] if isinstance(t, str))
    top = root.resolve()
    for command in list(parts):
        try:
            words = shlex.split(command)
        except ValueError:
            continue
        files = [w for w in words if "/" in w or w.endswith((".sh", ".py"))]
        if "make" in words[:2]:
            files.append("Makefile")
        for name in files:
            try:
                path = (top / name).resolve()
                path.relative_to(top)  # a path outside the repo (/etc/passwd, ../x) is never read
                if path.is_file() and path.stat().st_size < config.doctor_scan_bytes(cfg):
                    parts.append(path.read_text(encoding="utf-8", errors="replace"))
            except (ValueError, OSError):
                continue
    return "\n".join(parts)


def _norm(path):
    path = path.strip("\"'")
    path = path[2:] if path.startswith("./") else path
    return path.rstrip("/") or "."


def run_targets(root, text):
    """(everything, patterns): what the commands in `text` run. Only these count (never a word in a comment, an `echo`
    or `pip install pytest`): the argument of `-s`/`--start-directory` of a `python -m unittest discover` (`$var` is
    resolved from a `for var in <paths>` line; no `-s` means "."), the paths given to `python -m unittest` or to
    pytest (a folder is that folder, a test_*.py is its own folder), any test_*.py named in a command, and a pytest
    command with no path (everything). A folder is run if it equals a pattern or a glob matches it."""
    patterns, everything, loops = [], False, {}
    for line in text.splitlines():
        line = re.sub(r"\s#.*$", "", line.strip())
        if not line or line.startswith("#"):
            continue
        m = re.match(r"for\s+(\w+)\s+in\s+([^;]+);", line)
        if m:
            loops[m.group(1)] = [_norm(w) for w in m.group(2).split()]
        for cmd in re.split(r"\s*(?:;|&&|\|\||\||&)\s*", line):
            words = cmd.split()
            while words and (words[0] in ("do", "then", "else", "if", "while", "!", "time")
                             or re.match(r"^[A-Za-z_]\w*=", words[0])):
                words = words[1:]
            if not words:
                continue
            py = re.match(r"python[\d.]*$", Path(words[0]).name) is not None
            tool = None
            if py and "-m" in words[:6] and words.index("-m") + 1 < len(words):
                tool = words[words.index("-m") + 1]
                rest = words[words.index("-m") + 2:]
            elif Path(words[0]).name in ("pytest", "py.test"):
                tool, rest = "pytest", words[1:]
            for word in words:
                base = word.strip("\"'").rsplit("/", 1)
                if (base[-1].startswith("test_") and base[-1].endswith(".py")
                        and not re.search(r"[*?]", base[-1])):
                    patterns.append(_norm(base[0]) if len(base) == 2 else ".")
            if tool not in ("unittest", "pytest"):
                continue
            paths, start, it = [], None, iter(rest)
            for w in it:
                if tool == "unittest" and w in ("-s", "--start-directory"):
                    start = next(it, None)
                elif w.startswith("-"):
                    continue
                else:
                    w = w.split("::")[0]
                    if w.strip("\"'") == "discover" or not ("/" in w or w.endswith(".py") or (root / _norm(w)).is_dir()):
                        continue
                    paths.append(w)
            if start is not None:
                paths = [start]
            elif tool == "unittest" and "discover" in rest and not paths:
                paths = ["."]
            if tool == "pytest" and not paths:
                everything = True
            for w in paths:
                w = _norm(w)
                if w.startswith("$") and w.lstrip("${").rstrip("}") in loops:
                    patterns.extend(loops[w.lstrip("${").rstrip("}")])
                elif w.endswith(".py"):
                    patterns.append(w.rsplit("/", 1)[0] if "/" in w else ".")
                else:
                    patterns.append(w)
    return everything, patterns


def folder_is_run(folder, targets):
    """Whether `folder` is run by the `run_targets` result: equal to a pattern or matched by it as a glob (a parent of
    a run folder, `tests` for `-s tests/unit`, is not run)."""
    everything, patterns = targets
    return everything or any(fnmatch.fnmatchcase(folder, pat) for pat in patterns)


def check_test_dirs(rep, root, cfg):
    """WARN with every folder holding test_*.py that no `check` command runs (E43): a test nobody runs is no test. See
    run_targets for what counts as running a folder; nothing is said without `check` commands."""
    if cfg is None or not cfg.get("check"):
        return
    import config
    targets = run_targets(root, check_run_text(root, cfg))
    missing = [f for f in test_dirs(root, config.doctor_test_dirs_ignore(cfg)) if not folder_is_run(f, targets)]
    for folder in missing:
        rep.warn("test dirs", f"{folder}/ holds test_*.py that no command of 'check' runs",
                 f"add to 'check' in .claude/gw.json: python3 -m unittest discover -s {folder} -p 'test_*.py' "
                 f"(or list {folder} in doctorTestDirsIgnore)")
    if not missing:
        rep.ok("test dirs", "every folder with test_*.py is run by 'check'")


def media_note_folder(root):
    """The `Folder:` the gw-media-content note declares, or None when the note or the line is missing."""
    try:
        text = (root / MEDIA_NOTE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"^[\s>*-]*Folder\s*:\s*`?([^`\n]+?)`?\s*$", text, re.M)
    return m.group(1) if m else None


def old_media_folder(root):
    """docs/difusion (A8, 0.x) when the note declares no folder and it exists: what /gw-update moves to docs/media."""
    old = root / OLD_MEDIA_FOLDER
    if media_note_folder(root) is None and old.is_dir() and not old.is_symlink():
        return old
    return None


def media_folder(root):
    """The `Folder:` line of the gw-media-content note, or its default (docs/media; the old docs/difusion while it is
    the only one there, 0.x); None when it points outside the project."""
    folder = media_note_folder(root)
    if folder is None:
        folder = OLD_MEDIA_FOLDER if old_media_folder(root) and not (root / MEDIA_FOLDER).exists() else MEDIA_FOLDER
    path = Path(folder)
    return None if path.is_absolute() or ".." in path.parts else root / path


def uses_media_content(root):
    """The project uses gw-media-content when its note exists or the folder the note names (default docs/media) does.
    The skill itself is in every project that applied the workflow, so its presence says nothing."""
    folder = media_folder(root)
    return (root / MEDIA_NOTE).is_file() or (folder is not None and folder.is_dir())


def playwright_found():
    """True when `playwright` resolves as render.mjs does: from the current folder or from GW_PLAYWRIGHT_DIR, up the
    node_modules folders (and NODE_PATH, which Node also searches)."""
    bases = [Path.cwd()]
    if os.environ.get("GW_PLAYWRIGHT_DIR"):
        bases.append(Path(os.environ["GW_PLAYWRIGHT_DIR"]).resolve())
    for base in bases:
        for folder in [base, *base.parents]:
            if folder.name != "node_modules" and (folder / "node_modules" / "playwright" / "package.json").is_file():
                return True
        if (base / "playwright" / "package.json").is_file():
            return True
    return any((Path(d) / "playwright" / "package.json").is_file()
               for d in os.environ.get("NODE_PATH", "").split(os.pathsep) if d)


def imagemagick_webp():
    """The command (`magick`, else `convert`) whose `-list format` has WEBP, as render.mjs checks it; else None."""
    for command in ("magick", "convert"):
        if not shutil.which(command):
            continue
        try:
            r = subprocess.run([command, "-list", "format"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and re.search(r"\bWEBP\b", r.stdout):
            return command
    return None


def check_media_folder(rep, root):
    """A8 (0.x): warns about docs/difusion, the old default folder, while the note does not name another one."""
    if old_media_folder(root) is None:
        return
    if (root / MEDIA_FOLDER).exists():
        rep.warn("media folder", f"{OLD_MEDIA_FOLDER} (the old default folder of gw-media-content) and {MEDIA_FOLDER} "
                 "both exist, and the note names no folder",
                 f"merge {OLD_MEDIA_FOLDER} into {MEDIA_FOLDER} by hand and remove it (git mv / git rm), or name the "
                 f"one you keep in {MEDIA_NOTE} (`Folder: {OLD_MEDIA_FOLDER}`)")
    else:
        rep.warn("media folder", f"{OLD_MEDIA_FOLDER} is the old default folder of gw-media-content; the default is "
                 f"now {MEDIA_FOLDER}",
                 "python3 .claude/gw/scripts/apply.py . --update moves it, or write "
                 f"`Folder: {OLD_MEDIA_FOLDER}` in {MEDIA_NOTE} to keep it")


def check_media_tools(rep, root):
    """Only for a project that uses gw-media-content: node, Playwright and ImageMagick with WebP, which
    skills/gw-media-content/scripts/render.mjs needs (the machine running doctor is the one that renders)."""
    if not uses_media_content(root):
        return
    found = []
    if shutil.which("node"):
        found.append("node")
    else:
        rep.warn("media tools", "gw-media-content renders images with node, which is not on PATH",
                 "install Node.js 18+ (https://nodejs.org, or: apt install nodejs / brew install node)")
    if playwright_found():
        found.append("Playwright")
    else:
        rep.warn("media tools", "gw-media-content renders images with Playwright, which is not found from the current "
                 "folder nor from GW_PLAYWRIGHT_DIR",
                 "in the project: npm i -D playwright && npx playwright install chromium (then run from its folder, "
                 "or set GW_PLAYWRIGHT_DIR)")
    command = imagemagick_webp()
    if command:
        found.append(f"ImageMagick with WebP ({command})")
    else:
        rep.warn("media tools", "gw-media-content converts images with ImageMagick with WebP support, not found "
                 "(neither `magick` nor `convert` lists WEBP)",
                 "apt install imagemagick webp (Debian/Ubuntu) or brew install imagemagick webp (macOS)")
    if len(found) == 3:
        rep.ok("media tools", f"gw-media-content: {', '.join(found)} found")


GITHUB_REMOTE = re.compile(r"^(?:https?://(?:[^/@]+@)?|ssh://(?:[^/@]+@)?|[^/@:]+@)github\.com[:/]", re.I)


def github_remote(root):
    """The `origin` URL when it points at github.com (https, ssh:// or git@github.com: form); else None."""
    url = git(root, "remote", "get-url", "origin")
    return url if url and GITHUB_REMOTE.match(url) else None


def check_ci_access(rep, root):
    """AGENTS.md asks to look at the CI of the last push when a block closes: with `origin` on GitHub, that needs `gh`
    (logged in) or a token in the environment (P5 of record retro-2026-10-25-antes-de-main-0-4-0.md). Never
    prints a token. No remote, or a remote elsewhere: nothing to check."""
    if github_remote(root) is None:
        return
    if os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"):
        rep.ok("ci access", "GITHUB_TOKEN/GH_TOKEN is set, so the CI state of origin can be read")
        return
    why = ("origin is on GitHub, but the agent cannot read the CI state of a push (AGENTS.md asks to look at it when "
           "each block closes)")
    if not shutil.which("gh"):
        rep.warn("ci access", f"{why}: neither `gh` is on PATH nor GITHUB_TOKEN/GH_TOKEN is set",
                 "install GitHub CLI and run `gh auth login`, or export GITHUB_TOKEN")
        return
    try:
        # Only github.com: another configured host (an expired GHE login) must not fail it.
        logged_in = subprocess.run(["gh", "auth", "status", "--hostname", "github.com"], capture_output=True,
                                   text=True, timeout=10, cwd=str(root)).returncode == 0
    except (OSError, subprocess.SubprocessError):
        logged_in = False
    if logged_in:
        rep.ok("ci access", "`gh` is logged in, so the CI state of origin can be read")
    else:
        rep.warn("ci access", f"{why}: `gh auth status` fails and no GITHUB_TOKEN/GH_TOKEN is set",
                 "run `gh auth login` (or export GITHUB_TOKEN)")


def run(root):
    rep = Report()
    cfg = check_config(rep, root)
    version = cfg["version"] if cfg else None
    check_hooks_path(rep, root)
    check_ignored(rep, root)
    check_githooks(rep, root, version, cfg)
    check_legacy_paths(rep, cfg)
    check_worktrees(rep, root, cfg)
    check_worktree_links(rep, root, cfg)
    check_log(rep, root, cfg)
    check_commands(rep, root, cfg)
    check_ci(rep, root, cfg)
    check_ci_access(rep, root)
    check_settings(rep, root)
    check_subagents(rep, root)
    check_glossary(rep, root)
    check_instructions(rep, root, cfg)
    check_skill_tests(rep, root)
    check_test_dirs(rep, root, cfg)
    check_media_folder(rep, root)
    check_media_tools(rep, root)
    proposals = check_proposals(rep, root)
    check_skills(rep, root, version, proposals, cfg)
    check_session(rep, root)
    check_compaction(rep, root)
    check_levers(rep, root, cfg)
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", help="project path")
    args = parser.parse_args(argv)
    try:
        root = config.find_root(args.root)
    except config.ConfigError as exc:
        print(f"doctor: {exc}", file=sys.stderr)
        return 2
    rep = run(root)
    if args.json:
        print(json.dumps(rep.items, indent=2, ensure_ascii=False))
    else:
        for line in rep.lines():
            print(line)
    return 1 if rep.failed() else 0


if __name__ == "__main__":
    sys.exit(main())
