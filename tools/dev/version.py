#!/usr/bin/env python3
"""FLU-10: una sola versión para el instalador.

La versión vive en `app/src-tauri/tauri.conf.json`; este script la copia al resto de archivos que la repiten
(`app/package.json`, `app/package-lock.json`, `[workspace.package]` de `app/Cargo.toml` y los miembros del
workspace en `app/Cargo.lock`) y saca de `CHANGELOG.md` las notas de una versión para el release.

    python3 tools/dev/version.py                  # la versión actual
    python3 tools/dev/version.py comprobar        # sale en 1 si alguna copia no coincide
    python3 tools/dev/version.py copiar           # copia la de tauri.conf.json a las demás
    python3 tools/dev/version.py publicar X.Y.Z   # pone X.Y.Z y pasa [Unreleased] a [X.Y.Z] - hoy
    python3 tools/dev/version.py notas vX.Y.Z     # notas de esa versión (el tag tiene que coincidir con la versión)

Los archivos se editan con expresiones regulares para no tocar su formato; sin tomllib, que el job qa del CI
(Python 3.10) no trae.
"""
import argparse
import datetime
import json
import os
import re
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
FUENTE = 'app/src-tauri/tauri.conf.json'
CHANGELOG = 'CHANGELOG.md'
SEMVER = re.compile(r'^\d+\.\d+\.\d+$')
# Paquetes del workspace de Rust (su versión sale de [workspace.package] y Cargo.lock la repite).
MIEMBROS = ('tarkor', 'tarkor-nucleo')


def leer(raiz: str, ruta: str) -> str:
    with open(os.path.join(raiz, ruta), encoding='utf-8') as f:
        return f.read()


def escribir(raiz: str, ruta: str, texto: str) -> None:
    with open(os.path.join(raiz, ruta), 'w', encoding='utf-8', newline='\n') as f:
        f.write(texto)


def _json_version(n: int):
    """Las n primeras claves `"version"` de un JSON con formato (en package-lock, la raíz y `packages[""]`)."""
    return re.compile(r'("version"\s*:\s*")([^"]*)(")'), n


def _cargo_workspace():
    return re.compile(r'(^\[workspace\.package\][^\[]*?^version\s*=\s*")([^"]*)(")', re.MULTILINE | re.DOTALL), 1


def _cargo_lock(nombre: str):
    return re.compile(r'(^name = "' + re.escape(nombre) + r'"\nversion = ")([^"]*)(")', re.MULTILINE), 1


# Cada copia: archivo, patrón y cuántas veces aparece. El grupo 2 es la versión.
COPIAS = [
    ('app/package.json', *_json_version(1)),
    ('app/package-lock.json', *_json_version(2)),
    ('app/Cargo.toml', *_cargo_workspace()),
    *[('app/Cargo.lock', *_cargo_lock(m)) for m in MIEMBROS],
]


def actual(raiz: str = RAIZ) -> str:
    version = json.loads(leer(raiz, FUENTE)).get('version', '')
    if not SEMVER.match(version):
        raise SystemExit(f'{FUENTE}: "version" no es X.Y.Z: {version!r}')
    return version


def _encontradas(texto: str, patron: re.Pattern, veces: int) -> list:
    return [m.group(2) for m in patron.finditer(texto)][:veces]


def diferencias(raiz: str = RAIZ) -> list:
    """Las copias que no coinciden con la versión de FUENTE, como «archivo: lo que tiene»."""
    version = actual(raiz)
    malas = []
    for ruta, patron, veces in COPIAS:
        halladas = _encontradas(leer(raiz, ruta), patron, veces)
        if len(halladas) < veces:
            malas.append(f'{ruta}: no se encuentra la versión ({len(halladas)} de {veces})')
        malas += [f'{ruta}: {v} (se espera {version})' for v in halladas if v != version]
    return malas


def _poner(texto: str, patron: re.Pattern, veces: int, version: str) -> str:
    return patron.sub(lambda m: m.group(1) + version + m.group(3), texto, count=veces)


def copiar(raiz: str = RAIZ, version: str = '') -> list:
    """Escribe `version` (o la de FUENTE) en FUENTE y en las copias; devuelve los archivos cambiados."""
    if version:
        if not SEMVER.match(version):
            raise SystemExit(f'la versión tiene que ser X.Y.Z: {version!r}')
        fuente = [(FUENTE, *_json_version(1))]
    else:
        version, fuente = actual(raiz), []
    cambiados = []
    for ruta, patron, veces in fuente + COPIAS:
        texto = leer(raiz, ruta)
        if len(_encontradas(texto, patron, veces)) < veces:
            raise SystemExit(f'{ruta}: no se encuentra la versión')
        nuevo = _poner(texto, patron, veces, version)
        if nuevo != texto:
            escribir(raiz, ruta, nuevo)
            cambiados.append(ruta)
    return sorted(set(cambiados))


SECCION = re.compile(r'^## \[([^\]]+)\][^\n]*\n', re.MULTILINE)


def _secciones(texto: str) -> dict:
    """Título de cada `## [x]` → (inicio del título, inicio del cuerpo, fin del cuerpo)."""
    marcas = list(SECCION.finditer(texto))
    fin_ultima = re.search(r'^\[[^\]]+\]:\s', texto, re.MULTILINE)
    resultado = {}
    for i, m in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else (fin_ultima.start() if fin_ultima else len(texto))
        resultado[m.group(1)] = (m.start(), m.end(), fin)
    return resultado


def notas(version: str, raiz: str = RAIZ) -> str:
    texto = leer(raiz, CHANGELOG)
    seccion = _secciones(texto).get(version)
    if not seccion:
        raise SystemExit(f'{CHANGELOG}: no hay sección ## [{version}]')
    cuerpo = texto[seccion[1]:seccion[2]].strip()
    if not cuerpo:
        raise SystemExit(f'{CHANGELOG}: la sección ## [{version}] está vacía')
    return cuerpo + '\n'


def publicar(version: str, raiz: str = RAIZ, fecha: str = '') -> list:
    """Pone la versión y pasa lo de [Unreleased] a una sección nueva con fecha; [Unreleased] queda vacía."""
    texto = leer(raiz, CHANGELOG)
    secciones = _secciones(texto)
    if version in secciones:
        raise SystemExit(f'{CHANGELOG}: ya hay sección ## [{version}]')
    if 'Unreleased' not in secciones:
        raise SystemExit(f'{CHANGELOG}: no hay sección ## [Unreleased]')
    _, cuerpo, fin = secciones['Unreleased']
    if not texto[cuerpo:fin].strip():
        raise SystemExit(f'{CHANGELOG}: [Unreleased] está vacía; no hay nada que publicar')
    anterior = actual(raiz)
    cambiados = copiar(raiz, version)
    fecha = fecha or datetime.date.today().isoformat()
    texto = texto[:cuerpo] + f'\n## [{version}] - {fecha}\n' + texto[cuerpo:]
    # Enlaces de comparación al pie: [Unreleased] desde el tag nuevo y el de la versión nueva desde la anterior.
    unreleased = re.search(r'^\[Unreleased\]:\s*(\S+/compare/)v[^.\s]+\.[^.\s]+\.[^.\s]+\.\.\.HEAD$', texto, re.MULTILINE)
    if unreleased:
        base = unreleased.group(1)
        texto = (texto[:unreleased.start()] + f'[Unreleased]: {base}v{version}...HEAD\n'
                 f'[{version}]: {base}v{anterior}...v{version}' + texto[unreleased.end():])
    escribir(raiz, CHANGELOG, texto)
    return sorted(set(cambiados + [CHANGELOG]))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = p.add_subparsers(dest='orden')
    sub.add_parser('comprobar', help='sale en 1 si alguna copia no coincide con tauri.conf.json')
    sub.add_parser('copiar', help='copia la versión de tauri.conf.json a las demás')
    pub = sub.add_parser('publicar', help='pone X.Y.Z y pasa [Unreleased] a [X.Y.Z] - hoy')
    pub.add_argument('version')
    pub.add_argument('--fecha', default='', help='AAAA-MM-DD (por defecto, hoy)')
    nt = sub.add_parser('notas', help='notas de CHANGELOG.md para el tag vX.Y.Z')
    nt.add_argument('tag')
    a = p.parse_args(argv)

    if a.orden is None:
        print(actual())
    elif a.orden == 'comprobar':
        malas = diferencias()
        for m in malas:
            print(m, file=sys.stderr)
        if malas:
            print('arreglo: python3 tools/dev/version.py copiar', file=sys.stderr)
            return 1
        print(f'versión {actual()} en todas las copias')
    elif a.orden == 'copiar':
        for r in copiar():
            print(r)
    elif a.orden == 'publicar':
        for r in publicar(a.version, fecha=a.fecha):
            print(r)
    elif a.orden == 'notas':
        if not re.match(r'^v\d+\.\d+\.\d+$', a.tag):
            raise SystemExit(f'el tag tiene que ser vX.Y.Z: {a.tag!r}')
        if a.tag[1:] != actual():
            raise SystemExit(f'el tag {a.tag} no coincide con la versión de {FUENTE} ({actual()})')
        sys.stdout.write(notas(a.tag[1:]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
