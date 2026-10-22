#!/usr/bin/env python3
# galivelop-workflow v0.2.0
"""Broken links and stale references in the project's Markdown (a check for CI and `check`).

1. Relative links `[text](path)` and `[text](path#anchor)` in the tracked .md files: the file must exist and, when
   the link has an anchor and the target is a .md, it must have a heading with that anchor (as GitHub makes them).
   External links (http, mailto...) are not looked at; code fences and `inline code` are skipped.
2. `staleRefs` of .claude/gw.json: case-insensitive regexes that must not appear in the tracked files of docs/ and
   in README* at the root (a renamed task id or a removed phase that a document still mentions). The log file
   (config `log`) and .claude/ are skipped: the log may talk about the past.

  python3 enlaces-md.py [--files-only]     # --files-only: do not check anchors
Prints `file:line: problem` for each; exit 1 if any (the last line has the command to rerun), 2 on a bad config.
Python 3.8+, stdlib only. Root from this script's folder, via config.py.
"""
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as gwconfig  # noqa: E402

LINK = re.compile(r'(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
FENCE = re.compile(r'^\s*(```|~~~)')
_anchors = {}


def anchor(text):
    """The anchor GitHub gives a heading."""
    t = re.sub(r'`|\*\*|\*|~~|\[|\]\([^)]*\)', '', text.strip().lower())
    t = re.sub(r'[^\w\- ]', '', t, flags=re.UNICODE)
    return t.replace(' ', '-')


def anchors_of(path):
    if path not in _anchors:
        seen, in_code, found = {}, False, set()
        for line in path.read_text(encoding='utf-8').splitlines():
            if FENCE.match(line):
                in_code = not in_code
            if in_code:
                continue
            m = re.match(r'^#{1,6}\s+(.*?)\s*#*\s*$', line)
            if m:
                a = anchor(m.group(1))
                n = seen.get(a, 0)
                seen[a] = n + 1
                found.add(a if n == 0 else f'{a}-{n}')
            found |= {i.lower() for i in re.findall(r'<a\s+(?:name|id)="([^"]+)"', line)}
        _anchors[path] = found
    return _anchors[path]


def tracked(root, *patterns):
    out = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--', *patterns], capture_output=True, text=True)
    return [f for f in out.stdout.split('\0') if f and (root / f).is_file()]


def broken_links(root, md_files, files_only):
    problems = []
    for rel in md_files:
        path = root / rel
        in_code = False
        for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if FENCE.match(line):
                in_code = not in_code
            if in_code:
                continue
            for target in LINK.findall(re.sub(r'`[^`]*`', '', line)):
                if re.match(r'^[a-z]+:', target) or target.startswith('<'):
                    continue
                where, _, frag = target.partition('#')
                frag = urllib.parse.unquote(frag).lower()  # GitHub accepts upper case and encoded accents
                where = urllib.parse.unquote(where)
                dest = (path.parent / where).resolve() if where else path
                if where and not dest.exists():
                    problems.append(f'{rel}:{n}: no such file {where}; fix the link or create the file')
                elif frag and not files_only and dest.suffix == '.md' and dest.is_file() and frag not in anchors_of(dest):
                    problems.append(f'{rel}:{n}: {where or "(this file)"} has no heading with the anchor #{frag}')
    return problems


def stale_refs(root, patterns, log):
    problems = []
    compiled = []
    for p in patterns:
        try:
            compiled.append((p, re.compile(p, re.I)))
        except re.error as exc:
            raise gwconfig.ConfigError(f'staleRefs: {p!r} is not a valid regex ({exc}); fix .claude/gw.json')
    if not compiled:
        return problems
    files = [f for f in tracked(root) if (f.startswith('docs/') or ('/' not in f and f.upper().startswith('README')))
             and f != log and not f.startswith('.claude/')]
    for rel in files:
        try:
            text = (root / rel).read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable: not a document
        for n, line in enumerate(text.splitlines(), 1):
            for p, rx in compiled:
                m = rx.search(line)
                if m:
                    problems.append(f'{rel}:{n}: stale reference /{p}/ matches {m.group(0)!r}; update the text')
    return problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if any(a not in ('--files-only',) for a in argv):
        print('usage: python3 enlaces-md.py [--files-only]', file=sys.stderr)
        return 2
    try:
        cfg = gwconfig.load()
        root = cfg['_root']
        problems = broken_links(root, tracked(root, '*.md'), '--files-only' in argv)
        problems += stale_refs(root, cfg.get('staleRefs', []), cfg['log'])
    except gwconfig.ConfigError as exc:
        print(f'enlaces-md: {exc}; fix it: python3 {HERE / "config.py"} validate', file=sys.stderr)
        return 2
    for p in problems:
        print(p)
    if problems:
        print(f'{len(problems)} problem(s) in the Markdown; fix them and rerun: python3 {Path(__file__).resolve()}')
        return 1
    print('Markdown links and references OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
