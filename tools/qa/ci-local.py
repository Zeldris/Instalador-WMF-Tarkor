#!/usr/bin/env python3
"""FLU-3 (retro del piloto, 2026-10-22): la CI de GitHub corrida en local mientras está agotada.

Lee los pasos de `.github/workflows/comprobar.yml` (un dato, un sitio: no los copia) y corre, en orden, los `run:`
de los jobs de Ubuntu; un paso en rojo para el resto de su job, como en GitHub. Se salta los pasos con `if:` (solo de pull request) y los que instalan con `apt-get` (los pone
`tools/dev/instalar-entorno.sh`). Los jobs de otro sistema (Windows) salen como «sin cubrir»: quedan para la CI.

Uso: python3 tools/qa/ci-local.py [--apuntar] [--workflow <ruta>]
  --apuntar  añade una línea con la fecha, el commit y el resultado a docs/registros/ci-local.md.
Sale con 1 si falla algún paso.
"""
import argparse
import datetime
import os
import re
import subprocess
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
REGISTRO = os.path.join('docs', 'registros', 'ci-local.md')


def _sangria(linea):
    return len(linea) - len(linea.lstrip(' '))


def _valor(texto):
    texto = texto.strip()
    if len(texto) >= 2 and texto[0] == texto[-1] and texto[0] in '\'"':
        return texto[1:-1]
    return texto


def leer_jobs(texto):
    """Devuelve [{'nombre', 'runs_on', 'dir', 'pasos': [{'nombre', 'run', 'if'}]}] de un workflow sencillo."""
    lineas = texto.splitlines()
    jobs, job, paso = [], None, None
    en_jobs = False
    i = 0
    while i < len(lineas):
        linea = lineas[i]
        i += 1
        if not linea.strip() or linea.lstrip().startswith('#'):
            continue
        s = _sangria(linea)
        contenido = linea.strip()
        if s == 0:
            en_jobs = contenido == 'jobs:'
            continue
        if not en_jobs:
            continue
        if s == 2 and contenido.endswith(':'):
            job = {'nombre': contenido[:-1], 'runs_on': '', 'dir': '.', 'pasos': []}
            jobs.append(job)
            paso = None
            continue
        if job is None:
            continue
        if contenido.startswith('- '):
            paso = {'nombre': '', 'run': None, 'if': None}
            job['pasos'].append(paso)
            contenido = contenido[2:]
            s += 2
        m = re.match(r'([A-Za-z_-]+):\s*(.*)$', contenido)
        if not m:
            continue
        clave, resto = m.group(1), m.group(2)
        if clave == 'runs-on' and paso is None:
            job['runs_on'] = _valor(resto)
        elif clave == 'working-directory' and paso is None:
            job['dir'] = _valor(resto)
        elif paso is not None and clave == 'name':
            paso['nombre'] = _valor(resto)
        elif paso is not None and clave == 'if':
            paso['if'] = _valor(resto)
        elif paso is not None and clave == 'run':
            if resto.strip() in ('|', '>'):
                bloque = []
                while i < len(lineas) and (not lineas[i].strip() or _sangria(lineas[i]) > s):
                    bloque.append(lineas[i].strip())
                    i += 1
                paso['run'] = '\n'.join(l for l in bloque if l)
            else:
                paso['run'] = _valor(resto)
    return jobs


def planear(jobs):
    """Pasos a correr [(job, dir, nombre, orden)], saltados [(job, nombre, motivo)] y jobs sin cubrir."""
    correr, saltados, sin_cubrir = [], [], []
    for job in jobs:
        if 'ubuntu' not in job['runs_on']:
            sin_cubrir.append(f"{job['nombre']} ({job['runs_on']})")
            continue
        for paso in job['pasos']:
            if paso['run'] is None:
                continue
            nombre = paso['nombre'] or paso['run'].splitlines()[0]
            if paso['if']:
                saltados.append((job['nombre'], nombre, f"solo si {paso['if']}"))
            elif 'apt-get' in paso['run']:
                saltados.append((job['nombre'], nombre, 'paquetes de sistema (tools/dev/instalar-entorno.sh)'))
            else:
                correr.append((job['nombre'], job['dir'], nombre, paso['run']))
    return correr, saltados, sin_cubrir


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--apuntar', action='store_true')
    ap.add_argument('--workflow', default=os.path.join(RAIZ, '.github', 'workflows', 'comprobar.yml'))
    args = ap.parse_args(argv)
    with open(args.workflow, encoding='utf-8') as f:
        correr, saltados, sin_cubrir = planear(leer_jobs(f.read()))
    fallos = []
    for job, carpeta, nombre, orden in correr:
        if any(f.startswith(f'[{job}] ') for f in fallos):
            print(f'ci-local: no corrido [{job}] {nombre}: el job ya falló (como en GitHub)')
            continue
        print(f'ci-local: [{job}] {nombre}…', flush=True)
        r = subprocess.run(['bash', '-eo', 'pipefail', '-c', orden], cwd=os.path.join(RAIZ, carpeta),
                           capture_output=True, text=True)
        if r.returncode != 0:
            fallos.append(f'[{job}] {nombre}')
            print((r.stdout + r.stderr)[-3000:], file=sys.stderr)
            print(f'ci-local: FALLA [{job}] {nombre}', file=sys.stderr)
    for job, nombre, motivo in saltados:
        print(f'ci-local: saltado [{job}] {nombre}: {motivo}')
    cubierto = 'sin cubrir: ' + ', '.join(sin_cubrir) if sin_cubrir else 'todo cubierto'
    resultado = (f'en rojo ({"; ".join(fallos)})' if fallos else f'en verde ({len(correr)} pasos)') + f'; {cubierto}'
    print(f'ci-local: {resultado}')
    if args.apuntar:
        sha = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=RAIZ, capture_output=True,
                             text=True).stdout.strip()
        sucio = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=RAIZ,
                               capture_output=True, text=True).stdout.strip()
        ruta = os.path.join(RAIZ, REGISTRO)
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        nuevo = not os.path.exists(ruta)
        with open(ruta, 'a', encoding='utf-8') as f:
            if nuevo:
                f.write('# CI en local\n\nLo escribe `python3 tools/qa/ci-local.py --apuntar` mientras la CI de GitHub '
                        'está agotada (`FLU-3`).\n\n')
            f.write(f'- {datetime.date.today().isoformat()} · `{sha}`{" (con cambios sin commit)" if sucio else ""}'
                    f' · {resultado}\n')
    return 1 if fallos else 0


if __name__ == '__main__':
    sys.exit(main())
