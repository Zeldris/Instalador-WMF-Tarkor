#!/usr/bin/env python3
"""gw-media-content: figures about a project, computed from its repo, for the agent to quote (never to invent).

    python3 figures.py [--since REF] [--version-file PATH]

Run it from inside the project's git repository; the root is `git rev-parse --show-toplevel`. Prints one JSON object
on stdout: {"root", "today", "since", "figures": {name: {"value": ..., "source": "<command that gives it>"}}}. A figure
that cannot be computed has "value": null and a "note" saying why. Every number in a post comes from here or from a
file:line / commit the post's sheet.md cites.

  --since REF         count from REF (tag, branch or commit; exclusive) up to HEAD. Default: the last tag reachable
                      from HEAD; with no tag, the whole history (the "since" field says so).
  --version-file P    file (relative to the root) that holds the project's version; default: the first of
                      package.json, .claude-plugin/plugin.json, pyproject.toml, Cargo.toml, VERSION that has a
                      readable version. TOML: only [project] or [tool.poetry] (pyproject) and [package] or
                      [workspace.package] (Cargo) count; a dynamic or workspace-inherited version is "not readable".

"Last tag" means the nearest tag that looks like a version (v1.2, 1.2.3...); moving tags such as `latest` or `nightly`
are ignored. When that tag points at HEAD the count would be zero, so it starts at the previous version tag instead
(the "since" field says so); with no previous tag it starts at the first commit.

The old option name --desde is still accepted (with a warning on stderr) during 0.x.

Fails closed (exit 2, message on stderr) outside a git repository, with no commits, in a shallow clone (its history is
truncated, so every figure would be wrong), or with a REF git does not know. Needs git 2.13+ and Python 3.7+.
"""
import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

VERSION_TAG = re.compile(r"^v?\d+\.\d+")
TOML_TABLES = ("project", "tool.poetry", "package", "workspace.package")
TOML_HEADER = re.compile(r"^\s*\[\[?\s*([^\[\]]+?)\s*\]\]?\s*(?:#.*)?$")
TOML_VERSION = re.compile(r"""^\s*version\s*=\s*(?:"([^"]*)"|'([^']*)')\s*(?:#.*)?$""")
TOML_INHERITED = re.compile(r"^\s*(?:version\s*\.\s*workspace\s*=\s*true|version\s*=\s*\{\s*workspace\s*=\s*true\s*\})"
                            r"\s*(?:#.*)?$")
TOML_DYNAMIC = re.compile(r"""(?s)(?:^|\n)\s*dynamic\s*=\s*\[[^\]]*["']version["']""")
VERSION_FILES = ("package.json", ".claude-plugin/plugin.json", "pyproject.toml", "Cargo.toml", "VERSION")
TEST_NAME = re.compile(r"(?:^|/)(?:test_[^/]+\.(?:py|sh|mjs|js)|[^/]+_test\.(?:py|go|rb)|[^/]+\.(?:test|spec)\.(?:[cm]?[jt]sx?)"
                       r"|[^/]+Test\.java)$")
TEST_NAME_TEXT = "test_*.py|sh|mjs|js, *_test.py|go|rb, *.test|spec.js|ts|mjs|jsx|tsx, *Test.java"
MAX_SUBJECTS = 20


class Failure(Exception):
    pass


def git(root, *args, check=True, raw=False):
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, errors="replace")
    if check and proc.returncode != 0:
        raise Failure(f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()}")
    if proc.returncode != 0:
        return None
    return proc.stdout if raw else proc.stdout.strip()


def git_list(root, *args):
    """NUL-separated git output (-z) as a list: safe for names with spaces, quotes or non-ASCII characters."""
    return [x for x in git(root, args[0], "-z", *args[1:], raw=True).split("\0") if x]


def find_root():
    try:
        proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    except OSError as exc:
        raise Failure(f"cannot run git ({exc}); install git")
    if proc.returncode != 0 or not proc.stdout.strip():
        raise Failure("not inside a git repository; run it from the project folder: cd <project> && python3 figures.py")
    return Path(proc.stdout.strip())


def figure(value, source, note=None):
    out = {"value": value, "source": source}
    if note:
        out["note"] = note
    return out


def toml_sections(text):
    """{table name: its lines}; tables that appear twice are joined. Enough for the version keys, not a TOML parser."""
    sections, current = {"": []}, ""
    for line in text.splitlines():
        m = TOML_HEADER.match(line)
        if m:
            current = re.sub(r"\s*\.\s*", ".", m.group(1).strip()).replace('"', "").replace("'", "")
            sections.setdefault(current, [])
        else:
            sections[current].append(line)
    return sections


def toml_version(text):
    """(version, None) or (None, why it is not readable). Only the tables that name the project's own version."""
    sections = toml_sections(text)
    why = []
    for table in TOML_TABLES:
        lines = sections.get(table)
        if lines is None:
            continue
        for line in lines:
            m = TOML_VERSION.match(line)
            if m and (m.group(1) or m.group(2)):
                return m.group(1) or m.group(2), None
            if TOML_INHERITED.match(line):
                why.append(f"[{table}] inherits it from the workspace")
                break
        else:
            if table == "project" and TOML_DYNAMIC.search("\n".join(lines)):
                why.append('[project] declares dynamic = ["version"]')
    return None, "; ".join(why) or "no version key in [project], [tool.poetry], [package] or [workspace.package]"


def read_version(path):
    """(version, None) or (None, why it is not readable) for one file; BOM-tolerant."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if path.suffix == ".json":
        try:
            data = json.loads(text)
        except ValueError:
            return None, "not valid JSON"
        found = data.get("version") if isinstance(data, dict) else None
        if isinstance(found, str) and found.strip():
            return found.strip(), None
        return None, 'no string "version" key'
    if path.suffix == ".toml":
        return toml_version(text)
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line, None
    return None, "no line that is not blank or a # comment"


def project_version(root, explicit):
    """The project's own version, from the first known file that has a readable one (or --version-file)."""
    candidates = (explicit,) if explicit else VERSION_FILES
    unreadable = []
    for rel in candidates:
        path = root / rel
        if not path.is_file():
            if explicit:
                raise Failure(f"--version-file {explicit}: no such file in {root}; pass a path relative to the root")
            continue
        found, why = read_version(path)
        if found:
            return figure(found, f"read {rel}")
        if explicit:
            raise Failure(f"--version-file {explicit}: no version found in it ({why}); point to the file that holds it")
        unreadable.append((rel, why))
    if unreadable:
        return figure(None, "read " + ", ".join(rel for rel, _ in unreadable),
                      "; ".join(f"{rel} found, but its version is not readable ({why})" for rel, why in unreadable)
                      + "; pass --version-file <path> to read another file")
    return figure(None, "package.json, .claude-plugin/plugin.json, pyproject.toml, Cargo.toml, VERSION",
                  "no known version file; pass --version-file <path>")


def config_reader(root):
    """The workflow's config reader, if the project has one (installed copy first, then this repo's own)."""
    for rel in (".claude/gw/scripts/config.py", "scripts/config.py"):
        if (root / rel).is_file() and (root / ".claude" / "gw.json").is_file():
            return root / rel
    return None


def config_value(root, reader, key):
    proc = subprocess.run([sys.executable, str(reader), "--root", str(root), "get", key],
                          capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        return None, (proc.stderr.strip().splitlines() or ["the config reader failed"])[0]
    return proc.stdout.strip() or None, None


def changelog_headings(root):
    path = root / "CHANGELOG.md"
    if not path.is_file():
        return figure(None, "CHANGELOG.md", "no CHANGELOG.md at the root")
    section, headings = None, []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        m = re.match(r"^(#{2,6})\s+(.*\S)\s*$", line)
        if not m:
            continue
        if len(m.group(1)) == 2:
            if section is not None:
                break
            section = m.group(2)
        elif section is not None:
            headings.append(m.group(2))
    if section is None:
        return figure(None, "CHANGELOG.md", "CHANGELOG.md has no '## ' section")
    return figure({"section": section, "headings": headings},
                  "first '## ' section of CHANGELOG.md and its sub-headings")


def version_tag(root, rev, skip=()):
    """The nearest tag reachable from REV whose name looks like a version; `latest`, `nightly`... and SKIP are skipped."""
    excluded = list(skip)
    while True:
        args = ["describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "--match", "[0-9]*"]
        for name in excluded:
            args += ["--exclude", name]
        tag = git(root, *args, rev, check=False)
        if not tag:
            return None
        if VERSION_TAG.match(tag):
            return tag
        excluded.append(tag)


def is_shallow(root):
    if git(root, "rev-parse", "--is-shallow-repository", check=False) == "true":
        return True
    marker = git(root, "rev-parse", "--git-path", "shallow", check=False)  # git older than 2.15 has no such flag
    return bool(marker) and (root / marker).is_file()


def compute(root, since, version_file):
    head = git(root, "rev-parse", "--verify", "-q", "HEAD^{commit}", check=False) or _no_commits()
    if is_shallow(root):
        raise Failure("this is a shallow clone: its history is truncated, so commit counts, dates and the last tag would "
                    "be wrong; fetch the full history first: git fetch --unshallow --tags")
    figures = {}
    figures["project_version"] = project_version(root, version_file)
    reader = config_reader(root)
    if reader:
        cmd = f"python3 {reader.relative_to(root).as_posix()} get log"
        log, error = config_value(root, reader, "log")
        figures["log"] = figure(log, cmd, None if log else error or "gw.json has no 'log'")
    tag = version_tag(root, "HEAD")
    on_head = bool(tag) and git(root, "rev-parse", "--verify", "-q", f"refs/tags/{tag}^{{commit}}", check=False) == head
    # From HEAD itself, not HEAD^: on a tagged merge the previous tag may be reachable only through the second parent
    # (tag names have no whitespace, so split() is safe; git tag has no -z).
    previous = version_tag(root, "HEAD", git(root, "tag", "--points-at", "HEAD").split()) if on_head else None
    figures["last_tag"] = figure(
        tag, "git describe --tags --abbrev=0 --match 'v[0-9]*' --match '[0-9]*'",
        "points at HEAD" if on_head else None if tag else "the repo has no version tags (names like v1.2.3)")
    if since:
        if not git(root, "rev-parse", "--verify", "-q", f"{since}^{{commit}}", check=False):
            raise Failure(f"--since {since}: git does not know that ref; use a tag, branch or commit "
                        f"(git tag --list, git log --oneline)")
        base, base_text = since, f"--since {since}"
    elif on_head and previous:
        base, base_text = previous, f"tag {tag} on HEAD; counting from previous tag {previous}"
    elif on_head:
        base, base_text = None, f"tag {tag} on HEAD and no previous version tag; counting from the first commit"
    elif tag:
        base, base_text = tag, f"last tag {tag}"
    else:
        base, base_text = None, "first commit (the repo has no version tags)"
    rng = f"{base}..HEAD" if base else "HEAD"
    n = int(git(root, "rev-list", "--count", rng))
    figures["commits_since"] = figure(n, f"git rev-list --count {rng}")
    plain = int(git(root, "rev-list", "--count", "--no-merges", rng))
    figures["commits_no_merges"] = figure(plain, f"git rev-list --count --no-merges {rng}")
    subjects = git(root, "log", "--no-merges", f"--max-count={MAX_SUBJECTS}", "--format=%h %s", rng).splitlines()
    figures["commit_subjects"] = figure(subjects, f"git log --no-merges --max-count={MAX_SUBJECTS} --format='%h %s' {rng}",
                                       f"the newest {MAX_SUBJECTS} at most" if plain > MAX_SUBJECTS else None)
    dates = sorted(git(root, "log", "--format=%ad", "--date=short", rng).split())
    figures["date_range"] = figure({"first": dates[0], "last": dates[-1]} if dates else None,
                                    f"git log --format=%ad --date=short {rng}", None if dates else "no commits in the range")
    if base:
        # Three dots: from the merge base, like the base..HEAD commit count, even when BASE is not an ancestor of HEAD.
        names = git_list(root, "diff", "--name-only", f"{base}...HEAD")
        add = rem = 0
        for line in git(root, "diff", "--numstat", f"{base}...HEAD").splitlines():
            a, r, _ = (line.split("\t", 2) + ["", ""])[:3]
            add += int(a) if a.isdigit() else 0
            rem += int(r) if r.isdigit() else 0
        figures["changed_files"] = figure({"files": len(names), "lines_added": add, "lines_removed": rem},
                                          f"git diff --numstat {base}...HEAD")
    else:
        files = git_list(root, "ls-files")
        figures["changed_files"] = figure({"files": len(files)}, "git ls-files | wc -l",
                                          "no base ref: every tracked file counts as new")
    figures["changelog_last_section"] = changelog_headings(root)
    tests = [f for f in git_list(root, "ls-files") if TEST_NAME.search(f)]
    figures["test_files"] = figure(len(tests), f"git ls-files, names matching {TEST_NAME_TEXT}")
    return base_text, figures


def _no_commits():
    raise Failure("the repository has no commits yet; make a commit first")


OLD_OPTIONS = {"--desde": "--since"}


def rename_old_options(argv):
    """0.x compatibility: accept the old Spanish option names, warning on stderr with the new one."""
    out = []
    for arg in argv:
        name, eq, rest = arg.partition("=")
        if name in OLD_OPTIONS:
            print(f"figures.py: warning: {name} is deprecated; use {OLD_OPTIONS[name]}", file=sys.stderr)
            arg = OLD_OPTIONS[name] + eq + rest
        out.append(arg)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="figures.py", description="Figures from the repo for gw-media-content posts.")
    ap.add_argument("--since", metavar="REF", help="count from this tag/branch/commit (default: the last tag)")
    ap.add_argument("--version-file", metavar="PATH", help="file with the project's version, relative to the root")
    args = ap.parse_args(rename_old_options(sys.argv[1:] if argv is None else argv))
    try:
        root = find_root()
        base_text, figures = compute(root, args.since, args.version_file)
    except Failure as exc:
        print(f"figures.py: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"root": str(root), "today": datetime.date.today().isoformat(), "since": base_text,
                      "figures": figures}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
