#!/usr/bin/env python3
"""Inventario estático de un proyecto para `scout-updates`. Solo biblioteca estándar.

Uso:
  inventario.py [<raíz>] [--ollama <url>] [--json]

Recorre los archivos versionados (`git ls-files`; sin git, todo salvo node_modules, .git y venv) y saca por
sección (las de formato-arquitectura.md):
  runtimes        .nvmrc, .node-version, .python-version, .tool-versions, package.json `engines`, go.mod `go`,
                  Dockerfile `FROM` (imagen y etiqueta)
  dependencias    package.json (dependencies/devDependencies), requirements*.txt, pyproject.toml, go.mod,
                  Cargo.toml; con su lockfile si lo hay
  infraestructura .github/workflows (`uses:` y `runs-on:`), docker-compose/compose (`image:`)
  modelos de IA   variables de .env.example/.env.sample y de código de config cuyo nombre lleva MODEL, Modelfile y
                  *.Modelfile `FROM`, agentes de código (opencode.json: `model` y `agent.*.model`; sus `plugin`, en
                  dependencias); con --ollama, los modelos instalados (/api/tags)
Cada componente lleva el archivo de donde sale (varios, separados por coma, si se repite). Se excluye .claude/. No resuelve versiones ni consulta la red (salvo --ollama).
"""
import argparse, json, os, re, subprocess, sys, urllib.request

IGNORAR = {'node_modules', '.git', 'venv', '.venv', 'dist', 'build', '__pycache__'}
LOCKS = {'package.json': ('package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'bun.lockb'),
         'pyproject.toml': ('poetry.lock', 'uv.lock', 'pdm.lock'), 'Cargo.toml': ('Cargo.lock',), 'go.mod': ('go.sum',)}
VERSION_FIJA = {'.nvmrc': 'node', '.node-version': 'node', '.python-version': 'python', '.ruby-version': 'ruby'}
EXCLUIR = ('.claude/',)  # skills y sus fixtures de evaluación: no son del proyecto
ENV_EJEMPLO = ('.env.example', '.env.sample', '.env.template', 'example.env')
RE_MODELO_ENV = re.compile(r'^\s*([A-Z0-9_]*MODEL[A-Z0-9_]*)\s*=\s*["\']?([^"\'\s#]+)', re.M)
RE_MODELO_CODIGO = re.compile(r'process\.env\.([A-Z0-9_]*MODEL[A-Z0-9_]*)\s*(?:\?\?|\|\|)\s*[\'"]([^\'"]+)[\'"]'
                              r'|os\.environ\.get\(\s*[\'"]([A-Z0-9_]*MODEL[A-Z0-9_]*)[\'"]\s*,\s*[\'"]([^\'"]+)[\'"]')
CONFIG_CODIGO = re.compile(r'(^|/)(config|settings|env)[^/]*\.(ts|js|mjs|py)$')


def archivos(raiz):
    try:
        salida = subprocess.run(['git', 'ls-files', '-co', '--exclude-standard'], cwd=raiz, capture_output=True,
                                text=True, check=True).stdout
        return sorted(l for l in salida.splitlines() if l and os.path.isfile(os.path.join(raiz, l)))
    except (subprocess.CalledProcessError, FileNotFoundError):
        todos = []
        for d, dirs, fs in os.walk(raiz):
            dirs[:] = [x for x in dirs if x not in IGNORAR]
            todos += [os.path.relpath(os.path.join(d, f), raiz).replace(os.sep, '/') for f in fs]
        return sorted(todos)


def leer(raiz, ruta):
    try:
        with open(os.path.join(raiz, ruta), encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return ''


def comp(nombre, version, origen, uso=None):
    c = {'nombre': nombre, 'version': version, 'origen': origen}
    if uso:
        c['uso'] = uso
    return c


def con_lock(ruta, lista):
    base = os.path.basename(ruta)
    carpeta = os.path.dirname(ruta)
    for lock in LOCKS.get(base, ()):
        if os.path.join(carpeta, lock).replace(os.sep, '/').lstrip('/') in lista:
            return lock
    return None


def fusionar(comps):
    """Un componente por (nombre, versión, uso); los orígenes repetidos se juntan con coma."""
    vistos = {}
    for c in comps:
        clave = (c['nombre'], c['version'], c.get('uso'))
        if clave in vistos:
            if c['origen'] not in vistos[clave]['origen'].split(', '):
                vistos[clave]['origen'] += ', ' + c['origen']
        else:
            vistos[clave] = dict(c)
    return list(vistos.values())


def inventariar(raiz, lista=None, excluir=EXCLUIR):
    lista = archivos(raiz) if lista is None else lista
    lista = [r for r in lista if not r.startswith(tuple(excluir))]
    conjunto = set(lista)
    inv = {'runtimes': [], 'dependencias': [], 'infraestructura': [], 'modelos de IA': [], 'manifiestos': []}

    def manifiesto(ruta):
        inv['manifiestos'].append(ruta)

    for ruta in lista:
        base = os.path.basename(ruta)
        texto = None
        if base in VERSION_FIJA:
            manifiesto(ruta)
            inv['runtimes'].append(comp(VERSION_FIJA[base], leer(raiz, ruta).strip(), ruta))
        elif base == '.tool-versions':
            manifiesto(ruta)
            for l in leer(raiz, ruta).splitlines():
                partes = l.split()
                if len(partes) >= 2 and not partes[0].startswith('#'):
                    inv['runtimes'].append(comp(partes[0], partes[1], ruta))
        elif base == 'package.json':
            manifiesto(ruta)
            try:
                pkg = json.loads(leer(raiz, ruta))
            except ValueError:
                pkg = {}
            for motor, v in (pkg.get('engines') or {}).items():
                inv['runtimes'].append(comp(motor, v, ruta))
            for campo in ('dependencies', 'devDependencies'):
                for n, v in (pkg.get(campo) or {}).items():
                    inv['dependencias'].append(comp(n, v, ruta, 'dev' if campo == 'devDependencies' else None))
        elif re.match(r'requirements[^/]*\.txt$', base):
            manifiesto(ruta)
            for l in leer(raiz, ruta).splitlines():
                m = re.match(r'\s*([A-Za-z0-9_.\-]+(?:\[[^\]]*\])?)\s*([=<>~!]=?\s*[^\s;#]+)?', l)
                if m and not l.strip().startswith(('#', '-')):
                    inv['dependencias'].append(comp(m.group(1), (m.group(2) or '').replace(' ', '') or '*', ruta))
        elif base == 'pyproject.toml':
            manifiesto(ruta)
            texto = leer(raiz, ruta)
            m = re.search(r'requires-python\s*=\s*["\']([^"\']+)', texto)
            if m:
                inv['runtimes'].append(comp('python', m.group(1), ruta))
            # los corchetes de los extras (`pkg[extra]`) van entre comillas: no cierran la lista
            bloque = re.search(r'^dependencies\s*=\s*\[((?:"[^"]*"|\'[^\']*\'|[^\]"\'])*)\]', texto, re.M)
            for d in re.findall(r'["\']([^"\']+)["\']', bloque.group(1) if bloque else ''):
                m = re.match(r'\s*([A-Za-z0-9_.\-]+(?:\[[^\]]*\])?)\s*(.*)', d)
                if m:
                    inv['dependencias'].append(comp(m.group(1), m.group(2).strip() or '*', ruta))
        elif base == 'go.mod':
            manifiesto(ruta)
            texto = leer(raiz, ruta)
            m = re.search(r'^go\s+(\S+)', texto, re.M)
            if m:
                inv['runtimes'].append(comp('go', m.group(1), ruta))
            for n, v in re.findall(r'^\s*(?:require\s+)?([\w.\-]+\.[\w.\-/]+)\s+(v\S+)', texto, re.M):
                inv['dependencias'].append(comp(n, v, ruta))
        elif base == 'Cargo.toml':
            manifiesto(ruta)
            texto = leer(raiz, ruta)
            bloque = re.search(r'^\[dependencies\](.*?)(^\[|\Z)', texto, re.S | re.M)
            for n, v, vt in re.findall(r'^([\w\-]+)\s*=\s*(?:"([^"]+)"|\{(?:[^}]*?\bversion\s*=\s*"([^"]+)")?)', bloque.group(1) if bloque else '', re.M):
                inv['dependencias'].append(comp(n, v or vt or '*', ruta))
        elif base.startswith('Dockerfile') or base.endswith('.Dockerfile') or base.startswith('Containerfile'):
            manifiesto(ruta)
            texto = leer(raiz, ruta)
            etapas = {e.lower() for e in re.findall(r'^\s*FROM\s+.*?\s+AS\s+(\S+)', texto, re.M | re.I)}
            for img in re.findall(r'^\s*FROM\s+(?:--\S+\s+)*(\S+)', texto, re.M | re.I):
                if img.lower() not in etapas:  # `FROM build`: una etapa anterior, no una imagen
                    inv['runtimes'].append(comp(*imagen(img), ruta, 'imagen base'))
        elif re.match(r'(docker-)?compose[^/]*\.ya?ml$', base):
            manifiesto(ruta)
            for img in re.findall(r'^\s*image:\s*["\']?([^\s"\']+)', leer(raiz, ruta), re.M):
                inv['infraestructura'].append(comp(*imagen(img), ruta, 'servicio'))
        elif re.match(r'\.github/workflows/[^/]+\.ya?ml$', ruta):
            manifiesto(ruta)
            texto = leer(raiz, ruta)
            for accion in sorted(set(re.findall(r'uses:\s*["\']?([^\s"\'#]+)', texto))):
                n, _, v = accion.partition('@')
                inv['infraestructura'].append(comp(n, v or '-', ruta, 'acción de CI'))
            for lenguaje, v in sorted(set(re.findall(r'(node|python|go|java|dotnet)-version:\s*["\']?([^\s"\'#,}]+)', texto))):
                inv['runtimes'].append(comp(lenguaje, v, ruta, 'CI'))
            for runner in sorted(set(re.findall(r'runs-on:\s*["\']?([^\s"\'#]+)', texto))):
                inv['infraestructura'].append(comp('runner', runner, ruta, 'CI'))
        elif base in ENV_EJEMPLO:
            manifiesto(ruta)
            for var, valor in RE_MODELO_ENV.findall(leer(raiz, ruta)):
                inv['modelos de IA'].append(comp(valor, '-', ruta, var))
        elif base in ('opencode.json', 'opencode.jsonc'):
            manifiesto(ruta)
            try:
                cfg = json.loads(re.sub(r'^\s*//.*$', '', leer(raiz, ruta), flags=re.M))
            except ValueError:
                cfg = {}
            if cfg.get('model'):
                inv['modelos de IA'].append(comp(cfg['model'], '-', ruta, 'agente de código'))
            for nombre, agente in (cfg.get('agent') or {}).items():
                if isinstance(agente, dict) and agente.get('model'):
                    inv['modelos de IA'].append(comp(agente['model'], '-', ruta, f'agente {nombre}'))
            for plugin in cfg.get('plugin') or []:
                n, _, v = plugin.rpartition('@') if plugin.rfind('@') > 0 else (plugin, '', '')
                inv['dependencias'].append(comp(n, v or '-', ruta, 'plugin del agente'))
        elif base.startswith('Modelfile') or base.endswith('.Modelfile'):
            manifiesto(ruta)
            m = re.search(r'^\s*FROM\s+(\S+)', leer(raiz, ruta), re.M | re.I)
            if m:
                inv['modelos de IA'].append(comp(m.group(1), '-', ruta, 'base del Modelfile'))
        elif CONFIG_CODIGO.search(ruta) and 'test' not in ruta:
            for m in RE_MODELO_CODIGO.finditer(leer(raiz, ruta)):
                var, valor = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
                inv['modelos de IA'].append(comp(valor, '-', ruta, var))
        lock = con_lock(ruta, conjunto)
        if lock:
            for c in inv['dependencias']:
                if c['origen'] == ruta:
                    c['lock'] = lock
    for seccion in ('runtimes', 'dependencias', 'infraestructura', 'modelos de IA'):
        inv[seccion] = fusionar(inv[seccion])
    return inv


def imagen(ref):
    """(nombre, etiqueta) de una imagen: sin el digest; el `:` de un registro con puerto no es la etiqueta."""
    ref = ref.split('@')[0]
    nombre, _, etiqueta = ref.rpartition(':') if ':' in ref.rsplit('/', 1)[-1] else (ref, '', '')
    return nombre, etiqueta or 'latest'


def modelos_ollama(url):
    """Modelos instalados en un motor Ollama (/api/tags). None si no responde."""
    try:
        with urllib.request.urlopen(url.rstrip('/') + '/api/tags', timeout=5) as r:
            datos = json.load(r)
    except (OSError, ValueError):
        return None
    return [comp(m.get('name'), (m.get('details') or {}).get('quantization_level', '-'), url,
                 '%s, %.1f GB' % ((m.get('details') or {}).get('parameter_size', '?'), (m.get('size') or 0) / 1e9))
            for m in datos.get('models', [])]


def a_texto(inv):
    lineas = []
    for seccion, comps in inv.items():
        if seccion == 'manifiestos':
            continue
        lineas.append('## %s (%d)' % (seccion, len(comps)))
        for c in comps:
            lineas.append('- %s %s · %s%s' % (c['nombre'], c['version'], c['origen'],
                                              ' · ' + c['uso'] if c.get('uso') else ''))
    lineas.append('## manifiestos (%d)' % len(inv['manifiestos']))
    lineas += ['- ' + m for m in inv['manifiestos']]
    return '\n'.join(lineas)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('raiz', nargs='?', default='.')
    ap.add_argument('--ollama', help='URL del motor Ollama (p. ej. http://localhost:11434)')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    inv = inventariar(a.raiz)
    if a.ollama:
        instalados = modelos_ollama(a.ollama)
        if instalados is None:
            print('aviso: %s no responde; sin modelos instalados' % a.ollama, file=sys.stderr)
        else:
            inv['modelos instalados'] = instalados
    print(json.dumps(inv, ensure_ascii=False, indent=1) if a.json else a_texto(inv))


if __name__ == '__main__':
    main()
