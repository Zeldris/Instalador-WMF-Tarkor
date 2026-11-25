#!/usr/bin/env python3
# galivelop-workflow v0.9.0
"""Bring the protected branch into the working branch without losing the metrics ledger (E65).

  python3 merge-main.py [--root PATH] [--refs ID[,ID]]

The hooks write the metrics ledger (`metrics.ledger` in .claude/gw.json) all the time, so the tree is nearly always
dirty with it, and a plain `git merge` then refuses or, after a `stash`, can lose its lines. Steps:

  1. `git fetch origin <protectedBranch>` (a failure: exit 1 with git's reason).
  2. Uncommitted changes (tracked or untracked): none -> go on; only the ledger -> commit it first
     (`chore(<id>): ...`, trailers `Refs: <id>` and the next-step trailer of the project's `languages.docs.primary`, so the
     commit-msg hook accepts it); anything else -> exit 1 naming those paths and the command that fixes it
     (commit them, `git stash` or `git checkout -- <path>`). Nothing is committed or merged then.
     `<id>` is `--refs`, else the newest `Refs:` of the branch's own commits (`git log --first-parent --no-merges`);
     with neither, exit 1. On a spike branch (`spikeBranch`) the commit has no scope and no `Refs:`.
     With `metrics.commitLedger` false the ledger counts as any other dirty file, and nothing is committed when
     `origin/<protectedBranch>` brings nothing new.
  3. `git merge --no-edit origin/<protectedBranch>` (never a rebase); its exit status is this script's. After a
     conflict the ledger commit stays and git's own instructions apply.

Fails closed: a missing or invalid .claude/gw.json, not a git repository or no ledger setting -> exit 2 with the
command that fixes it. Project root: --root, else config.find_root (never the current directory alone).
Python 3.8+ standard library only.
"""
import argparse
import os
import posixpath
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, str(HERE))
import config  # noqa: E402

PROG = "merge-main"
NEXT = {"es": "Siguiente", "en": "Next"}  # the trailer commit-message.py asks for (NEXT_TRAILERS)
TEXT = {"es": ("commitea el ledger de métricas antes de fusionar {branch}", "Fusionar origin/{branch}"),
        "en": ("commit the metrics ledger before merging {branch}", "Merge origin/{branch}")}


def say(msg):
    print(f"{PROG}: {msg}", file=sys.stderr)


def git(root, *args, capture=True):
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    return subprocess.run(["git", "-C", str(root), *args], capture_output=capture, text=True, env=env)


def dirty_paths(root):
    """Repo-relative paths with uncommitted changes (staged, unstaged or untracked), or None when git fails."""
    res = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if res.returncode != 0:
        return None
    paths = []
    parts = res.stdout.split("\0")
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        paths.append(entry[3:])
        if entry[0] in "RC":  # a rename lists the old path next
            i += 1
    return paths


def head_refs(root):
    """The ids of the newest `Refs:` trailer on the branch's own first-parent line (merge commits, which carry none,
    and the commits a merge brought in are skipped)."""
    res = git(root, "log", "--first-parent", "--no-merges", "--format=%(trailers:key=Refs,valueonly)%x00")
    if res.returncode != 0:
        return []
    for chunk in res.stdout.split("\0"):
        ids = [x.strip() for line in chunk.splitlines() for x in line.split(",") if x.strip()]
        if ids:
            return ids
    return []


def main(argv=None):
    ap = argparse.ArgumentParser(prog=PROG, description="Merge origin/<protectedBranch>, committing the ledger first.")
    ap.add_argument("--root", help="project root (default: found from this script or the repo)")
    ap.add_argument("--refs", help="task id(s), comma separated, for the ledger commit (default: HEAD's Refs:)")
    args = ap.parse_args(argv)
    try:
        cfg = config.load(config.find_root(args.root))
        root = cfg["_root"]
        branch = cfg.get("protectedBranch")
        metrics = config.metrics(cfg)
        ledger = metrics.get("ledger")
        commit_ledger = bool(metrics.get("commitLedger", True))
        spike_prefix = config.spike_prefix(cfg)
    except config.ConfigError as exc:
        say(f"cannot read the config: {exc}; fix it: python3 {HERE / 'config.py'} validate")
        return 2
    if not branch or not ledger:
        say("protectedBranch or metrics.ledger is not set in .claude/gw.json; set them (docs/en/config.md)")
        return 2
    ledger = posixpath.normpath(ledger)
    lang = config.languages(cfg)["docs"]["primary"]
    lang = lang if lang in NEXT else "en"

    res = git(root, "fetch", "origin", branch)
    if res.returncode != 0:
        say(f"git fetch origin {branch} failed: {(res.stderr or res.stdout).strip()}; check the remote and the "
            f"network, then run it again: python3 {Path(__file__).resolve()}")
        return 1

    paths = dirty_paths(root)
    if paths is None:
        say(f"git status failed in {root}; is it a git repository? run: git -C {root} status")
        return 2
    others = [p for p in paths if p != ledger or not commit_ledger]
    if others:
        say(f"uncommitted changes besides the ledger: {', '.join(others)}; commit them, or put them away with "
            f"`git stash` (or `git checkout -- <path>`), then run it again: python3 {Path(__file__).resolve()}")
        return 1
    new = git(root, "rev-list", "--count", f"HEAD..origin/{branch}")
    brings = new.returncode != 0 or new.stdout.strip() != "0"  # when unsure, commit and let the merge say
    if paths and brings:  # only the ledger, and a merge is coming
        name = git(root, "symbolic-ref", "--short", "-q", "HEAD").stdout.strip()
        spike = bool(name) and config.is_spike_branch(name, spike_prefix)
        ids = [] if spike else ([x.strip() for x in (args.refs or "").split(",") if x.strip()] or head_refs(root))
        if not ids and not spike:
            say(f"the ledger ({ledger}) needs a commit but there is no task id for its Refs: trailer; pass one: "
                f"python3 {Path(__file__).resolve()} --refs <id>")
            return 1
        subject, nxt = TEXT[lang]
        scope = f"({ids[0]})" if ids else ""
        refs = f"Refs: {', '.join(ids)}\n" if ids else ""
        message = (f"chore{scope}: {subject.format(branch=branch)}\n\n{refs}"
                   f"{NEXT[lang]}: {nxt.format(branch=branch)}\n")
        for cmd in (["add", "--", ledger], ["commit", "-m", message, "--", ledger]):
            res = git(root, *cmd)
            if res.returncode != 0:
                say(f"git {cmd[0]} of the ledger failed: {(res.stderr or res.stdout).strip()}; fix it and run it again")
                return 1
        print(f"{PROG}: committed {ledger}")

    return git(root, "merge", "--no-edit", f"origin/{branch}", capture=False).returncode


if __name__ == "__main__":
    sys.exit(main())
