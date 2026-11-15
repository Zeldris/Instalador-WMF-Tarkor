#!/usr/bin/env python3
"""INS-67: genera app/src/fuentes.css desde los CSS de @fontsource (app/node_modules/@fontsource/<familia>/<peso>.css).

Se queda solo con los @font-face de los subconjuntos latin y latin-ext, solo con la fuente woff2 (sin el .woff) y con
la ruta relativa a app/src. Uso:
    python3 tools/dev/fuentes.py            # reescribe app/src/fuentes.css
    python3 tools/dev/fuentes.py --check    # sale en 1 si el archivo commiteado difiere de lo generado
"""
import os
import re
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
APP = os.path.join(RAIZ, 'app')
SALIDA = os.path.join(APP, 'src', 'fuentes.css')
FAMILIAS = [('cinzel', (400, 600, 700)), ('inter', (400, 500, 600))]

CABECERA = """/* Fuentes empaquetadas en local (@fontsource), solo los subconjuntos latin y latin-ext y solo woff2 (INS-67):
   el asistente es en castellano y WebView2 y WebKitGTK leen woff2. Generado por tools/dev/fuentes.py (no se edita
   a mano) de los 400.css…700.css de @fontsource; con unicode-range, el navegador baja solo el subconjunto que use
   la página. */
"""


def generar():
    bloques = []
    for familia, pesos in FAMILIAS:
        for peso in pesos:
            ruta = os.path.join(APP, 'node_modules', '@fontsource', familia, f'{peso}.css')
            with open(ruta, encoding='utf-8') as f:
                css = f.read()
            for m in re.finditer(r'(/\* [^*]+ \*/)\n(@font-face \{.*?\n\})', css, re.S):
                comentario, cuerpo = m.groups()
                if not re.search(rf'-latin(-ext)?-{peso}-normal ', comentario):
                    continue
                cuerpo = re.sub(
                    r"src: url\(\./files/([^)]+\.woff2)\) format\('woff2'\), url\([^)]+\) format\('woff'\);",
                    rf"src: url(../node_modules/@fontsource/{familia}/files/\1) format('woff2');",
                    cuerpo,
                )
                bloques.append(f'{comentario}\n{cuerpo}\n')
    return CABECERA + '\n' + '\n'.join(bloques)


def main():
    nuevo = generar()
    if '--check' in sys.argv[1:]:
        with open(SALIDA, encoding='utf-8') as f:
            if f.read() != nuevo:
                print('app/src/fuentes.css difiere de lo generado: python3 tools/dev/fuentes.py', file=sys.stderr)
                return 1
        return 0
    with open(SALIDA, 'w', encoding='utf-8', newline='\n') as f:
        f.write(nuevo)
    return 0


if __name__ == '__main__':
    sys.exit(main())
