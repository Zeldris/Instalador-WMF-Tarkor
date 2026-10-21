#!/usr/bin/env python3
"""QA-116 (usuaria, 2026-10-19): compactar sin perder lo que haga falta después.

Compactar resume la conversación, pero el registro de la sesión (`~/.claude/projects/<proyecto>/<sesión>.jsonl`)
la guarda entera mientras dure el contenedor. Esto la consulta sin leerla (pesa cientos de MB):

  recuperar.py "<regex>"      los fragmentos de la conversación principal que casan (lo escrito por la usuaria,
                              por Claude, las órdenes y sus resultados), recortados, los más recientes al final.
                              --max N (10), --ancho N (400 caracteres por fragmento), --sesion <ruta.jsonl>.
  recuperar.py --estado       lo que el gancho de SessionStart vuelve a poner en el contexto tras cada compactación:
                              la fila de la rama en la bitácora, git status, los últimos commits, las compactaciones
                              de la sesión (para el presupuesto de la tarea) y cómo recuperar un detalle.

Desde el gancho, el registro es el `transcript_path` que Claude Code le pasa por la entrada; si no, el `.jsonl` más
reciente del proyecto (igual que `medir.py` de opt-tokens). `--estado` imprime la orden con `--sesion` ya puesta.
Una sesión nueva no tiene el registro de la anterior: lo que tiene que sobrevivir va a la bitácora (CLAUDE.md).
"""
import glob, json, os, re, subprocess, sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))


# Una llamada a este script (no una mención: un diff o un mensaje que lo nombran sí se buscan).
LLAMADA = re.compile(r'python3?\s+\S*recuperar\.py\s+(?!--estado)')


def ruta_por_defecto():
    # Igual que `ruta_por_defecto` de .claude/skills/opt-tokens/medir.py, con la raíz del repo como proyecto.
    proyecto = re.sub(r'[^A-Za-z0-9]', '-', os.environ.get('CLAUDE_PROJECT_DIR') or RAIZ)
    candidatos = glob.glob(os.path.expanduser(f'~/.claude/projects/{proyecto}/*.jsonl'))
    return max(candidatos, key=os.path.getmtime) if candidatos else None


def quien_escribe(d, texto):
    """Lo inyectado en un turno de la usuaria (avisos del sistema, ganchos, órdenes `/`) no lo dijo ella."""
    if d.get('type') != 'user':
        return 'claude'
    return 'sistema' if d.get('isMeta') or texto.lstrip().startswith('<') else 'usuaria'


def textos(d):
    """(quién, texto) de cada bloque de una línea del registro; los de las llamadas a este mismo script, fuera."""
    m = d.get('message') or {}
    contenido = m.get('content')
    if isinstance(contenido, str):
        yield quien_escribe(d, contenido), contenido
        return
    for b in contenido or []:
        if not isinstance(b, dict):
            continue
        t = b.get('type')
        if t == 'text':
            yield quien_escribe(d, b.get('text', '')), b.get('text', '')
        elif t == 'tool_use':
            yield f'orden {b.get("name", "?")}', json.dumps(b.get('input') or {}, ensure_ascii=False)
        elif t == 'tool_result':
            c = b.get('content')
            if isinstance(c, list):
                c = '\n'.join(x.get('text', '') for x in c if isinstance(x, dict))
            yield 'resultado', c or ''


def buscar(ruta, patron, maximo, ancho):
    # Se busca en el texto ya leído, no en la línea JSON: en ella las comillas, los saltos de línea y `^` no casan.
    try:
        rx = re.compile(patron, re.I)
    except re.error as e:
        sys.exit(f'La expresión /{patron}/ no vale ({e}); para texto literal, escapa los símbolos: re.escape')
    hallados, propias = [], set()
    for linea in open(ruta, encoding='utf-8'):
        try:
            d = json.loads(linea)
        except json.JSONDecodeError:
            continue
        if d.get('isSidechain') or d.get('isCompactSummary'):
            continue
        bloques = (d.get('message') or {}).get('content')
        if isinstance(bloques, list):
            # Las búsquedas anteriores con este script y sus resultados repetirían lo ya encontrado.
            for b in bloques:
                if isinstance(b, dict) and b.get('type') == 'tool_use' and LLAMADA.search(str((b.get('input') or {}).get('command', ''))):
                    propias.add(b.get('id'))
            if any(isinstance(b, dict) and (b.get('id') in propias or b.get('tool_use_id') in propias) for b in bloques):
                continue
        for quien, texto in textos(d):
            m = rx.search(texto)
            if m:
                ini = max(0, m.start() - ancho // 2)
                trozo = re.sub(r'\s+', ' ', texto[ini:ini + ancho]).strip()
                hallados.append(f'[{(d.get("timestamp") or "")[:16]}] {quien}: {"…" if ini else ""}{trozo}…')
    for h in hallados[-maximo:]:
        print(h)
    print(f'{len(hallados)} fragmentos con /{patron}/' + (f' (los {maximo} últimos)' if len(hallados) > maximo else ''))


def git(*args):
    return subprocess.run(['git', '-C', RAIZ, *args], capture_output=True, text=True).stdout.strip()


def estado(ruta):
    rama = git('rev-parse', '--abbrev-ref', 'HEAD')
    print(f'Estado tras compactar (QA-116), rama {rama}:')
    bitacora = os.path.join(RAIZ, 'docs', 'registros', 'traspaso.md')
    if os.path.exists(bitacora):
        fila = next((l for l in open(bitacora, encoding='utf-8') if l.startswith(f'| **Tarea en curso · `{rama}`**')), None)
        print('- Bitácora: ' + (fila.split('|', 2)[2].rsplit('|', 1)[0].strip() if fila else 'sin fila para esta rama'))
    # Sin el strip de `git()`: el espacio inicial de « M ruta» es parte del formato.
    cambios = subprocess.run(['git', '-C', RAIZ, 'status', '--short'], capture_output=True, text=True).stdout.splitlines()
    print(f'- Sin commit: {len(cambios)} archivos' + (': ' + ', '.join(c[3:] for c in cambios[:8]) if cambios else ''))
    print('- Últimos commits: ' + ' · '.join(git('log', '--format=%h %s', '-3').splitlines()))
    if ruta and os.path.exists(ruta):
        n = sum(1 for l in open(ruta, encoding='utf-8') if '"compact_boundary"' in l)
        print(f'- Compactaciones en esta sesión: {n} (compáralo con el presupuesto de la tarea en la bitácora)')
    sesion = f' --sesion {ruta}' if ruta else ''
    print('- Si falta un detalle de antes (un error, un trozo de código, lo que dijo la usuaria): '
          f'python3 tools/qa/recuperar.py "<regex>"{sesion}, nunca leer el registro entero.')


def ruta_del_gancho():
    """El `transcript_path` que Claude Code pasa a un gancho por la entrada estándar."""
    if sys.stdin is None or sys.stdin.isatty():
        return None
    try:
        return json.loads(sys.stdin.read() or '{}').get('transcript_path')
    except (json.JSONDecodeError, AttributeError):
        return None


def main():
    args = sys.argv[1:]
    opciones = {'--max': 10, '--ancho': 400, '--sesion': None}
    for k in list(opciones):
        if k in args:
            i = args.index(k)
            if i + 1 >= len(args):
                sys.exit(f'{k} necesita un valor')
            try:
                opciones[k] = args[i + 1] if k == '--sesion' else int(args[i + 1])
            except ValueError:
                sys.exit(f'{k} necesita un número, no «{args[i + 1]}»')
            del args[i:i + 2]
    if args == ['--estado']:
        estado(opciones['--sesion'] or ruta_del_gancho() or ruta_por_defecto())
        return 0
    if len(args) != 1:
        print(__doc__)
        return 2
    ruta = opciones['--sesion'] or ruta_por_defecto()
    if not ruta:
        sys.exit('No encuentro el registro de la sesión (usa --sesion <ruta.jsonl>)')
    buscar(ruta, args[0], opciones['--max'], opciones['--ancho'])
    return 0


if __name__ == '__main__':
    sys.exit(main())
