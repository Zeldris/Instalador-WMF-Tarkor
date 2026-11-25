#!/usr/bin/env python3
# galivelop-workflow v0.9.0
"""E72: the committed copies of generated files are up to date. For each entry of `generated` in .claude/gw.json
({"command": ..., "paths": [...]}), runs `command` with bash at the repo root and compares the files under its
`paths` (files or folders, relative to the root) before and after: a file changed, added or removed means the
committed copies were stale. The regenerated files stay on disk, so the fix is to commit them.

  python3 generated-check.py [--root PATH]

The comparison is with the files on disk before the command, not with HEAD: on a work tree with uncommitted changes
whose generated files are already regenerated it passes, and in CI (a clean checkout) it is the same as
`git diff --exit-code -- <paths>` after regenerating. Every entry runs, even after a failure, and each failure is
named. Exit 0 all up to date (or `generated` empty), 1 a command failed or changed its paths, 2 bad config (a path
outside the repository). Python 3.8+, stdlib only. Root from this script's path (config.find_root).
"""
import argparse
import hashlib
import os
import shlex
import subprocess
import tempfile
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True  # no __pycache__: it would make the tree look dirty
import config  # noqa: E402  the only reader of .claude/gw.json


def inside(root, rel):
    """The absolute path of `rel` when it stays inside `root`, else None."""
    if os.path.isabs(rel):
        return None
    full = os.path.realpath(os.path.join(str(root), rel))
    base = os.path.realpath(str(root))
    return full if full == base or full.startswith(base + os.sep) else None


def snapshot(root, paths):
    """{path relative to root: sha256} of every file under `paths` (a missing path has none; .git is skipped)."""
    found = {}

    def add(full):
        h = hashlib.sha256()
        try:
            with open(full, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 16), b""):
                    h.update(chunk)
        except OSError as exc:  # unreadable: its error is its content, so a change still shows
            h.update(str(exc).encode())
        found[os.path.relpath(full, str(root)).replace(os.sep, "/")] = h.hexdigest()

    for full in paths:
        if os.path.isfile(full) or os.path.islink(full):
            add(full)
        elif os.path.isdir(full):
            seen = set()  # real paths of the folders already walked: a symlink loop is walked once
            for top, dirs, files in os.walk(full, followlinks=True):
                real = os.path.realpath(top)
                if real in seen:
                    dirs[:] = []
                    continue
                seen.add(real)
                dirs[:] = sorted(d for d in dirs if d != ".git")
                for name in sorted(files):
                    add(os.path.join(top, name))
    return found


def outside_working_copy(root):
    """True when `root` is a linked worktree under the temp folder: where the pre-push runs the check, not the user's
    checkout, so the regenerated files on disk are not the ones the user can commit."""
    try:
        base = os.path.realpath(tempfile.gettempdir())
        real = os.path.realpath(str(root))
        linked = os.path.isfile(os.path.join(real, ".git"))
    except OSError:
        return False
    return linked and real.startswith(base.rstrip(os.sep) + os.sep)


def check_entry(root, entry):
    """Runs one entry; returns the list of lines that describe its failure (empty when up to date)."""
    command, rels = entry["command"], entry["paths"]
    fulls = [inside(root, rel) for rel in rels]
    before = snapshot(root, fulls)
    r = subprocess.run(["bash", "-c", command], cwd=str(root), stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        return [f"generated: '{command}' failed (exit {r.returncode}); fix the generator and run it again: "
                f"python3 {os.path.join(HERE, 'generated-check.py')}"]
    after = snapshot(root, fulls)
    diffs = ([f"  changed: {p}" for p in sorted(p for p in before if p in after and before[p] != after[p])]
             + [f"  added: {p}" for p in sorted(set(after) - set(before))]
             + [f"  removed: {p}" for p in sorted(set(before) - set(after))])
    if not diffs:
        return []
    quoted = " ".join(shlex.quote(rel) for rel in rels)
    if outside_working_copy(root):
        return ([f"generated: '{command}' changed {len(diffs)} file(s): the committed copies are stale"] + diffs
                + [f"generated: this run is in a temporary checkout, not your working copy; run `{command}` in your "
                   f"working copy, then git add -- {quoted}"])
    return ([f"generated: '{command}' changed {len(diffs)} file(s): the committed copies are stale"] + diffs
            + [f"generated: the regenerated files are on disk; commit them: git add -- {quoted}"])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root")
    args = p.parse_args(argv)
    fix = f"python3 {os.path.join(HERE, 'config.py')} validate"
    try:
        root = config.find_root(args.root)
        cfg = config.load(root)
    except config.ConfigError as exc:
        print(f"generated: {exc}; fix the config: {fix}", file=sys.stderr)
        return 2
    entries = cfg.get("generated") or []
    if not entries:
        print("generated: nothing to regenerate (`generated` in .claude/gw.json is empty)")
        return 0
    bad = [rel for e in entries for rel in e["paths"] if inside(root, rel) is None]
    if bad:
        print(f"generated: path(s) outside the repository in `generated`: {', '.join(bad)}; use paths relative to "
              f"the repo root in .claude/gw.json and check it: {fix}", file=sys.stderr)
        return 2
    failed = False
    for entry in entries:
        lines = check_entry(root, entry)
        if lines:
            failed = True
            print("\n".join(lines), file=sys.stderr)
        else:
            print(f"generated: '{entry['command']}' leaves {' '.join(entry['paths'])} up to date")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
