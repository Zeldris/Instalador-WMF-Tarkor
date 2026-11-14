#!/usr/bin/env python3
# galivelop-workflow v0.6.0
"""The agent map must not point at anything that no longer exists (a check for CI and `check`).

The map (default docs/agent-map.md; config `agentMap.path`) says where each contract lives and what implements it.
An agent trusts it, so a stale row is worse than no map. This script reads every path the map cites:

  `path`          backtick token that is a path of the repo: the file or folder exists (a glob, `*` or `?`, must
                  match at least one);
  `path#name`     and the file defines `name` (function, class, constant, type, shell function, JSON key...);
  `otherName`     a camelCase name after a `path#name` in the same row or bullet occurs in that file (a call or a
                  field is enough: the map names a section by what it calls);
  [text](path)    a Markdown link whose target is not a URL or an anchor: the file or folder exists. `#fragment` and
                  `?query` are dropped (md-links.py checks heading anchors).

A path resolves from the repo root or from the map's own folder (links try the map's folder first). A backtick token
counts as a path when it has a `/` and its first folder exists at the root, or it is a configured prefix or root
(`agentMap.prefixes` maps a short prefix to a real folder: {"b/": "backend/src/"}; `agentMap.roots` lists top folders
that count even when they no longer exist), or it ends with `/`, or its last part has a file extension. Anything else
(`and/or`, `gw.json`, `skills/<name>/x.md`, a domain name, text in a code fence) is just words and is not looked up.
A table row, a list item and a paragraph are one unit each; a message carries the line where the unit starts.

  python3 agent-map.py [--root PATH]

Exit 0 if every reference exists, or if the project has no map at the default path (it says so); 1 if some reference
is broken, or if `agentMap.path` names a file that is not there; 2 if the config is invalid (fails closed).
Python 3.8+, stdlib only. Root and config through config.py.
"""
import argparse
import glob as globber
import os
import posixpath
import re
import sys
import urllib.parse
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as gwconfig  # noqa: E402

DEFAULT_MAP = "docs/agent-map.md"
OLD_DEFAULT_MAP = "docs/mapa-agente.md"  # A8 (0.x): read, with a warning, when it is the only one that exists
LINK = re.compile(r'!?\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
TICKS = re.compile(r'`([^`\n]+)`')
TOKEN = re.compile(r'^([\w.@+%\-/*?]+?)(?::\d+(?:-\d+)?)?(?:#(\S+))?$')
LOOSE = re.compile(r'^[a-z]+[A-Z]\w*$')
IDENT = re.compile(r'^[A-Za-z_]\w*$')
LINE_ANCHOR = re.compile(r'^L\d+')  # GitHub's #L10, not a name
EXTENSION = re.compile(r'\.[A-Za-z][A-Za-z0-9]{0,5}$')
DOMAIN = re.compile(r'^[\w\-]+(\.[\w\-]+)+$')
SCHEME = re.compile(r'^(?:[A-Za-z][A-Za-z0-9+.\-]*:|//)')
PLACEHOLDER = re.compile(r'[<>{}$~|\\]|\.\.\.|…')
UNIT_START = re.compile(r'^(?:[-*+] |\d+[.)] |#|\|)')
FENCE = re.compile(r'^\s*(```|~~~)')
MARKDOWN = ('.md', '.markdown', '.mdx', '.html')


def units(text):
    """(line number, text) of each unit: a table row, a list item, a heading or a paragraph (continuation lines are
    joined). Code fences are skipped."""
    current, start, in_fence = [], 0, False
    for number, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            if current:
                yield start, ' '.join(current)
            current, start = [], 0
            continue
        if in_fence:
            continue
        if not line.strip():
            if current:
                yield start, ' '.join(current)
            current, start = [], 0
        elif UNIT_START.match(line):
            if current:
                yield start, ' '.join(current)
            current, start = [line.strip()], number
        else:
            start = start or number
            current.append(line.strip())
    if current:
        yield start, ' '.join(current)


# Files whose methods are written `[modifiers] ReturnType name(...) [throws X] {` (return type BEFORE the name).
# (not C or C++: their return types, `char *dup(`, `std::string name(`, `void Foo::bar(`, `const T& get() const`, do not fit)
TYPED_METHOD_SUFFIXES = ('.java', '.kt', '.kts', '.cs', '.scala', '.groovy')
CONTROL = {'if', 'else', 'for', 'while', 'do', 'switch', 'catch', 'try', 'return', 'throw', 'new', 'case',
           'synchronized', 'using', 'lock', 'foreach', 'when', 'yield', 'await'}
# `<...>` with up to three levels of nesting (`Map<String, List<X>>`, `<?>`)
GENERIC = r'<(?:[^<>\n]|<(?:[^<>\n]|<[^<>\n]*>)*>)*>'
METHOD_MODIFIERS = (r'(?:public|private|protected|internal|static|final|abstract|synchronized|native|default|virtual'
                    r'|override|sealed|async|extern|unsafe|partial|open|inline|suspend|strictfp|transient)')
# a return type: `void`, `a.b.C`, `List<String>`, `Map<K, List<V>>[]`, `int[][]`, `String?`
RETURN_TYPE = (rf'(?!(?:{"|".join(sorted(CONTROL))})\b)[\w.]+(?:{GENERIC})?(?:\s*\[\s*\])*\??')
# a parameter list: it cannot cross `;`, `{` or `}`, and its parentheses balance (one level of nesting: `@Size(max = 1)`)
PARAMS = r'\((?:[^;{}()]|\([^;{}()]*\))*\)'


def defines(text, name, suffix):
    """True when `text` (a file with extension `suffix`) declares `name`, not merely calls it."""
    n = re.escape(name)
    patterns = [
        rf'\b(?:function\*?|def|const|let|var|class|interface|type|enum|model|struct|fn|func|trait|object|record'
        rf'|namespace|module)\s+{n}\b',
        # a top-level assignment: Python or shell variable, TypeScript `export` constant
        rf'^(?:export\s+)?{n}\s*(?::[^=\n]+)?=(?!=)',
        # a method (with or without modifiers): its parentheses are followed by `{`, not `;` like a call
        rf'^\s*(?:(?:public|private|protected|static|async|override|readonly)\s+)*{n}\s*(?:<[^>]*>)?\([^;]*?\)\s*'
        rf'(?::[^;{{=]*)?\{{',
    ]
    if suffix in TYPED_METHOD_SUFFIXES and name in CONTROL:
        # there `if (x) {` and `catch (E e) {` are not definitions of `if` and `catch`; a method named `lock` still
        # has its return type (typed form below). In JS, TS or Python a method may be named `lock`, `when`, `catch`.
        patterns.pop()
    if suffix in TYPED_METHOD_SUFFIXES:
        # a method with a return type: `[@Annotation] [modifiers] [<T>] Type name(...) [throws X, Y] {`; a call, a
        # `return name(x);` or `new Name() {` (anonymous class) is not one: the type cannot be a control keyword
        patterns.append(
            rf'^[ \t]*(?:@\w[\w.]*(?:\([^)\n]*\))?\s+)*(?:{METHOD_MODIFIERS}\s+)*(?:{GENERIC}\s+)?'
            rf'{RETURN_TYPE}[ \t]+{n}\s*{PARAMS}\s*(?:throws\s+[\w.,\s]+?)?\s*\{{')
    if suffix in ('.sh', '.bash', '.zsh'):
        patterns.append(rf'^\s*(?:function\s+)?{n}\s*\(\s*\)')
    if suffix == '.json':
        patterns.append(rf'"{n}"\s*:')
    return any(re.search(p, text, re.M) for p in patterns)


class Checker:
    def __init__(self, root, map_rel, prefixes, roots):
        self.root = Path(root)
        self.map_rel = map_rel
        self.map_dir = posixpath.dirname(map_rel)
        self.prefixes = prefixes
        self.roots = roots
        self.broken = []
        self.total = 0
        self._texts = {}

    def text_of(self, rel):
        if rel not in self._texts:
            try:
                self._texts[rel] = (self.root / rel).read_text(encoding='utf-8', errors='replace')
            except OSError:
                self._texts[rel] = ''
        return self._texts[rel]

    def report(self, line, message):
        self.broken.append(f'{self.map_rel}:{line}: {message}')

    def locate(self, path, bases):
        """(files, folders, escaped): what `path` matches from each base folder (repo-relative), first base that
        matches wins; `escaped` is True when every base resolved outside the repo."""
        escaped = True
        for base in bases:
            rel = posixpath.normpath(posixpath.join(base, path)) if base else posixpath.normpath(path)
            if rel == '..' or rel.startswith('../'):
                continue
            escaped = False
            found = sorted(globber.glob(str(self.root / rel), recursive=True)) if re.search(r'[*?]', rel) \
                else ([str(self.root / rel)] if (self.root / rel).exists() else [])
            if found:
                relative = [os.path.relpath(f, self.root).replace(os.sep, '/') for f in found]
                files = [r for r in relative if (self.root / r).is_file()]
                return files, relative, False, rel
        return [], [], escaped, None

    def is_path(self, path, prefixed):
        if '/' not in path.strip('/') and not path.endswith('/'):
            return False
        first = path.split('/', 1)[0]
        if first in ('', '.'):
            return False
        if prefixed or first in self.roots or (self.root / first).exists() or first == '..':
            return True
        if DOMAIN.match(first):
            return False
        return path.endswith('/') or bool(EXTENSION.search(path.rstrip('/').rsplit('/', 1)[-1]))

    def expand(self, path):
        first, slash, rest = path.partition('/')
        if slash and first in self.prefixes:
            return self.prefixes[first] + rest, True
        return path, False

    def check_link(self, line, target):
        target = target.strip('<>')
        if not target or SCHEME.match(target) or target.startswith('#') or PLACEHOLDER.search(target):
            return
        target = urllib.parse.unquote(re.split(r'[?#]', target, maxsplit=1)[0])
        if not target:
            return
        self.total += 1
        if target.startswith('/'):
            bases, shown = [''], target.lstrip('/')
        else:
            bases, shown = [self.map_dir, ''], target
        _, found, escaped, _ = self.locate(shown, bases)
        if not found:
            if escaped:
                self.report(line, f'link leaves the repository: {target} (fix the link)')
            else:
                self.report(line, f'path not found: {target} (fix the link, or restore the file)')

    def check_token(self, line, token, loose):
        """Check one backtick token. Returns the files a later loose name is looked up in (None for none)."""
        if PLACEHOLDER.search(token):
            return None
        if LOOSE.match(token):
            if loose:
                self.total += 1
                if not any(re.search(rf'\b{re.escape(token)}\b', self.text_of(f)) for f in loose[1]):
                    self.report(line, f'{loose[0]} does not define {token} (rename it in the map, or restore it)')
            return loose
        m = TOKEN.match(token)
        if not m:
            return None
        path, frag = m.group(1), m.group(2)
        if path.startswith('/'):
            return None
        if path.startswith('./'):
            path = path[2:]
        path, prefixed = self.expand(path)
        if not self.is_path(path, prefixed):
            return None
        self.total += 1
        files, found, escaped, rel = self.locate(path, ['', self.map_dir] if self.map_dir else [''])
        if not found:
            if re.search(r'[*?]', path):
                self.report(line, f'no file matches {path} (fix the glob, or restore the files)')
            elif escaped:
                self.report(line, f'link leaves the repository: {path} (fix the reference)')
            else:
                self.report(line, f'path not found: {path} (fix the row, or restore the file)')
            return None
        if frag and IDENT.match(frag) and not LINE_ANCHOR.match(frag) and not path.lower().endswith(MARKDOWN):
            if not files:
                self.report(line, f'{path} is a folder, so it cannot define {frag} (cite a file: path#{frag})')
            elif not any(defines(self.text_of(f), frag, posixpath.splitext(f)[1]) for f in files):
                self.report(line, f'{files[0] if len(files) == 1 else path} does not define {frag} '
                                  f'(rename it in the map, or restore it)')
            return None if re.search(r'[*?]', path) else (files[0] if len(files) == 1 else path, files)
        return None

    def check_text(self, text):
        for line, unit in units(text):
            for link in LINK.finditer(unit):
                self.check_link(line, link.group(1))
            loose = None
            for tick in TICKS.finditer(LINK.sub(' ', unit)):
                loose = self.check_token(line, tick.group(1).strip(), loose)


def run(root, cfg):
    agent_map = cfg.get('agentMap') or {}
    declared = agent_map.get('path')
    map_rel = posixpath.normpath(declared or DEFAULT_MAP)
    map_file = Path(root) / map_rel
    if not declared and not map_file.is_file() and (Path(root) / OLD_DEFAULT_MAP).is_file():
        print(f'agent-map: warning: {OLD_DEFAULT_MAP} is the old name of the default agent map and will stop being '
              f'read in 1.0; rename it: git mv {OLD_DEFAULT_MAP} {DEFAULT_MAP}', file=sys.stderr)
        map_rel = OLD_DEFAULT_MAP
        map_file = Path(root) / map_rel
    if not map_file.is_file():
        if declared:
            print(f'agent-map: agentMap.path points to {map_rel}, which does not exist; create it, or fix '
                  f'agentMap.path in .claude/gw.json (or remove the key)')
            return 1
        print(f'agent-map: no agent map at {map_rel}; nothing to check (declare agentMap.path in '
              f'.claude/gw.json if the map lives elsewhere)')
        return 0
    prefixes = {}
    for short, real in (agent_map.get('prefixes') or {}).items():
        folder = posixpath.normpath(real) + '/'
        prefixes[short.rstrip('/')] = folder
    roots = {r.strip('/') for r in agent_map.get('roots') or []}
    checker = Checker(root, map_rel, prefixes, roots)
    checker.check_text(map_file.read_text(encoding='utf-8', errors='replace'))
    for message in checker.broken:
        print(message)
    print(f'{map_rel}: {len(checker.broken)} broken references out of {checker.total} checked')
    return 1 if checker.broken else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', help='project path (default: the git top level, see config.py)')
    args = parser.parse_args(argv)
    try:
        cfg = gwconfig.load(args.root)
    except gwconfig.ConfigError as exc:
        print(f'agent-map: gw config: {exc}', file=sys.stderr)
        return 2
    return run(cfg['_root'], cfg)


if __name__ == '__main__':
    sys.exit(main())
