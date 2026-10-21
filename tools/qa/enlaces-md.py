#!/usr/bin/env python3
"""QA-107 (2026-10-19): enlaces rotos en los `.md` del repositorio (CI).

Mira los enlaces relativos `[texto](ruta)` y `[texto](ruta#ancla)`: que el archivo exista y, si lleva ancla y es un
`.md`, que tenga un encabezado con esa ancla (como las genera GitHub). Los enlaces externos (http, mailto) no se
miran. Sale con 1 si hay alguno roto.
Uso: python3 tools/qa/enlaces-md.py [--solo-archivos]
"""
import os, re, subprocess, sys, urllib.parse

RAIZ = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True).stdout.strip()
ENLACE = re.compile(r'(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')


def ancla(texto):
    """El ancla que GitHub da a un encabezado."""
    t = re.sub(r'`|\*\*|\*|~~|\[|\]\([^)]*\)', '', texto.strip().lower())
    t = re.sub(r'[^\w\- ]', '', t, flags=re.UNICODE)
    return t.replace(' ', '-')


def anclas_de(ruta, cache={}):
    if ruta not in cache:
        vistas, dentro_de_codigo = {}, False
        out = set()
        for l in open(ruta, encoding='utf-8'):
            if re.match(r'^\s*(```|~~~)', l):
                dentro_de_codigo = not dentro_de_codigo
            if dentro_de_codigo:
                continue
            m = re.match(r'^#{1,6}\s+(.*?)\s*#*\s*$', l)
            if m:
                a = ancla(m.group(1))
                n = vistas.get(a, 0)
                vistas[a] = n + 1
                out.add(a if n == 0 else f'{a}-{n}')
            for idm in re.findall(r'<a\s+(?:name|id)="([^"]+)"', l):
                out.add(idm)
        cache[ruta] = out
    return cache[ruta]


def main():
    solo_archivos = '--solo-archivos' in sys.argv
    archivos = subprocess.run(['git', 'ls-files', '*.md'], capture_output=True, text=True, cwd=RAIZ).stdout.split()
    rotos = []
    for rel in archivos:
        ruta = os.path.join(RAIZ, rel)
        dentro_de_codigo = False
        for n, l in enumerate(open(ruta, encoding='utf-8'), 1):
            if re.match(r'^\s*(```|~~~)', l):
                dentro_de_codigo = not dentro_de_codigo
            if dentro_de_codigo:
                continue
            for destino in ENLACE.findall(re.sub(r'`[^`]*`', '', l)):
                if re.match(r'^[a-z]+:', destino) or destino.startswith('<'):
                    continue
                camino, _, an = destino.partition('#')
                # GitHub acepta el ancla en mayúsculas y con los acentos codificados (`%C3%B3`).
                an = urllib.parse.unquote(an).lower()
                camino = urllib.parse.unquote(camino)
                # QA-184: `docs/registros/pr/` guarda la descripción de un PR, que enlaza desde la raíz del repo.
                base = RAIZ if rel.startswith('docs/registros/pr/') else os.path.dirname(ruta)
                objetivo = os.path.normpath(os.path.join(base, camino)) if camino else ruta
                if camino and not os.path.exists(objetivo):
                    rotos.append(f'{rel}:{n}: no existe {camino}')
                elif an and not solo_archivos and objetivo.endswith('.md') and an not in anclas_de(objetivo):
                    rotos.append(f'{rel}:{n}: {camino or "(este archivo)"} no tiene el ancla #{an}')
    for r in rotos:
        print(r)
    print(f'{len(rotos)} enlaces rotos en {len(archivos)} archivos .md')
    return 1 if rotos else 0


if __name__ == '__main__':
    sys.exit(main())
