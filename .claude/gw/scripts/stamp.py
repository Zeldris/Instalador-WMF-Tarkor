#!/usr/bin/env python3
# galivelop-workflow v0.9.0
"""Stamped-version lines (B44, B45): the one reader of what the version stamp changes in a diff.

`version.py` writes the workflow version in a `galivelop-workflow vX.Y.Z` header (apply.HEADER), in the `version`
of a SKILL.md's metadata and in the top-level `"version"` of gw.json. A diff whose only changes are those lines says
nothing about the code: scope-guard.py (not a deviation) and review-scope.py --trivial (not counted lines) skip it.

  only_stamp(removed, added)  True when both line lists are non-empty and pair up as the same lines with another version
  stamp_diff(diff_text)       (stamp_lines, other_lines) counts of a `git diff -U0` of ONE file (PATH: that file)

The header pattern is the one of apply.py (workflow-only, so copied here: tests/test_stamp.py checks they agree); the
version keys count only in the files version.py stamps (SKILL.md, gw.json, plugin.json), the header only in a comment.
Python 3.8+ standard library only.
"""
import re

SEMVER = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?"
HEADER = re.compile(r"galivelop-workflow v(" + SEMVER + ")")
# The header lives in a comment (`# `, `// `, `<!-- `, `; `, `-- `, `/* `, ` * `): `MIN = "galivelop-workflow v0.8.0"` is code.
HEADER_LINE = re.compile(r"^\s*(?:#|//|<!--|;|--|/\*|\*)\s*galivelop-workflow v(" + SEMVER + ")")
# The two keys version.py stamps: SKILL.md's `metadata.version` and the top-level "version" of gw.json / plugin.json
# (its TOP_VERSION: a key on its own line, two-space indent). Any other file's `version:` is not a stamp.
KEY = re.compile(r"^(\s*)([\"']?)version\2(\s*[:=]\s*[\"']?)(" + SEMVER + r")([\"']?,?\s*)$")
JSON_KEY = re.compile(r'^(  "version"\s*:\s*")(' + SEMVER + r')(",?\s*)$')
JSON_STAMPED = ("gw.json", "plugin.json")


def normal(line, path=None):
    """The line with its stamped version replaced by `X`, or None when the line is not a stamp line. PATH (of the file
    the line is in) says which version key counts; without it only the header does."""
    line = line.rstrip("\r\n")
    if HEADER_LINE.search(line):
        return HEADER.sub("galivelop-workflow vX", line)
    name = str(path or "").replace("\\", "/").rsplit("/", 1)[-1]
    if name == "SKILL.md":
        m = KEY.match(line)
        if m:
            return f"{m.group(1)}{m.group(2)}version{m.group(2)}{m.group(3)}X{m.group(5)}"
    elif name in JSON_STAMPED:
        m = JSON_KEY.match(line)
        if m:
            return f'{m.group(1)}X{m.group(3)}'
    return None


def only_stamp(removed, added, path=None):
    """True when REMOVED and ADDED (lists of lines, markers dropped) are non-empty and every line is a stamp line, the two
    sides being the same lines up to the version."""
    if not removed or not added or len(removed) != len(added):
        return False
    old, new = [normal(x, path) for x in removed], [normal(x, path) for x in added]
    return None not in old and None not in new and old == new


def stamp_diff(text, path=None):
    """(stamp, other): changed lines of a `git diff -U0` (one file) that only change the stamp, and the rest."""
    removed, added = [], []
    in_hunk = False  # `---` and `+++` are file headers only before the first `@@`; inside a hunk they are changed lines
    for line in text.splitlines():
        if line.startswith("diff "):
            in_hunk = False
            continue
        if line.startswith("@@"):
            in_hunk = True
            continue
        if line.startswith(("index ", "\\")) or (not in_hunk and line.startswith(("--- ", "+++ "))):
            continue
        if line.startswith("-"):
            removed.append(line[1:])
        elif line.startswith("+"):
            added.append(line[1:])
    new = [normal(x, path) for x in added]
    stamp, left = 0, []
    for line in removed:
        n = normal(line, path)
        if n is not None and n in new:
            new[new.index(n)] = False  # paired: the same line with another version
            stamp += 2
        else:
            left.append(line)
    other = len(left) + sum(1 for x in new if x is not False)
    return stamp, other
