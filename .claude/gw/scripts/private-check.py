#!/usr/bin/env python3
# galivelop-workflow v0.5.0
"""Nothing private reaches the public repo (plan §10, E2): key formats, e-mail addresses and private names.

  python3 private-check.py --range A..B   # what the commits of A..B add, one commit at a time
  python3 private-check.py --commits -    # the same for the commit shas on stdin, one per line (the pre-push hook
                                          # passes the commits each ref pushes)
  python3 private-check.py --all          # every tracked file as it is in the working tree (paths and content)
  options: --no-names (skip the private names), --root PATH, --rev REV (read .claude/gw.json as commit REV has it)

What a commit adds: its added lines (against its parent; a merge, only the lines that are in none of its parents),
the paths of the files it adds (renames included: --no-renames) and its message. So a value added in one commit and
removed in the next is still found: the history is published too.

Checks:
  - key/token formats: the KEY_FORMATS regex of the pre-commit hook (.githooks/pre-commit, else
    templates/githooks/pre-commit), read at run time so it lives in one place; not found -> exit 2.
  - e-mail addresses, unless privateCheck.emails is false. Allowed: example.com/.org/.net (and subdomains), any
    *.example domain, *@users.noreply.github.com, local part noreply/no-reply/git (git@<host> is an SSH remote),
    privateCheck.allowEmails of
    .claude/gw.json (public) and allowEmails of .claude/gw.local.json (private).
  - privateNames of the local file .claude/gw.local.json (never committed), plus the names of its `anonymize`
    (config.py adds them): case-insensitive, with `-`, `_` and space taken as the same. No local file: skipped with a
    notice; a malformed one: exit 2.
A line with gw-allow-private is skipped (a checked false positive); one with gw-allow-secret skips the key check only,
as in the pre-commit hook. privateCheck: false in .claude/gw.json turns everything off.
Exit 0 clean, 1 something found (at most 10 hits, `path:line: <kind> <match>`), 2 cannot check (fails closed).
The config is read by config.py, the only reader of .claude/gw.json and .claude/gw.local.json. Python 3.8+.
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True
import config  # noqa: E402

PROG = "private-check"
ALLOW_MARK = "gw-allow-private"
SECRET_MARK = "gw-allow-secret"
MAX_HITS = 10
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![A-Za-z0-9-])")
PUBLIC_DOMAINS = ("example.com", "example.org", "example.net")


class CheckError(Exception):
    pass


def git(root, *args):
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    r = subprocess.run(["git", "-C", str(root), "-c", "core.quotePath=false", *args], capture_output=True, env=env)
    if r.returncode != 0:
        raise CheckError(f"git {' '.join(args)} failed: {r.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return r.stdout.decode("utf-8", "replace")


def key_formats(root):
    """The KEY_FORMATS regex of the pre-commit hook, compiled. Raises CheckError when no hook holds it."""
    for rel in (".githooks/pre-commit", "templates/githooks/pre-commit"):
        hook = Path(root) / rel
        if not hook.is_file():
            continue
        for line in hook.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"KEY_FORMATS='(.+)'\s*$", line)
            if m:
                try:
                    return re.compile(m.group(1))
                except re.error as exc:
                    raise CheckError(f"the KEY_FORMATS regex of {hook} does not compile ({exc}); reinstall the "
                                     f"hooks: /gw-update")
        raise CheckError(f"{hook} has no KEY_FORMATS line; reinstall the hooks: /gw-update")
    raise CheckError(f"no pre-commit hook with KEY_FORMATS in {root} (.githooks/pre-commit); reinstall the hooks: "
                     f"/gw-update")


def email_allowed(address, allowed):
    address = address.lower()
    local, _, domain = address.rpartition("@")
    # git@<host> is an SSH remote (git@github.com:owner/repo), not a person's address.
    if address in allowed or local in ("noreply", "no-reply", "git") or domain == "users.noreply.github.com":
        return True
    if domain == "example" or domain.endswith(".example"):
        return True
    return any(domain == d or domain.endswith("." + d) for d in PUBLIC_DOMAINS)


def name_regex(names):
    """One case-insensitive regex for all private names; `-`, `_` and whitespace inside a name match each other."""
    parts = []
    for name in names:
        words = [re.escape(w) for w in re.split(r"[-_\s]+", name.strip()) if w]
        if words:
            parts.append(r"[-_\s]".join(words))
    return re.compile("|".join(sorted(parts, key=len, reverse=True)), re.IGNORECASE) if parts else None


class Scanner:
    def __init__(self, keys, emails, allowed, names):
        self.keys, self.emails, self.allowed, self.names = keys, emails, {a.lower() for a in allowed}, names
        self.hits = []
        self.total = 0

    def line(self, where, text):
        if ALLOW_MARK in text:
            return
        found = []
        if SECRET_MARK not in text:
            for m in self.keys.finditer(text):
                value = re.sub(r"^(\\[nrt]|%[0-9A-Fa-f]{2}|[^A-Za-z0-9-])", "", m.group(0))
                found.append(("key", value[:8] + "…"))
        if self.emails:
            found += [("e-mail", m.group(0)) for m in EMAIL.finditer(text) if not email_allowed(m.group(0), self.allowed)]
        if self.names is not None:
            found += [("private name", m.group(0)) for m in self.names.finditer(text)]
        for kind, value in found:
            self.total += 1
            if len(self.hits) < MAX_HITS:
                self.hits.append(f"{where}: {kind} {value}")


def parse_hunks(diff, scan, suffix):
    """Feed every added line of a `git diff-tree -p` (plain or --cc) to scan(where, text)."""
    path, lineno, width = None, 0, 1
    for raw in diff.splitlines():
        if raw.startswith(("diff --git ", "diff --cc ", "diff --combined ")):
            path, width = None, 1
            continue
        if raw.startswith("+++ "):
            target = raw[4:]
            if target.startswith('"') and target.endswith('"'):
                target = target[1:-1]
            path = None if target == "/dev/null" else target[2:] if target.startswith("b/") else target
            continue
        m = re.match(r"(@+) .*?\+(\d+)(?:,\d+)? @+", raw)
        if m:
            width, lineno = len(m.group(1)) - 1, int(m.group(2))
            continue
        if path is None or len(raw) < width:
            continue
        prefix, text = raw[:width], raw[width:]
        if "-" in prefix or not set(prefix) <= {" ", "+"}:
            continue  # removed from the result (or "\ No newline at end of file")
        if prefix == "+" * width:
            scan(f"{path}:{lineno}{suffix}", text)
        lineno += 1


def scan_commit(root, sha, scanner):
    short = sha[:7]
    suffix = f" (commit {short})"
    parents = git(root, "rev-list", "--parents", "-n", "1", sha).split()[1:]
    if len(parents) > 1:
        status = git(root, "diff-tree", "-r", "-c", "--no-renames", "--no-commit-id", "--name-status", "-z", sha)
        fields = status.split("\0")
        added = [fields[i + 1] for i in range(0, len(fields) - 1, 2) if set(fields[i]) == {"A"}]
        diff = git(root, "diff-tree", "-p", "--cc", "--no-renames", "--no-commit-id", sha)
    else:
        added = [p for p in git(root, "diff-tree", "-r", "--root", "--no-renames", "--no-commit-id",
                                "--diff-filter=A", "--name-only", "-z", sha).split("\0") if p]
        diff = git(root, "diff-tree", "-p", "-U0", "--root", "--no-renames", "--no-commit-id", sha)
    for path in added:
        scanner.line(f"{path}{suffix} (path)", path)
    parse_hunks(diff, scanner.line, suffix)
    for text in git(root, "log", "-1", "--format=%B", sha).splitlines():
        scanner.line(f"commit {short} (message)", text)


def scan_tree(root, scanner):
    listing = git(root, "ls-files", "-z", "-s")
    for entry in listing.split("\0"):
        if not entry:
            continue
        meta, _, path = entry.partition("\t")
        scanner.line(f"{path} (path)", path)
        if meta.split()[0] not in ("100644", "100755"):
            continue  # symlink or submodule
        try:
            data = (Path(root) / path).read_bytes()
        except OSError:
            continue  # deleted in the working tree: nothing there to publish
        if b"\0" in data[:8000]:
            continue  # binary
        for n, text in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            scanner.line(f"{path}:{n}", text)


def commits_of(root, args):
    if args.range:
        if ".." not in args.range or "..." in args.range:
            raise CheckError(f"--range needs A..B, got {args.range!r}; e.g. --range origin/main..HEAD")
        base = args.range.split("..", 1)[0]
        try:
            git(root, "rev-parse", "-q", "--verify", f"{base}^{{commit}}")
        except CheckError:
            raise CheckError(f"the base of {args.range} is not in this clone; fetch it: git fetch --deepen=200 origin")
        return [s for s in git(root, "rev-list", "--reverse", args.range).split() if s]
    source = sys.stdin if args.commits == "-" else open(args.commits, encoding="utf-8")
    with source:
        shas = [s.strip() for s in source if s.strip()]
    for sha in shas:
        try:
            git(root, "cat-file", "-e", f"{sha}^{{commit}}")
        except CheckError:
            raise CheckError(f"commit {sha[:12]} is not in this clone; fetch it and retry: git fetch origin")
    return shas


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--range", metavar="A..B", help="scan what the commits of A..B add")
    what.add_argument("--commits", metavar="FILE", help="scan the commits listed in FILE (- for stdin)")
    what.add_argument("--all", action="store_true", help="scan every tracked file of the working tree")
    parser.add_argument("--no-names", action="store_true", help="skip the private names of .claude/gw.local.json")
    parser.add_argument("--root", help="project path (default: as config.py finds it)")
    parser.add_argument("--rev", help="read .claude/gw.json as this commit has it (the pushed one)")
    args = parser.parse_args(argv)
    try:
        cfg = config.load(args.root, args.rev)
        root = cfg["_root"]
        settings = config.private_check(cfg)
        if settings is None:
            print(f"{PROG}: off (privateCheck is false in .claude/gw.json)", file=sys.stderr)
            return 0
        names = None
        if not args.no_names:
            local = config.load_local(root)
            if local is None:
                print(f"{PROG}: no {config.LOCAL_REL.as_posix()}, so private names are not checked; list them there: "
                      f'{{"privateNames": ["..."]}}', file=sys.stderr)
            else:
                names = name_regex(local["privateNames"])
        local_allow = (config.load_local(root) or {}).get("allowEmails", [])
        scanner = Scanner(key_formats(root), settings["emails"], settings["allowEmails"] + local_allow, names)
        if args.all:
            scan_tree(root, scanner)
        else:
            for sha in commits_of(root, args):
                scan_commit(root, sha, scanner)
    except (config.ConfigError, CheckError, OSError) as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return 2
    if not scanner.total:
        return 0
    print(f"{PROG}: found something that must not be public:", file=sys.stderr)
    for hit in scanner.hits:
        print(f"  {hit}", file=sys.stderr)
    if scanner.total > len(scanner.hits):
        print(f"  … and {scanner.total - len(scanner.hits)} more", file=sys.stderr)
    allow = (f"a public address goes in privateCheck.allowEmails of .claude/gw.json, a private one in allowEmails of "
             f"{config.LOCAL_REL.as_posix()}; a checked false positive can carry {ALLOW_MARK} on its line")
    if args.all:
        print(f"{PROG}: remove it from the files ({allow}), then commit: git commit -a", file=sys.stderr)
    else:
        print(f"{PROG}: remove it from the commits that add it, not in a new one ({allow}); rewrite the unpushed "
              f"commits: git rebase -i <the remote branch>", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
