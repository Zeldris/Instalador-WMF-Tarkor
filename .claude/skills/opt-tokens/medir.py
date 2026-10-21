#!/usr/bin/env python3
"""Dónde se van los tokens de una sesión de Claude Code (skill `opt-tokens`).

Lee el registro de la sesión (`~/.claude/projects/<proyecto>/<sesión>.jsonl`) y saca:
  - el uso real de la API (entrada, caché escrita, caché leída, salida) de las llamadas del periodo;
  - por herramienta: cuántas llamadas, los tokens que metieron sus resultados en el contexto y los tokens
    **arrastrados** (cada resultado se vuelve a enviar en cada llamada posterior hasta la siguiente
    compactación: un resultado de 5k tokens con 200 llamadas detrás pesa 1M);
  - los resultados más pesados, las imágenes, los errores, y lo repetido (mismo archivo leído o misma orden);
  - por archivo (QA-175): cuántas veces se leyó cada uno (Read, o Bash con cat/sed/head/grep… sobre su ruta) y lo que
    arrastraron esas lecturas: un archivo grande que se relee pide un puntero en un mapa o una herramienta;
  - por modelo, la sesión principal y sus subagentes (`<sesión>/subagents/*.jsonl`): si lo mecánico va al modelo
    caro o el diseño a uno barato (QA-117);
  - por subagente (una fila por registro: descripción, tipo, modelo, llamadas, contexto medio, entrada, salida) y el
    total de sesión + subagentes (QA-146). La salida es la mayor de las líneas de cada respuesta, no la primera.

Uso:
  python3 medir.py                       la sesión más reciente del proyecto actual, últimas 24 h
  python3 medir.py --horas 6             otro periodo (0 = toda la sesión)
  python3 medir.py --desde <ISO|sha>     solo desde ese momento (commit: su fecha; fecha ISO-8601, sin zona = UTC); sustituye a --horas
  python3 medir.py --sesion <ruta.jsonl> otra sesión
  python3 medir.py --top 20              cuántas filas en cada lista

Los tokens de un resultado se estiman por su tamaño (caracteres / 3,5; una imagen, ~1.600). El uso de la API es
el exacto que trae el registro.
"""
import argparse, collections, datetime as dt, glob, json, os, re, subprocess, sys

TOKENS_IMAGEN = 1600
CHARS_POR_TOKEN = 3.5
SALIDA_MINIMA = 100  # tokens de salida por llamada por debajo de los cuales la de un subagente no es fiable


def raiz_del_proyecto():
    # La misma carpeta de proyecto que `ruta_por_defecto` de tools/qa/recuperar.py: la raíz del repo, aunque se
    # lance desde una subcarpeta.
    if os.environ.get('CLAUDE_PROJECT_DIR'):
        return os.environ['CLAUDE_PROJECT_DIR']
    r = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    return r.stdout.strip() or os.getcwd()


def momento_desde(valor):
    """QA-134: `--desde` acepta un commit (su fecha) o una fecha ISO-8601 (sin zona, UTC). Siempre en UTC."""
    r = subprocess.run(['git', 'rev-parse', '--verify', '--quiet', f'{valor}^{{commit}}'], capture_output=True, text=True)
    if r.returncode == 0:
        f = dt.datetime.fromisoformat(subprocess.run(['git', 'show', '-s', '--format=%cI', r.stdout.strip()],
                                                     capture_output=True, text=True).stdout.strip())
    else:
        try:
            f = dt.datetime.fromisoformat(valor.replace('Z', '+00:00'))
        except ValueError:
            sys.exit(f'--desde: «{valor}» no es un commit ni una fecha ISO-8601')
    return (f if f.tzinfo else f.replace(tzinfo=dt.timezone.utc)).astimezone(dt.timezone.utc)


def ruta_por_defecto():
    proyecto = re.sub(r'[^A-Za-z0-9]', '-', raiz_del_proyecto())
    candidatos = glob.glob(os.path.expanduser(f'~/.claude/projects/{proyecto}/*.jsonl'))
    if not candidatos:
        sys.exit(f'No hay sesiones en ~/.claude/projects/{proyecto}/ (usa --sesion)')
    return max(candidatos, key=os.path.getmtime)


def tokens_de(contenido):
    """Tokens estimados y número de imágenes de un `tool_result`."""
    if isinstance(contenido, str):
        return len(contenido) / CHARS_POR_TOKEN, 0
    total, imagenes = 0.0, 0
    for b in contenido or []:
        if b.get('type') == 'image':
            imagenes += 1
            total += TOKENS_IMAGEN
        else:
            total += len(b.get('text', '') or '') / CHARS_POR_TOKEN
    return total, imagenes


def resumen_entrada(nombre, entrada):
    for clave in ('command', 'file_path', 'pattern', 'url', 'query', 'skill', 'description'):
        if clave in entrada:
            return f'{clave}={str(entrada[clave])[:110]}'
    return json.dumps(entrada, ensure_ascii=False)[:110]


ARCHIVO = re.compile(r'(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.(?:ts|tsx|js|mjs|py|md|sh|json|jsonl|sql|prisma|css|html))(?![\w/])')
LEE = re.compile(r'(?:^|[|;&(]\s*|\s)(?:cat|sed|head|tail|grep|rg|awk|wc|less|nl|cut)\s')
CD = re.compile(r'^\s*cd\s+(\S+)\s*&&')
# QA-179: lo que va justo detrás de un intérprete (o con `./`) se ejecuta, no se lee: `bash tools/qa/host.sh grep …`.
EJECUTA = re.compile(r'(?:^|[|;&(]\s*|\s)(?:(?:bash|sh|python3?|node)\s+(?:-\S+\s+)*|(?=\./))(\S+)')


def rutas_leidas(nombre, entrada, raiz):
    """QA-175: los archivos que lee una llamada, con la ruta desde la raíz del repo. Read: su `file_path`; Bash: las
    rutas de la orden si lleva una orden de lectura (con `cd <dir> &&` delante, relativas a <dir>), salvo los scripts
    que la orden ejecuta."""
    if nombre == 'Read' and entrada.get('file_path'):
        rutas = [entrada['file_path']]
    elif nombre == 'Bash' and LEE.search(entrada.get('command') or ''):
        orden = entrada['command']
        cd = CD.match(orden)
        base = cd.group(1) if cd else ''
        ejecutados = {os.path.normpath(e) for e in EJECUTA.findall(orden)}
        rutas = [r if r.startswith('/') or not base else os.path.join(base, r)
                 for r in ARCHIVO.findall(orden) if os.path.normpath(r) not in ejecutados]
    else:
        return []
    fuera = raiz.rstrip('/') + '/'
    return sorted({del_repo(os.path.normpath(r[len(fuera):] if r.startswith(fuera) else r), raiz) for r in rutas})


def del_repo(ruta, raiz, cache={}):
    """La ruta desde la raíz: una relativa a otra carpeta de trabajo (`src/x.ts` desde backend/) se resuelve por el
    único archivo de git que acaba igual; si hay varios o ninguno, se deja tal cual."""
    if raiz not in cache:
        r = subprocess.run(['git', 'ls-files'], cwd=raiz, capture_output=True, text=True)
        cache[raiz] = r.stdout.split()
    if ruta in cache[raiz] or ruta.startswith('/'):
        return ruta
    iguales = [f for f in cache[raiz] if f.endswith('/' + ruta)]
    return iguales[0] if len(iguales) == 1 else ruta


def respuestas_de(ruta, desde):
    """Las respuestas de la API de un registro, una por id de mensaje: lista de (modelo, contexto, salida).
    Claude Code escribe una línea por bloque con el mismo `usage`, pero `output_tokens` crece de una línea a otra
    (la primera trae un valor provisional): la salida real es el máximo de las líneas del mismo id (QA-146)."""
    por_id = {}
    for linea in open(ruta, encoding='utf-8'):
        try:
            d = json.loads(linea)
        except json.JSONDecodeError:
            continue
        m = d.get('message') or {}
        if d.get('type') != 'assistant' or not m.get('usage') or (m.get('model') or '').startswith('<'):
            continue
        ts = d.get('timestamp')
        if desde and ts and dt.datetime.fromisoformat(ts.replace('Z', '+00:00')) < desde:
            continue
        u = m['usage']
        ctx = sum(u.get(k) or 0 for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'))
        clave = m.get('id') or d.get('requestId') or d.get('uuid')
        antes = por_id.get(clave)
        por_id[clave] = (m.get('model') or '?', ctx, max(u.get('output_tokens') or 0, antes[2] if antes else 0))
    return list(por_id.values())


def uso_por_modelo(ruta, desde, por_modelo, quien):
    """Suma en `por_modelo[(quien, modelo)]` las llamadas, la entrada y la salida del registro de un subagente.
    Devuelve las respuestas (para el desglose por subagente)."""
    resp = respuestas_de(ruta, desde)
    for modelo, ctx, sal in resp:
        p = por_modelo[(quien, modelo)]
        p[0] += 1; p[1] += ctx; p[2] += sal
    return resp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sesion')
    ap.add_argument('--horas', type=float, default=24)
    ap.add_argument('--desde')
    ap.add_argument('--top', type=int, default=12)
    a = ap.parse_args()
    ruta = a.sesion or ruta_por_defecto()
    desde = None
    if a.desde:
        desde = momento_desde(a.desde)
    elif a.horas > 0:
        desde = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=a.horas)

    usos = collections.Counter()
    llamadas_api = 0
    contextos = []  # contexto de cada llamada, para la curva entre compactaciones
    usos_tool = {}  # id → (nombre, resumen)
    archivos_tool = {}  # id → archivos que lee (QA-175)
    raiz = raiz_del_proyecto()
    resultados = []  # (indice_llamada, id, tokens, imagenes, es_error)
    cortes = []  # índice de llamada en el que hubo compactación
    vistos = {}  # id de mensaje → índice de su llamada (para quedarse con la salida mayor)
    salidas = []  # salida de cada llamada
    modelos_llamada = []  # modelo de cada llamada (o None)
    por_modelo = collections.defaultdict(lambda: [0, 0, 0])  # (quién, modelo) → llamadas, entrada, salida
    recortada = False  # con --horas, si la sesión empezó antes del periodo
    for linea in open(ruta, encoding='utf-8'):
        try:
            d = json.loads(linea)
        except json.JSONDecodeError:
            continue
        ts = d.get('timestamp')
        if desde and ts:
            if dt.datetime.fromisoformat(ts.replace('Z', '+00:00')) < desde:
                recortada = True
                continue
        if d.get('isSidechain'):
            continue
        if d.get('type') == 'system' and d.get('subtype') == 'compact_boundary':
            cortes.append(llamadas_api)
            continue
        m = d.get('message') or {}
        if d.get('type') == 'assistant':
            u = m.get('usage')
            # Claude Code escribe una línea por bloque (razonamiento, texto, herramienta) de la misma respuesta, y
            # todas repiten su `usage`: se cuenta una vez por id de mensaje.
            clave = m.get('id') or d.get('requestId') or d.get('uuid')
            if u and clave in vistos:
                salidas[vistos[clave]] = max(salidas[vistos[clave]], u.get('output_tokens') or 0)
            elif u:
                vistos[clave] = len(salidas)
                llamadas_api += 1
                for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'):
                    usos[k] += u.get(k) or 0
                contextos.append(sum(u.get(k) or 0 for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')))
                salidas.append(u.get('output_tokens') or 0)
                modelos_llamada.append(m['model'] if not (m.get('model') or '<').startswith('<') else None)
            for b in m.get('content') or []:
                if isinstance(b, dict) and b.get('type') == 'tool_use':
                    entrada = b.get('input') or {}
                    usos_tool[b['id']] = (b.get('name', '?'), resumen_entrada(b.get('name'), entrada), json.dumps(entrada, sort_keys=True))
                    archivos_tool[b['id']] = rutas_leidas(b.get('name'), entrada, raiz)
        elif d.get('type') == 'user':
            for b in m.get('content') or [] if isinstance(m.get('content'), list) else []:
                if isinstance(b, dict) and b.get('type') == 'tool_result':
                    t, img = tokens_de(b.get('content'))
                    resultados.append((llamadas_api, b.get('tool_use_id'), t, img, bool(b.get('is_error'))))

    if llamadas_api == 0:
        sys.exit('No hay llamadas en ese periodo (prueba --horas 0)')
    usos['output_tokens'] = sum(salidas)
    for modelo, ctx, sal in zip(modelos_llamada, contextos, salidas):
        if modelo:
            p = por_modelo[('principal', modelo)]
            p[0] += 1; p[1] += ctx; p[2] += sal

    def arrastre(idx):
        # Llamadas posteriores hasta la siguiente compactación: cada una vuelve a leer el resultado.
        fin = next((c for c in cortes if c > idx), llamadas_api)
        return max(fin - idx, 1)

    por_tool = collections.defaultdict(lambda: [0, 0.0, 0.0, 0, 0])  # llamadas, tokens, arrastrados, imágenes, errores
    filas = []
    repetidas = collections.Counter()
    por_archivo = collections.defaultdict(lambda: [0, 0.0, 0.0])  # lecturas, tokens, arrastrados
    for idx, tid, t, img, err in resultados:
        leidos = archivos_tool.get(tid) or []
        for r in leidos:  # una orden que lee varios archivos reparte su resultado entre ellos
            q = por_archivo[r]
            q[0] += 1; q[1] += t / len(leidos); q[2] += t * arrastre(idx) / len(leidos)
        nombre, resumen, completa = usos_tool.get(tid, ('?', '', ''))
        arr = t * arrastre(idx)
        p = por_tool[nombre]
        p[0] += 1; p[1] += t; p[2] += arr; p[3] += img; p[4] += err
        filas.append((arr, t, nombre, resumen, img, err))
        if nombre in ('Read', 'Bash', 'Grep', 'Glob', 'WebFetch'):
            repetidas[(nombre, completa, resumen)] += 1

    total_in = usos['input_tokens'] + usos['cache_creation_input_tokens'] + usos['cache_read_input_tokens']
    print(f'Sesión: {os.path.basename(ruta)}  ·  periodo: {"toda" if not desde else f"desde {desde:%Y-%m-%d %H:%M} UTC" if a.desde else f"últimas {a.horas:g} h"}')
    print(f'Llamadas a la API: {llamadas_api}  ·  compactaciones: {len(cortes)}')
    print(f'Entrada {total_in:,.0f} tokens (caché leída {usos["cache_read_input_tokens"]:,.0f} = '
          f'{100 * usos["cache_read_input_tokens"] / max(total_in, 1):.0f} %, escrita {usos["cache_creation_input_tokens"]:,.0f}, '
          f'sin caché {usos["input_tokens"]:,.0f})  ·  salida {usos["output_tokens"]:,.0f}')
    print(f'Contexto medio por llamada: {total_in / llamadas_api:,.0f} tokens  →  cada llamada de más cuesta eso '
          f'(a precio de caché, ~{total_in / llamadas_api / 10:,.0f} tokens de entrada normal)')
    print(f'Salida media por llamada: {usos["output_tokens"] / llamadas_api:,.0f} tokens (incluye el razonamiento)')
    # Curva entre compactaciones (QA-111): el suelo es el contexto fijo (instrucciones, herramientas, resumen) y el
    # techo, hasta dónde crece antes de compactar. Un techo muy por encima del suelo pide compactar antes.
    tramos, inicio = [], 0
    for c in cortes + [llamadas_api]:
        if c > inicio:
            tramos.append(contextos[inicio:c])
        inicio = c
    # Con --horas, el primer tramo empieza a mitad (sin la compactación que lo abrió): su primera llamada no es un suelo.
    parcial = recortada and (not cortes or cortes[0] > 0) and len(tramos) > 1
    if parcial:
        tramos = tramos[1:]
    if tramos:
        suelos = [t[0] for t in tramos]
        techos = [max(t) for t in tramos]
        print(f'Tramos entre compactaciones: {len(tramos)}  ·  suelo medio {sum(suelos) / len(suelos):,.0f}  ·  techo medio '
              f'{sum(techos) / len(techos):,.0f}  ·  {sum(map(len, tramos)) / len(tramos):,.0f} llamadas por tramo'
              + ('  (sin el primero, que empezó antes del periodo)' if parcial else ''))
        # QA-127: el contexto medio de arriba mezcla tramos con topes de compactación distintos (si el tope cambió en el
        # periodo, la media no cuadra con el techo). Cada tramo por separado, los últimos 8, deja ver el régimen actual.
        print('Por tramo, del más antiguo al último (medio/techo, en miles): ' + '  '.join(
            f'{sum(t) / len(t) / 1000:,.0f}/{max(t) / 1000:,.0f}' for t in tramos[-8:]))
        if parcial:
            sin = [c for t in tramos for c in t]
            print(f'Contexto medio sin el primer tramo: {sum(sin) / len(sin):,.0f} tokens')
    print()
    print('POR HERRAMIENTA (tokens que metió en el contexto · arrastrados en las llamadas siguientes)')
    for nombre, (n, t, arr, img, err) in sorted(por_tool.items(), key=lambda x: -x[1][2])[: a.top]:
        extra = (f' · {img} imágenes' if img else '') + (f' · {err} errores' if err else '')
        print(f'  {nombre:<28} {n:>5} llamadas  {t:>9,.0f} tok  {arr:>13,.0f} arrastrados{extra}')
    print()
    print('RESULTADOS QUE MÁS PESARON (arrastrados)')
    for arr, t, nombre, resumen, img, err in sorted(filas, reverse=True)[: a.top]:
        print(f'  {arr:>12,.0f}  ({t:>7,.0f} tok) {nombre}: {resumen}{" [imagen]" if img else ""}{" [error]" if err else ""}')
    if por_archivo:
        print()
        print('POR ARCHIVO (lecturas con Read o Bash · tokens · arrastrados; una orden con varios archivos se reparte)')
        for r, (n, t, arr) in sorted(por_archivo.items(), key=lambda x: -x[1][2])[: a.top]:
            print(f'  {r[-60:]:<60} {n:>4}×  {t:>9,.0f} tok  {arr:>13,.0f} arrastrados')
    rep = [(n, k) for k, n in repetidas.items() if n > 1]
    if rep:
        print()
        print('REPETIDO (la misma lectura u orden, idéntica, más de una vez)')
        for n, (nombre, _, resumen) in sorted(rep, reverse=True)[: a.top]:
            print(f'  {n:>3}× {nombre}: {resumen}')
    # QA-117: qué modelo hizo qué. Lo mecánico (escribir código con un plan cerrado, buscar, jugar una ronda) puede ir a
    # un subagente con un modelo más barato; el diseño y la revisión, al grande.
    tipos = collections.Counter()
    subs = []  # (descripción, tipo, modelo, respuestas)
    for sub in sorted(glob.glob(os.path.join(os.path.splitext(ruta)[0], 'subagents', '*.jsonl'))):
        try:
            meta = json.load(open(sub[:-len('.jsonl')] + '.meta.json', encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            meta = {}
        tipo = meta.get('agentType') or '?'
        resp = uso_por_modelo(sub, desde, por_modelo, 'subagentes')
        if resp:
            modelo = resp[-1][0]
            tipos[(tipo, modelo)] += 1
            subs.append((meta.get('description') or os.path.basename(sub)[:-len('.jsonl')], tipo, modelo, resp))
    # QA-146: una fila por subagente, con su contexto medio (lo que cuesta cada llamada suya) y su salida. Los totales
    # de arriba son solo de la sesión principal; aquí van los de los subagentes y la suma de todo. QA-154: «arranque»
    # es el contexto de su primera llamada, lo fijo que paga cada subagente antes de hacer nada.
    if subs:
        print()
        print('POR SUBAGENTE (una fila por registro de <sesión>/subagents/)')
        # Hay registros de subagente que solo guardan el `usage` del bloque a medias (2026-10-20: 20 respuestas con 370
        # tokens de salida en total): por debajo de SALIDA_MINIMA por llamada, la salida no se cree y sale «—».
        sin_salida = False
        for desc, tipo, modelo, resp in sorted(subs, key=lambda x: -sum(r[1] for r in x[3]))[: a.top]:
            ent = sum(r[1] for r in resp)
            sal = sum(r[2] for r in resp)
            sal_txt = f'{sal:>9,}' if sal >= SALIDA_MINIMA * len(resp) else f'{"—":>9}'
            sin_salida |= sal < SALIDA_MINIMA * len(resp)
            print(f'  {desc[:34]:<34} {tipo[:15]:<15} {modelo:<20} {len(resp):>4} llamadas  {ent / len(resp):>8,.0f} ctx medio  '
                  f'{resp[0][1]:>7,} arranque  {ent:>12,} entrada  {sal_txt} salida')
        if sin_salida:
            print(f'  «—»: el registro del subagente no guarda la salida final (menos de {SALIDA_MINIMA} por llamada); '
                  f'la salida de los totales se queda corta')
        if len(subs) > a.top:
            print(f'  … y {len(subs) - a.top} más (--top {len(subs)})')
        n_sub = sum(len(x[3]) for x in subs)
        ent_sub = sum(r[1] for x in subs for r in x[3])
        sal_sub = sum(r[2] for x in subs for r in x[3])
        print(f'  Subagentes en total: {len(subs)} registros · {n_sub:,} llamadas · {ent_sub:,} entrada · {sal_sub:,} salida')
        print(f'  Arranque medio: {sum(x[3][0][1] for x in subs) / len(subs):,.0f} tokens (lo que paga cada subagente antes de hacer '
              f'nada: un arreglo de pocas llamadas que la principal ya tiene en contexto sale más barato en ella)')
        print(f'  Sesión + subagentes: {llamadas_api + n_sub:,} llamadas · {total_in + ent_sub:,} entrada · '
              f'{usos["output_tokens"] + sal_sub:,} salida')
    print()
    print('POR MODELO (entrada y salida de la API)')
    for (quien, modelo), (n, ent, sal) in sorted(por_modelo.items(), key=lambda x: (x[0][0] != 'principal', -x[1][1])):
        print(f'  {quien:<10} {modelo:<28} {n:>5} llamadas  {ent:>13,} entrada  {sal:>10,} salida')
    if tipos:
        print('  Subagentes: ' + ' · '.join(f'{n} {t} ({m})' for (t, m), n in tipos.most_common()))


if __name__ == '__main__':
    main()
