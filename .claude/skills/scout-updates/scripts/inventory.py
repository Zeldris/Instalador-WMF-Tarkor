#!/usr/bin/env python3
"""Static inventory of a project for `scout-updates`. Python 3 standard library only.

Usage:
  inventory.py [<root>] [--ollama <url>] [--json]

Walks the versioned files (`git ls-files`; without git, everything except node_modules, .git and venvs) and reports,
per section (those of references/formats.md):
  runtimes         .nvmrc, .node-version, .python-version, .tool-versions, package.json `engines`, go.mod `go`,
                   pyproject `requires-python`, Dockerfile `FROM` (image and tag), CI `<language>-version`
  dependencies     package.json (dependencies/devDependencies), requirements*.txt, pyproject.toml, go.mod,
                   Cargo.toml; with the lockfile if there is one
  infrastructure   .github/workflows (`uses:` and `runs-on:`), docker-compose/compose (`image:`)
  ai models        variables of .env.example/.env.sample and of config code whose name has MODEL, Modelfile and
                   *.Modelfile `FROM`, code agents (opencode.json: `model` and `agent.*.model`; their `plugin`
                   goes under dependencies); with --ollama, the installed models (/api/tags)
Every component carries the file it comes from (several, comma separated, if repeated). `.claude/` is excluded.
It resolves no versions and queries no network (except --ollama).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request

IGNORE = {'node_modules', '.git', 'venv', '.venv', 'dist', 'build', '__pycache__'}
LOCKS = {'package.json': ('package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'bun.lockb'),
         'pyproject.toml': ('poetry.lock', 'uv.lock', 'pdm.lock'), 'Cargo.toml': ('Cargo.lock',), 'go.mod': ('go.sum',)}
PINNED_VERSION = {'.nvmrc': 'node', '.node-version': 'node', '.python-version': 'python', '.ruby-version': 'ruby'}
EXCLUDE = ('.claude/',)  # skills and their fixtures: not the project's own
ENV_EXAMPLE = ('.env.example', '.env.sample', '.env.template', 'example.env')
MODEL_ENV_RE = re.compile(r'^\s*([A-Z0-9_]*MODEL[A-Z0-9_]*)\s*=\s*["\']?([^"\'\s#]+)', re.M)
MODEL_CODE_RE = re.compile(r'process\.env\.([A-Z0-9_]*MODEL[A-Z0-9_]*)\s*(?:\?\?|\|\|)\s*[\'"]([^\'"]+)[\'"]'
                           r'|os\.environ\.get\(\s*[\'"]([A-Z0-9_]*MODEL[A-Z0-9_]*)[\'"]\s*,\s*[\'"]([^\'"]+)[\'"]')
CONFIG_CODE = re.compile(r'(^|/)(config|settings|env)[^/]*\.(ts|js|mjs|py)$')
SECTIONS = ('runtimes', 'dependencies', 'infrastructure', 'ai models')


def list_files(root):
    try:
        out = subprocess.run(['git', 'ls-files', '-co', '--exclude-standard'], cwd=root, capture_output=True,
                             text=True, check=True).stdout
        return sorted(l for l in out.splitlines() if l and os.path.isfile(os.path.join(root, l)))
    except (subprocess.CalledProcessError, FileNotFoundError):
        found = []
        for d, dirs, fs in os.walk(root):
            dirs[:] = [x for x in dirs if x not in IGNORE]
            found += [os.path.relpath(os.path.join(d, f), root).replace(os.sep, '/') for f in fs]
        return sorted(found)


def read(root, path):
    try:
        with open(os.path.join(root, path), encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return ''


def comp(name, version, origin, use=None):
    c = {'name': name, 'version': version, 'origin': origin}
    if use:
        c['use'] = use
    return c


def lock_of(path, files):
    base = os.path.basename(path)
    folder = os.path.dirname(path)
    for lock in LOCKS.get(base, ()):
        if os.path.join(folder, lock).replace(os.sep, '/').lstrip('/') in files:
            return lock
    return None


def merge(comps):
    """One component per (name, version, use); repeated origins are joined with a comma."""
    seen = {}
    for c in comps:
        key = (c['name'], c['version'], c.get('use'))
        if key in seen:
            if c['origin'] not in seen[key]['origin'].split(', '):
                seen[key]['origin'] += ', ' + c['origin']
        else:
            seen[key] = dict(c)
    return list(seen.values())


def image(ref):
    """(name, tag) of an image: without the digest; the `:` of a registry with a port is not the tag."""
    ref = ref.split('@')[0]
    name, _, tag = ref.rpartition(':') if ':' in ref.rsplit('/', 1)[-1] else (ref, '', '')
    return name, tag or 'latest'


def inventory(root, files=None, exclude=EXCLUDE):
    files = list_files(root) if files is None else files
    files = [r for r in files if not r.startswith(tuple(exclude))]
    fileset = set(files)
    inv = {s: [] for s in SECTIONS}
    inv['manifests'] = []

    for path in files:
        base = os.path.basename(path)
        if base in PINNED_VERSION:
            inv['manifests'].append(path)
            inv['runtimes'].append(comp(PINNED_VERSION[base], read(root, path).strip(), path))
        elif base == '.tool-versions':
            inv['manifests'].append(path)
            for l in read(root, path).splitlines():
                parts = l.split()
                if len(parts) >= 2 and not parts[0].startswith('#'):
                    inv['runtimes'].append(comp(parts[0], parts[1], path))
        elif base == 'package.json':
            inv['manifests'].append(path)
            try:
                pkg = json.loads(read(root, path))
            except ValueError:
                pkg = {}
            for engine, v in (pkg.get('engines') or {}).items():
                inv['runtimes'].append(comp(engine, v, path))
            for field in ('dependencies', 'devDependencies'):
                for n, v in (pkg.get(field) or {}).items():
                    inv['dependencies'].append(comp(n, v, path, 'dev' if field == 'devDependencies' else None))
        elif re.match(r'requirements[^/]*\.txt$', base):
            inv['manifests'].append(path)
            for l in read(root, path).splitlines():
                m = re.match(r'\s*([A-Za-z0-9_.\-]+(?:\[[^\]]*\])?)\s*([=<>~!]=?\s*[^\s;#]+)?', l)
                if m and not l.strip().startswith(('#', '-')):
                    inv['dependencies'].append(comp(m.group(1), (m.group(2) or '').replace(' ', '') or '*', path))
        elif base == 'pyproject.toml':
            inv['manifests'].append(path)
            text = read(root, path)
            m = re.search(r'requires-python\s*=\s*["\']([^"\']+)', text)
            if m:
                inv['runtimes'].append(comp('python', m.group(1), path))
            # the brackets of extras (`pkg[extra]`) sit inside quotes: they do not close the list
            block = re.search(r'^dependencies\s*=\s*\[((?:"[^"]*"|\'[^\']*\'|[^\]"\'])*)\]', text, re.M)
            for d in re.findall(r'["\']([^"\']+)["\']', block.group(1) if block else ''):
                m = re.match(r'\s*([A-Za-z0-9_.\-]+(?:\[[^\]]*\])?)\s*(.*)', d)
                if m:
                    inv['dependencies'].append(comp(m.group(1), m.group(2).strip() or '*', path))
        elif base == 'go.mod':
            inv['manifests'].append(path)
            text = read(root, path)
            m = re.search(r'^go\s+(\S+)', text, re.M)
            if m:
                inv['runtimes'].append(comp('go', m.group(1), path))
            for n, v in re.findall(r'^\s*(?:require\s+)?([\w.\-]+\.[\w.\-/]+)\s+(v\S+)', text, re.M):
                inv['dependencies'].append(comp(n, v, path))
        elif base == 'Cargo.toml':
            inv['manifests'].append(path)
            text = read(root, path)
            block = re.search(r'^\[dependencies\](.*?)(^\[|\Z)', text, re.S | re.M)
            for n, v, vt in re.findall(r'^([\w\-]+)\s*=\s*(?:"([^"]+)"|\{(?:[^}]*?\bversion\s*=\s*"([^"]+)")?)',
                                       block.group(1) if block else '', re.M):
                inv['dependencies'].append(comp(n, v or vt or '*', path))
        elif base.startswith('Dockerfile') or base.endswith('.Dockerfile') or base.startswith('Containerfile'):
            inv['manifests'].append(path)
            text = read(root, path)
            stages = {e.lower() for e in re.findall(r'^\s*FROM\s+.*?\s+AS\s+(\S+)', text, re.M | re.I)}
            for img in re.findall(r'^\s*FROM\s+(?:--\S+\s+)*(\S+)', text, re.M | re.I):
                if img.lower() not in stages:  # `FROM build`: an earlier stage, not an image
                    inv['runtimes'].append(comp(*image(img), path, 'base image'))
        elif re.match(r'(docker-)?compose[^/]*\.ya?ml$', base):
            inv['manifests'].append(path)
            for img in re.findall(r'^\s*image:\s*["\']?([^\s"\']+)', read(root, path), re.M):
                inv['infrastructure'].append(comp(*image(img), path, 'service'))
        elif re.match(r'\.github/workflows/[^/]+\.ya?ml$', path):
            inv['manifests'].append(path)
            text = read(root, path)
            for action in sorted(set(re.findall(r'uses:\s*["\']?([^\s"\'#]+)', text))):
                n, _, v = action.partition('@')
                inv['infrastructure'].append(comp(n, v or '-', path, 'CI action'))
            for language, v in sorted(set(re.findall(r'(node|python|go|java|dotnet)-version:\s*["\']?([^\s"\'#,}]+)', text))):
                inv['runtimes'].append(comp(language, v, path, 'CI'))
            for runner in sorted(set(re.findall(r'runs-on:\s*["\']?([^\s"\'#]+)', text))):
                inv['infrastructure'].append(comp('runner', runner, path, 'CI'))
        elif base in ENV_EXAMPLE:
            inv['manifests'].append(path)
            for var, value in MODEL_ENV_RE.findall(read(root, path)):
                inv['ai models'].append(comp(value, '-', path, var))
        elif base in ('opencode.json', 'opencode.jsonc'):
            inv['manifests'].append(path)
            try:
                cfg = json.loads(re.sub(r'^\s*//.*$', '', read(root, path), flags=re.M))
            except ValueError:
                cfg = {}
            if cfg.get('model'):
                inv['ai models'].append(comp(cfg['model'], '-', path, 'code agent'))
            for name, agent in (cfg.get('agent') or {}).items():
                if isinstance(agent, dict) and agent.get('model'):
                    inv['ai models'].append(comp(agent['model'], '-', path, f'agent {name}'))
            for plugin in cfg.get('plugin') or []:
                n, _, v = plugin.rpartition('@') if plugin.rfind('@') > 0 else (plugin, '', '')
                inv['dependencies'].append(comp(n, v or '-', path, 'agent plugin'))
        elif base.startswith('Modelfile') or base.endswith('.Modelfile'):
            inv['manifests'].append(path)
            m = re.search(r'^\s*FROM\s+(\S+)', read(root, path), re.M | re.I)
            if m:
                inv['ai models'].append(comp(m.group(1), '-', path, 'Modelfile base'))
        elif CONFIG_CODE.search(path) and 'test' not in path:
            for m in MODEL_CODE_RE.finditer(read(root, path)):
                var, value = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
                inv['ai models'].append(comp(value, '-', path, var))
        lock = lock_of(path, fileset)
        if lock:
            for c in inv['dependencies']:
                if c['origin'] == path:
                    c['lock'] = lock
    for section in SECTIONS:
        inv[section] = merge(inv[section])
    return inv


def ollama_models(url):
    """Models installed in an Ollama engine (/api/tags). None if it does not answer."""
    try:
        with urllib.request.urlopen(url.rstrip('/') + '/api/tags', timeout=5) as r:
            data = json.load(r)
    except (OSError, ValueError):
        return None
    return [comp(m.get('name'), (m.get('details') or {}).get('quantization_level', '-'), url,
                 '%s, %.1f GB' % ((m.get('details') or {}).get('parameter_size', '?'), (m.get('size') or 0) / 1e9))
            for m in data.get('models', [])]


def as_text(inv):
    lines = []
    for section, comps in inv.items():
        if section == 'manifests':
            continue
        lines.append('## %s (%d)' % (section, len(comps)))
        for c in comps:
            lines.append('- %s %s | %s%s' % (c['name'], c['version'], c['origin'],
                                             ' | ' + c['use'] if c.get('use') else ''))
    lines.append('## manifests (%d)' % len(inv['manifests']))
    lines += ['- ' + m for m in inv['manifests']]
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('root', nargs='?', default='.', help='project root (default: current directory)')
    ap.add_argument('--ollama', help='URL of an Ollama engine (e.g. http://localhost:11434)')
    ap.add_argument('--json', action='store_true', help='print JSON instead of text')
    a = ap.parse_args(argv)
    inv = inventory(a.root)
    if a.ollama:
        installed = ollama_models(a.ollama)
        if installed is None:
            print('warning: %s does not answer; no installed models' % a.ollama, file=sys.stderr)
        else:
            inv['installed models'] = installed
    print(json.dumps(inv, ensure_ascii=False, indent=1) if a.json else as_text(inv))


if __name__ == '__main__':
    main()
