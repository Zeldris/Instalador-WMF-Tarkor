#!/usr/bin/env python3
"""Compare `architecture.md` with the project for `scout-updates`. Python 3 standard library only.

Usage:
  compare.py [<architecture.md>] [--root <root>] [--json] [--report <report.md>]
  (default root: the project holding this copy in .claude/skills, else `git rev-parse --show-toplevel`; never the
  current directory, so it works from a subfolder)
  compare.py [<architecture.md>] --section <title>   print only that section (to reread it without the whole file)

Without <architecture.md>, it is `architecture.md` in the `scoutDir` folder of the project's `.claude/gw.json`
(read with `.claude/gw/scripts/config.py`; default `.claude/gw/scout`).

The words the script looks for come in English and in Spanish (the `language` values of the config), whichever the
project uses: seal `seal`/`sello`, section `Constraints`/`Restricciones`, report section `Coverage`/`Cobertura`,
table header `Component`/`Componente`.

For every `## ...` section with a seal `<!-- seal: YYYY-MM-DD | <commit> | path, path -->` (references/formats.md;
the separator is `|`, a middle dot also works):
  same        no file of the seal changed since its commit (`git diff --name-only <commit>`, uncommitted included):
              just put today's date
  changed     some changed or vanished: reread that section (lists the files)
  unsealed    section without a seal, or with a commit git does not know: reread it
Plus `uncounted`: manifests found by `inventory.py` that appear in no seal (new components).
With `--report`, also `uncovered`: components of architecture.md (first column of its tables) that have no row in the
`## Coverage` table of the report (step 6).
Sections without components (e.g. Constraints) carry no seal and are not compared.
Exits 1 if there is something to reread, 0 if everything is the same.
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inventory

SECTION_RE = re.compile(r'^##\s+(.+?)\s*$', re.M)
SEAL_RE = re.compile(r'<!--\s*(?:seal|sello):\s*(\d{4}-\d{2}-\d{2})\s*[·|]\s*([0-9a-f]{4,40})\s*[·|]\s*(.*?)\s*-->')
NOT_COMPARED = ('constraints', 'restricciones')
COVERAGE = ('coverage', 'cobertura')
HEADERS = ('component', 'componente')


def sections(text):
    """[(title, date, commit, [paths])]; date/commit None if the section has no seal."""
    parts = SECTION_RE.split(text)
    out = []
    for title, body in zip(parts[1::2], parts[2::2]):
        if title.strip().lower() in NOT_COMPARED:
            continue
        m = SEAL_RE.search(body)
        if m:
            out.append((title, m.group(1), m.group(2), [r.strip() for r in m.group(3).split(',') if r.strip()]))
        else:
            out.append((title, None, None, []))
    return out


def first_column(body):
    """First cell of each table row, without header or separator, normalised."""
    cells = []
    for line in body.splitlines():
        if not line.startswith('|') or re.match(r'^\|\s*:?-', line):
            continue
        cell = line.split('|')[1].replace('`', '').strip().lower()
        if cell and cell not in HEADERS:
            cells.append(cell)
    return cells


def uncovered(arch_text, report_text):
    """Components of architecture.md with no row in the report's `## Coverage`, in order."""
    parts = SECTION_RE.split(arch_text)
    components = []
    for title, body in zip(parts[1::2], parts[2::2]):
        if title.strip().lower() not in NOT_COMPARED:
            components += first_column(body)
    parts = SECTION_RE.split(report_text)
    covered = set()
    for title, body in zip(parts[1::2], parts[2::2]):
        if title.strip().lower() in COVERAGE:
            covered |= set(first_column(body))
    return [c for c in components if c not in covered]


def scout_dir(root):
    """The `scoutDir` of the project's config, read with the project's copy of config.py (the only reader)."""
    config = os.path.join(root, '.claude', 'gw', 'scripts', 'config.py')
    if not os.path.isfile(config):
        sys.exit('scoutDir: %s not found; pass <architecture.md> explicitly, or apply the workflow: '
                 'python3 <workflow>/scripts/aplicar.py --update %s' % (config, root))
    r = subprocess.run([sys.executable, config, '--root', root, 'get', 'scoutDir'], capture_output=True, text=True)
    if r.returncode:
        sys.exit('scoutDir: could not read it (%s); fix the config: python3 %s validate' % (r.stderr.strip(), config))
    return r.stdout.strip()


def git(root, *args):
    r = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True)
    return r.returncode, r.stdout


def changed_files(root, commit, paths):
    """Seal paths changed since commit; None if git does not know the commit."""
    code, _ = git(root, 'cat-file', '-e', commit + '^{commit}')
    if code:
        return None
    # against the working tree: what is uncommitted counts too
    _, out = git(root, 'diff', '--name-only', '--relative', commit, '--', *paths)
    touched = set(out.split())
    touched |= {r for r in paths if not os.path.exists(os.path.join(root, r))}
    return sorted(touched)


def compare(arch_path, root):
    with open(arch_path, encoding='utf-8') as f:
        text = f.read()
    result = {'same': [], 'changed': [], 'unsealed': [], 'uncounted': []}
    sealed = set()
    for title, date, commit, paths in sections(text):
        sealed |= set(paths)
        if not commit:
            result['unsealed'].append({'section': title})
            continue
        if not paths:  # with no paths, git diff would compare the whole repository
            result['unsealed'].append({'section': title, 'reason': 'seal without files'})
            continue
        touched = changed_files(root, commit, paths)
        if touched is None:
            result['unsealed'].append({'section': title, 'reason': 'unknown commit %s' % commit})
        elif touched:
            result['changed'].append({'section': title, 'date': date, 'files': touched})
        else:
            result['same'].append({'section': title, 'date': date})
    folders = tuple(r.rstrip('/') + '/' for r in sealed)  # a seal with a folder covers its manifests
    result['uncounted'] = [m for m in inventory.inventory(root)['manifests']
                           if m not in sealed and not m.startswith(folders)]
    return result


def section(text, title):
    """Text of the `## ...` sections whose title contains `title` (case-insensitive); None if none."""
    parts = SECTION_RE.split(text)
    chunks = ['## %s\n\n%s' % (t, c.strip('\n') + '\n') for t, c in zip(parts[1::2], parts[2::2])
              if title.strip().lower() in t.lower()]
    return '\n'.join(chunks) or None


def default_root():
    """The project root, never the current directory: the project that holds this copy (it is installed in
    <root>/.claude/skills/scout-updates/scripts), else the git top level (from the plugin cache)."""
    here = os.path.dirname(os.path.abspath(__file__))
    parts = here.replace(os.sep, '/').rstrip('/').split('/')
    if parts[-4:] == ['.claude', 'skills', 'scout-updates', 'scripts']:
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(here))))
    r = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit('compare.py: not inside a git repository, so the project root is unknown; pass it: '
                 'python3 compare.py --root <project root>')
    return r.stdout.strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('architecture', nargs='?', help='default: <scoutDir>/architecture.md of the project config')
    ap.add_argument('--root', help='project root (default: the project holding this copy, else the git top level)')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--report', help='step-6 report: checks its coverage table')
    ap.add_argument('--section', help='print only the sections whose title contains this text')
    a = ap.parse_args(argv)
    if not a.root:
        a.root = default_root()
    if not a.architecture:
        a.architecture = os.path.join(a.root, scout_dir(a.root), 'architecture.md')
    if a.section:
        with open(a.architecture, encoding='utf-8') as f:
            text = f.read()
        chunk = section(text, a.section)
        if chunk is None:
            print('No section contains "%s". Sections: %s' % (a.section, ', '.join(SECTION_RE.findall(text))))
            return 1
        print(chunk, end='')
        return 0
    res = compare(a.architecture, a.root)
    if a.report:
        with open(a.architecture, encoding='utf-8') as f, open(a.report, encoding='utf-8') as g:
            res['uncovered'] = uncovered(f.read(), g.read())
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        for s in res['same']:
            print('same       %s (seal %s)' % (s['section'], s['date']))
        for s in res['changed']:
            print('changed    %s (seal %s): %s' % (s['section'], s['date'], ', '.join(s['files'])))
        for s in res['unsealed']:
            print('unsealed   %s%s' % (s['section'], ' (%s)' % s['reason'] if s.get('reason') else ''))
        for m in res['uncounted']:
            print('uncounted  %s' % m)
        for c in res.get('uncovered', []):
            print('uncovered  %s' % c)
    return 1 if res['changed'] or res['unsealed'] or res['uncounted'] or res.get('uncovered') else 0


if __name__ == '__main__':
    sys.exit(main())
