#!/usr/bin/env python3
# galivelop-workflow v0.2.0
"""Check that a project has the workflow set up (used by /gw-doctor and CI). No AI, no network.

  python3 doctor.py            # one line per check: OK / WARN / FAIL, each problem with the command that fixes it
  python3 doctor.py --json     # the same as a JSON list of {status, check, message, fix}
  python3 doctor.py --root R   # check the project at R (default: config.find_root)

Exit 1 if any check FAILs (WARNs do not fail). Checks: the config; core.hooksPath and other hook managers; the git
hooks (present, executable, version); the log and its next step; the `check` and `install` commands exist; a CI
workflow; .claude/settings.json (WMF P4: SessionStart matchers, `compact` only runs recuperar.py --estado, hook
commands point to existing files, the PR guard on PreToolUse); AGENTS.md/CLAUDE.md authorise dealing work to
subagents (VeriNews P1); copied skills at the config's version; a session opened outside the repo (VeriNews P3);
in a cloud session (CLAUDE_CODE_REMOTE=true), the compaction window the project's settings.json sets is in the
environment. That last check and the session one read the machine running doctor, not only the project, so their
lines can differ between a person's machine, CI and a cloud session.
Python 3.8+ standard library only.
"""
import argparse
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
import registro_sesion  # noqa: E402

HEADER = re.compile(r"^# galivelop-workflow v(\S+)\s*$", re.M)
NEXT_STEP = re.compile(r"siguiente paso|next step", re.I)
PR_TOOLS = ("create_pull_request", "merge_pull_request")
PR_GUARD = "revision-antes-de-main.sh"
INTERPRETERS = {"bash", "sh", "zsh", "python", "python3", "node", "env", "exec"}
SOURCES = re.compile(r"galivelop|workflow|mattpocock", re.I)
PROPOSAL = ".gw-nuevo"  # aplicar.py's proposals for files with local edits
FLOW_HOOK_SCRIPTS = ("session-start.sh", "recuperar.py", "revision-antes-de-main.sh")  # the settings template's
SKILL_LICENSE = "LICENSE-mattpocock-skills"  # aplicar.py copies it next to the skills that cite it


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
    return (f"add as the last line of {hooks_dir}/pre-push and {hooks_dir}/pre-commit (with <hook> = the file's "
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
    return cfg

# What a commit must carry for the workflow to work; a `.gitignore` with `.claude/*` would leave it out.
MUST_BE_TRACKED = (".claude/gw.json", ".claude/gw/scripts/config.py", ".claude/settings.json",
                   ".claude/skills/selector/SKILL.md", ".githooks/pre-push")


def ignored_paths(root):
    """[(path, the .gitignore rule that ignores it)] for MUST_BE_TRACKED; a tracked file is never ignored."""
    out = []
    for rel in MUST_BE_TRACKED:
        r = subprocess.run(["git", "-C", str(root), "check-ignore", "-v", "--", rel], capture_output=True, text=True)
        if r.returncode == 0:
            rule = r.stdout.split("\t")[0].strip()
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
    if current in (".githooks", str(root / ".githooks")):
        rep.ok("hooks-path", "core.hooksPath is .githooks")
    elif not current:
        rep.fail("hooks-path", "core.hooksPath is unset, so the workflow's git hooks do not run",
                 "git config core.hooksPath .githooks")
    else:
        rep.warn("hooks-path", f"core.hooksPath is '{current}' (another hook manager); the workflow's hooks run "
                 f"only if chained", chain_hint(current))


def check_githooks(rep, root, version):
    for name in ("pre-push", "pre-commit"):
        path = root / ".githooks" / name
        check = f"githook {name}"
        if not path.is_file():
            rep.fail(check, f".githooks/{name} is missing", "/gw-update")
            continue
        if not os.access(str(path), os.X_OK):
            rep.fail(check, f".githooks/{name} is not executable", f"chmod +x .githooks/{name}")
            continue
        found = header_version(path)
        if version and found != version:
            rep.warn(check, f".githooks/{name} is version {found or '(no header)'}, the config says {version}",
                     "/gw-update")
        else:
            rep.ok(check, f".githooks/{name} present and executable" + (f" (v{found})" if found else ""))


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


def check_commands(rep, root, cfg):
    if cfg is None:
        return
    for key, bad in (("check", rep.fail), ("install", rep.warn)):
        for command in cfg.get(key) or []:
            word = first_word(command)
            if resolves(word, root):
                rep.ok(f"{key} command", f"'{command}' ({word} found)")
            else:
                bad(f"{key} command", f"'{command}': '{word}' is not a command on PATH nor a file in the repo",
                    f"install {word} or fix '{key}' in .claude/gw.json, then: python3 {HERE / 'doctor.py'}")


def check_ci(rep, root):
    wf = root / ".github" / "workflows"
    found = sorted(p.name for p in wf.glob("*.y*ml")) if wf.is_dir() else []
    if found:
        rep.ok("ci", f"CI workflow(s): {', '.join(found)}")
    else:
        rep.warn("ci", "no CI workflow under .github/workflows, so nothing checks pushes outside this machine",
                 "copy the workflow's CI template: mkdir -p .github/workflows && cp <workflow>/templates/github/"
                 "comprobar.yml .github/workflows/")


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


def stale_flow_hooks(hooks):
    """[(event, command)] of SessionStart/PreToolUse hooks that run a workflow script from another folder."""
    out = []
    for event in ("SessionStart", "PreToolUse"):
        for entry in hooks.get(event) or []:
            for h in (entry.get("hooks") or []) if isinstance(entry, dict) else []:
                command = h.get("command", "") if isinstance(h, dict) else ""
                if (any(re.search(rf"(^|[/\s\"']){re.escape(n)}\b", command) for n in FLOW_HOOK_SCRIPTS)
                        and ".claude/gw/scripts/" not in command):
                    out.append((event, command))
    return out


def check_proposals(rep, root):
    """WARN with every pending *.gw-nuevo; returns them."""
    listed = git(root, "ls-files", "-co", "--exclude-standard") or ""
    found = sorted(f for f in listed.splitlines() if f.endswith(PROPOSAL))
    if found:
        first = found[0][:-len(PROPOSAL)]
        rep.warn("proposals", f"{len(found)} pending {PROPOSAL} proposal(s), not reviewed: {', '.join(found[:10])}"
                 + (" …" if len(found) > 10 else ""),
                 f"merge each by hand and delete it; see one: git diff --no-index {first} {first}{PROPOSAL}")
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
                      if isinstance(h, dict) and not re.search(r"recuperar\.py[\"']?\s+--estado\b", h.get("command", ""))]
            if others:
                problems += 1
                rep.fail("settings SessionStart", f"entry {i} ({matcher}) runs '{others[0]}' on compact; after a "
                         f"compaction only recuperar.py --estado should run (the rest re-runs setup mid-task)",
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
    for event, command in stale_flow_hooks(hooks):
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
    elif any("orchestrate-dealer" in t for t in texts):
        rep.ok("agents", "AGENTS.md/CLAUDE.md authorise dealing work to subagents (orchestrate-dealer)")
    else:
        rep.warn("agents", "neither AGENTS.md nor CLAUDE.md mentions orchestrate-dealer, so the session may not deal "
                 "work to subagents", "add to AGENTS.md: 'Multi-step work is dealt to subagents (skill "
                 "orchestrate-dealer); the main session plans, decides and reviews.'")


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


def check_skills(rep, root, version, proposals=()):
    base = root / ".claude" / "skills"
    if not version or not base.is_dir():
        return
    stale = []
    for skill in sorted(base.glob("*/SKILL.md")):
        meta = skill_metadata(skill)
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
    folder = registro_sesion.opened_outside(root)
    if folder:
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


def run(root):
    rep = Report()
    cfg = check_config(rep, root)
    version = cfg["version"] if cfg else None
    check_hooks_path(rep, root)
    check_ignored(rep, root)
    check_githooks(rep, root, version)
    check_log(rep, root, cfg)
    check_commands(rep, root, cfg)
    check_ci(rep, root)
    check_settings(rep, root)
    check_subagents(rep, root)
    proposals = check_proposals(rep, root)
    check_skills(rep, root, version, proposals)
    check_session(rep, root)
    check_compaction(rep, root)
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
