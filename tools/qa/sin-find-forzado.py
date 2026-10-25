#!/usr/bin/env python3
"""INS-43 (retro): ningún código del asistente fuerza con `!` el resultado de un `.find(...)`.

`perfiles.find(...)!` se cayó dos veces con un perfil guardado que ya no existía en la evaluación (y tres más
estaban latentes). Para un perfil, `perfilDe()` (app/src/tipos.ts) trae el de la evaluación con un respaldo; para
lo demás, `?? <respaldo>` o un `if (!x)` explícito. Se miran los `*.ts` y `*.tsx` de `app/src` salvo los tests
(`*.test.ts(x)`) y `app/src/test*`, y solo la misma línea del `.find(`.

Uso: python3 tools/qa/sin-find-forzado.py [raíz]   (raíz del repo; por defecto, la de este script)
Sale con 1 y lista `archivo:línea` de cada coincidencia.
"""
import os
import re
import sys

FORZADO = re.compile(r'\.find\([^\n]*\)!')
RAIZ = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))


def es_codigo(ruta_relativa: str) -> bool:
    nombre = os.path.basename(ruta_relativa)
    if not nombre.endswith(('.ts', '.tsx')) or re.search(r'\.test\.tsx?$', nombre):
        return False
    return not os.path.relpath(ruta_relativa, 'src').split(os.sep)[0].startswith('test')


def buscar(raiz: str) -> list[str]:
    base = os.path.join(raiz, 'app', 'src')
    hallazgos = []
    for carpeta, subs, archivos in os.walk(base):
        subs.sort()
        for nombre in sorted(archivos):
            ruta = os.path.join(carpeta, nombre)
            if not es_codigo(os.path.relpath(ruta, os.path.join(raiz, 'app'))):
                continue
            with open(ruta, encoding='utf-8') as f:
                for n, linea in enumerate(f, 1):
                    if FORZADO.search(linea):
                        hallazgos.append(f'{os.path.relpath(ruta, raiz)}:{n}: {linea.strip()}')
    return hallazgos


def main(argv: list[str]) -> int:
    hallazgos = buscar(os.path.abspath(argv[1]) if len(argv) > 1 else RAIZ)
    if hallazgos:
        print('sin-find-forzado: `.find(...)!` fuerza un resultado que puede no existir; usa `perfilDe()` para un perfil '
              'o un respaldo explícito (`?? …`):', file=sys.stderr)
        for h in hallazgos:
            print(f'  {h}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
