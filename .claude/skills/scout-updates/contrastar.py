#!/usr/bin/env python3
"""Contrasta `arquitectura.md` con el proyecto para `scout-updates`. Solo biblioteca estándar.

Uso:
  contrastar.py <arquitectura.md> [--raiz <raíz>] [--json] [--informe <informe.md>]
  contrastar.py <arquitectura.md> --seccion <título>   imprime solo esa sección (para releerla sin leer el archivo)

Por cada sección `## ...` con sello `<!-- sello: AAAA-MM-DD · <commit> · ruta, ruta -->` (formato-arquitectura.md):
  igual       ningún archivo del sello cambió desde su commit (`git diff --name-only <commit>`, sin commitear incluido): basta con
              poner la fecha de hoy
  cambiada    alguno cambió o desapareció: se relee esa sección (lista los archivos)
  sin sello   sección sin sello, o con un commit que git no conoce: se relee
Además, `sin cuenta`: manifiestos de `inventario.py` que no figuran en ningún sello (componentes nuevos).
Con `--informe`, además `sin cubrir`: componentes de arquitectura.md (primera columna de sus tablas) que no tienen
fila en la tabla `## Cobertura` del informe (paso 6).
Las secciones sin componentes (p. ej. Restricciones) no llevan sello y no se contrastan.
Sale con código 1 si hay algo que releer, 0 si todo está igual.
"""
import argparse, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inventario

RE_SECCION = re.compile(r'^##\s+(.+?)\s*$', re.M)
RE_SELLO = re.compile(r'<!--\s*sello:\s*(\d{4}-\d{2}-\d{2})\s*·\s*([0-9a-f]{4,40})\s*·\s*(.*?)\s*-->')
SIN_CONTRASTE = ('restricciones',)


def secciones(texto):
    """[(título, fecha, commit, [rutas])]; fecha/commit None si la sección no tiene sello."""
    partes = RE_SECCION.split(texto)
    salida = []
    for titulo, cuerpo in zip(partes[1::2], partes[2::2]):
        if titulo.strip().lower() in SIN_CONTRASTE:
            continue
        m = RE_SELLO.search(cuerpo)
        if m:
            rutas = [r.strip() for r in m.group(3).split(',') if r.strip()]
            salida.append((titulo, m.group(1), m.group(2), rutas))
        else:
            salida.append((titulo, None, None, []))
    return salida


def _primera_columna(cuerpo):
    """Primera celda de cada fila de tabla, sin cabecera ni separador, normalizada."""
    celdas = []
    for linea in cuerpo.splitlines():
        if not linea.startswith('|') or re.match(r'^\|\s*:?-', linea):
            continue
        celda = linea.split('|')[1].replace('`', '').strip().lower()
        if celda and celda != 'componente':
            celdas.append(celda)
    return celdas


def sin_cubrir(texto_arq, texto_informe):
    """Componentes de arquitectura.md sin fila en `## Cobertura` del informe, en orden."""
    partes = RE_SECCION.split(texto_arq)
    componentes = []
    for titulo, cuerpo in zip(partes[1::2], partes[2::2]):
        if titulo.strip().lower() not in SIN_CONTRASTE:
            componentes += _primera_columna(cuerpo)
    partes = RE_SECCION.split(texto_informe)
    cubiertos = set()
    for titulo, cuerpo in zip(partes[1::2], partes[2::2]):
        if titulo.strip().lower() == 'cobertura':
            cubiertos |= set(_primera_columna(cuerpo))
    return [c for c in componentes if c not in cubiertos]


def git(raiz, *args):
    r = subprocess.run(['git', *args], cwd=raiz, capture_output=True, text=True)
    return r.returncode, r.stdout


def cambiados(raiz, commit, rutas):
    """Rutas del sello cambiadas desde commit; None si git no conoce el commit."""
    codigo, _ = git(raiz, 'cat-file', '-e', commit + '^{commit}')
    if codigo:
        return None
    # contra el árbol de trabajo: entra también lo cambiado sin commitear
    _, salida = git(raiz, 'diff', '--name-only', '--relative', commit, '--', *rutas)
    tocados = set(salida.split())
    tocados |= {r for r in rutas if not os.path.exists(os.path.join(raiz, r))}
    return sorted(tocados)


def contrastar(ruta_arq, raiz):
    with open(ruta_arq, encoding='utf-8') as f:
        texto = f.read()
    informe = {'igual': [], 'cambiada': [], 'sin sello': [], 'sin cuenta': []}
    sellados = set()
    for titulo, fecha, commit, rutas in secciones(texto):
        sellados |= set(rutas)
        if not commit:
            informe['sin sello'].append({'seccion': titulo})
            continue
        if not rutas:  # sin rutas, git diff compararía todo el repositorio
            informe['sin sello'].append({'seccion': titulo, 'motivo': 'sello sin archivos'})
            continue
        tocados = cambiados(raiz, commit, rutas)
        if tocados is None:
            informe['sin sello'].append({'seccion': titulo, 'motivo': 'commit %s desconocido' % commit})
        elif tocados:
            informe['cambiada'].append({'seccion': titulo, 'fecha': fecha, 'archivos': tocados})
        else:
            informe['igual'].append({'seccion': titulo, 'fecha': fecha})
    carpetas = tuple(r.rstrip('/') + '/' for r in sellados)  # un sello con una carpeta cubre sus manifiestos
    informe['sin cuenta'] = [m for m in inventario.inventariar(raiz)['manifiestos']
                             if m not in sellados and not m.startswith(carpetas)]
    return informe


def seccion(texto, titulo):
    """Texto de las secciones `## ...` cuyo título contiene `titulo` (sin mayúsculas); None si ninguna."""
    partes = RE_SECCION.split(texto)
    trozos = ['## %s\n\n%s' % (t, c.strip('\n') + '\n') for t, c in zip(partes[1::2], partes[2::2])
              if titulo.strip().lower() in t.lower()]
    return '\n'.join(trozos) or None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('arquitectura')
    ap.add_argument('--raiz', default='.')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--informe', help='informe del paso 6: comprueba su tabla de cobertura')
    ap.add_argument('--seccion', help='imprime solo las secciones cuyo título contiene este texto')
    a = ap.parse_args(argv)
    if a.seccion:
        with open(a.arquitectura, encoding='utf-8') as f:
            texto = f.read()
        trozo = seccion(texto, a.seccion)
        if trozo is None:
            print('Ninguna sección contiene «%s». Secciones: %s' % (a.seccion, ', '.join(RE_SECCION.findall(texto))))
            return 1
        print(trozo, end='')
        return 0
    inf = contrastar(a.arquitectura, a.raiz)
    if a.informe:
        with open(a.arquitectura, encoding='utf-8') as f, open(a.informe, encoding='utf-8') as g:
            inf['sin cubrir'] = sin_cubrir(f.read(), g.read())
    if a.json:
        print(json.dumps(inf, ensure_ascii=False, indent=1))
    else:
        for s in inf['igual']:
            print('igual      %s (sello %s)' % (s['seccion'], s['fecha']))
        for s in inf['cambiada']:
            print('cambiada   %s (sello %s): %s' % (s['seccion'], s['fecha'], ', '.join(s['archivos'])))
        for s in inf['sin sello']:
            print('sin sello  %s%s' % (s['seccion'], ' (%s)' % s['motivo'] if s.get('motivo') else ''))
        for m in inf['sin cuenta']:
            print('sin cuenta %s' % m)
        for c in inf.get('sin cubrir', []):
            print('sin cubrir %s' % c)
    return 1 if inf['cambiada'] or inf['sin sello'] or inf['sin cuenta'] or inf.get('sin cubrir') else 0


if __name__ == '__main__':
    sys.exit(main())
