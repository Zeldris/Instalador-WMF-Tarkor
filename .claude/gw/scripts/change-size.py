#!/usr/bin/env python3
# galivelop-workflow v0.6.0
"""Size of a commit and of a review block, in changed lines, with a warning above `changeSize` (D43).

  python3 change-size.py              # warnings for the staged change and for the open block (staged included)
  python3 change-size.py --show       # also the counts when they are under the limits
  python3 change-size.py --base REV   # the block starts after REV instead of after the last review commit

Changed lines = added + deleted (`git diff --numstat`, no renames). They do not count: binary files, paths that match
a `changeSize.exclude` regex (the workflow's installed copies under `.claude/gw/`, lock files), paths git marks as
generated (`linguist-generated` in .gitattributes) and, of a paired document whose pair changes in the same commit
(`changeSize.pairs`: a regex on the path and its replacement, `docs/en/x.md` -> `docs/es/x.md`), the smaller side.

The commit is what is staged. The block is the review unit of a long branch (B18): the commits of the branch (not
merges, not in `origin/<protectedBranch>`, or the local branch without a remote) after the newest one carrying the
`metrics.quality.findingsTrailer` trailer (`Findings:`, which the fix commit of a block review carries; `Findings: 0`
when the review found nothing), plus the staged change. It is the sum of each commit's count, so a line changed twice counts
twice: an upper bound of the review's diff. On the protected branch, or without it, there is no block (a note says so
for the latter).

Who calls it: `recover.py --state` (D85: `block`, for its overdue-review warning) and the commit-msg hook, before every commit that is not a merge, revert, cherry-pick or rebase step; it
only warns (exit 0) and never stops a commit, unless `changeSize.severity` is "block" (A13): then it exits 3 when a limit
is exceeded and the hook rejects the commit. A limit of 0 turns its warning off. Fails closed on what it cannot know:
an invalid config, a git error or a --base that is not a commit -> exit 2 with what fixes it. Project root and config:
config.find_root and config.load. Python 3.8+ standard library only.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, str(HERE))
import config  # noqa: E402

PROG = "change-size"
EXCEEDED = 3  # exit code of "a limit is exceeded and changeSize.severity is block" (1 stays an unexpected crash)


class SizeError(Exception):
    pass


def git(root, *args):
    r = subprocess.run(["git", "-C", str(root), "-c", "core.quotepath=false", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise SizeError(f"git {' '.join(args)} failed: {r.stderr.strip() or r.returncode}; check the repository: "
                        "git status")
    return r.stdout


def has_ref(root, ref):
    return subprocess.run(["git", "-C", str(root), "rev-parse", "-q", "--verify", f"{ref}^{{commit}}"],
                          capture_output=True).returncode == 0


def numstat_entries(tokens):
    """(path, lines) from -z numstat tokens 'added\\tdeleted\\tpath'; a binary file ('-') counts 0."""
    for token in tokens:
        token = token.lstrip("\n")
        if not token:
            continue
        added, deleted, path = token.split("\t", 2)
        lines = 0 if added == "-" or deleted == "-" else int(added) + int(deleted)
        yield path, lines


def generated(root, paths, cached):
    """The paths git marks as generated (linguist-generated set or true), from the index's .gitattributes if cached."""
    if not paths:
        return set()
    args = ["git", "-C", str(root), "check-attr", "-z", "--stdin", *(["--cached"] if cached else []),
            "linguist-generated"]
    r = subprocess.run(args, input="\0".join(paths) + "\0", capture_output=True, text=True)
    if r.returncode != 0:
        raise SizeError(f"git check-attr failed: {r.stderr.strip()}; check .gitattributes: git check-attr -a <path>")
    out = r.stdout.split("\0")
    return {out[i] for i in range(0, len(out) - 2, 3) if out[i + 2] in ("set", "true")}


def count(files, settings, skip):
    """Changed lines of one commit's {path: lines}: excluded and generated paths out, the smaller side of a pair out."""
    kept = {p: n for p, n in files.items()
            if p not in skip and not any(re.search(rx, p) for rx in settings["exclude"])}
    total = sum(kept.values())
    paired = set()
    for path in sorted(kept):
        for rx, repl in settings["pairs"].items():
            if path in paired or not re.search(rx, path):
                continue
            other = re.sub(rx, repl, path, count=1)
            if other != path and other in kept and other not in paired:
                total -= min(kept[path], kept[other])
                paired.update((path, other))
    return total


def staged_count(root, settings):
    files = dict(numstat_entries(git(root, "diff", "--cached", "--numstat", "-z", "--no-renames").split("\0")))
    return count(files, settings, generated(root, list(files), cached=True))


def protected_ref(root, cfg):
    branch = cfg.get("protectedBranch") or "main"
    for ref in (f"refs/remotes/origin/{branch}", f"refs/heads/{branch}"):
        if has_ref(root, ref):
            return branch, ref
    return branch, None


def block(root, cfg, settings, base):
    """(lines of the block's commits, description of where it starts) or None when there is no block."""
    if not has_ref(root, "HEAD"):
        return None
    branch, ref = protected_ref(root, cfg)
    current = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if current == branch:
        return None
    if base is not None:
        if not has_ref(root, base):
            raise SizeError(f"--base {base} is not a commit; give one that is: git log --oneline")
        stop = ["^" + base]
        where = f"after {base}"
    elif ref is None:
        print(f"{PROG}: no origin/{branch} nor {branch}, so the block size is not checked; give its start: "
              f"python3 {Path(__file__).name} --base <commit>", file=sys.stderr)
        return None
    else:
        stop = ["^" + ref]
        where = f"since the branch left {ref.split('/', 2)[-1]}"
    key = config.metrics(cfg)["quality"]["findingsTrailer"]
    out = git(root, "log", "-z", "--no-merges", "--numstat", "--no-renames",
              f"--format=%x01%H %(trailers:key={key},valueonly,separator=%x2C)", "HEAD", *stop)
    commits = []  # newest first: [sha, {path: lines}]
    for token in out.split("\0"):
        if token.startswith("\x01"):
            sha, _, trailer = token[1:].partition(" ")
            if trailer.strip() and base is None:
                where = f"after {sha[:12]} (last commit with a {key}: trailer)"
                break
            commits.append((sha, {}))
        elif commits:
            commits[-1][1].update(numstat_entries([token]))
    paths = sorted({p for _, files in commits for p in files})
    skip = generated(root, paths, cached=False)
    return sum(count(files, settings, skip) for _, files in commits), where, len(commits)


def main(argv=None):
    parser = argparse.ArgumentParser(prog=PROG, description=__doc__.splitlines()[0])
    parser.add_argument("--root", help="project root (default: the git top level of the current directory)")
    parser.add_argument("--show", action="store_true", help="print the counts even under the limits")
    parser.add_argument("--base", help="the block starts after this commit")
    args = parser.parse_args(argv)
    try:
        root = Path(config.find_root(args.root)).resolve()
        cfg = config.load(root)
    except config.ConfigError as exc:
        print(f"{PROG}: {exc}; fix it: python3 {HERE / 'config.py'} --root <project> validate", file=sys.stderr)
        return 2
    settings = config.change_size(cfg)
    trailer = config.metrics(cfg)["quality"]["findingsTrailer"]
    try:
        commit = staged_count(root, settings)
        blk = block(root, cfg, settings, args.base)
    except SizeError as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 2
    limit = settings["commit"]
    strict = settings["severity"] == "block"
    label = "ERROR" if strict else "WARNING"
    failed = False
    if limit and commit > limit:
        failed = strict
        print(f"{PROG}: {label}: this commit changes {commit} lines (more than {limit}, changeSize.commit in "
              ".claude/gw.json); if it holds more than one step, split it: git restore --staged <file>, commit "
              "the rest, then the next step", file=sys.stderr)
    elif args.show:
        print(f"{PROG}: the staged change: {commit} lines (limit {limit or 'off'})")
    if blk is not None:
        lines, where, n = blk
        total, limit = lines + commit, settings["block"]
        if limit and total > limit:
            failed = failed or strict
            print(f"{PROG}: {label}: the block {where} changes {total} lines with this commit ({n} commit(s) before "
                  f"it; more than {limit}, changeSize.block in .claude/gw.json); close it: /code-review of its diff, "
                  f"and its fix commit carries `{trailer}: <n>` (0 if the review found nothing)",
                  file=sys.stderr)
        elif args.show:
            print(f"{PROG}: the block {where}: {total} lines with the staged change, {n} commit(s) (limit "
                  f"{limit or 'off'})")
    return EXCEEDED if failed else 0


if __name__ == "__main__":
    sys.exit(main())
