#!/usr/bin/env python3
"""Banco de calidad por pares para `scout-updates` (banco-calidad.md). Solo biblioteca estándar.

Uso:
  banco.py generar <casos.jsonl> --modelo M --salida <salidas.jsonl> [--url U] [--api ollama|openai]
  banco.py pares <salidas.jsonl> <salidas.jsonl> [...] --casos <casos.jsonl> --salida <pares.jsonl> --clave <clave.json> [--semilla N]
  banco.py juzgar <pares.jsonl> --juez M --rubrica <rubrica.md> --salida <veredictos.jsonl> [--url U] [--api ...]
  banco.py resumen <pares.jsonl> <clave.json> <veredictos.jsonl> [--json] [--detalle]

Casos: una línea por caso, {"id", "system"?, "prompt", "contexto"?, "opciones"?: {"temperature", "num_ctx",
"max_tokens", "format"}}; `format` es el JSON Schema de las llamadas estructuradas. Con Ollama va siempre `think: false`. `contexto` es lo que ve el juez (p. ej. la acción del jugador); sin él, los últimos 1500 caracteres
del prompt.
generar: una línea por caso, {"caso", "modelo", "salida", "ms"} o {"caso", "modelo", "error"}.
pares: por caso y por cada pareja de modelos, dos pares a ciegas (A como X y B como X), barajados; los nombres solo
van en la clave.
juzgar: el juez responde {"ganador": "X"|"Y"|"empate", "motivo"}; un par cuya llamada falla sale con "error" y no
cuenta en el resumen. Para juzgar con Claude, la sesión escribe
veredictos.jsonl a mano con ese formato y {"par"}, sin abrir la clave.
resumen: por modelo, victorias (empate = 0,5) y tasa; consistencia = % de casos cuyo ganador no cambia al girar el
par (el que cambia cuenta como empate); sesgo de posición = % de veces que gana X. Con --detalle, además, con el mismo
conteo: cara a cara (tasa de cada modelo contra cada otro), puntos por caso y los motivos de los pares que pierde
cada modelo (para los fallos típicos del informe).
"""
import argparse, itertools, json, random, sys, time, urllib.request

URL_OLLAMA = 'http://localhost:11434'
CONTEXTO_MAX = 1500


def leer_jsonl(ruta):
    with open(ruta, encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]


def escribir_jsonl(ruta, filas):
    with open(ruta, 'w', encoding='utf-8') as f:
        for r in filas:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def llamar_http(url, api, modelo, system, prompt, opciones, formato_json=False, timeout=600):
    """Texto generado por el motor. api: 'ollama' (/api/generate) u 'openai' (/v1/chat/completions)."""
    opciones = opciones or {}
    if api == 'ollama':
        # think: false, como el proyecto: sin él, los modelos con razonamiento lo escriben antes de la respuesta
        cuerpo = {'model': modelo, 'prompt': prompt, 'stream': False, 'think': False, 'options': {}}
        if system:
            cuerpo['system'] = system
        for k in ('temperature', 'num_ctx'):
            if k in opciones:
                cuerpo['options'][k] = opciones[k]
        if 'max_tokens' in opciones:
            cuerpo['options']['num_predict'] = opciones['max_tokens']
        if formato_json:
            cuerpo['format'] = 'json'
        elif 'format' in opciones:
            cuerpo['format'] = opciones['format']
        destino = url.rstrip('/') + '/api/generate'
    else:
        mensajes = ([{'role': 'system', 'content': system}] if system else []) + [{'role': 'user', 'content': prompt}]
        cuerpo = {'model': modelo, 'messages': mensajes}
        for k in ('temperature', 'max_tokens'):
            if k in opciones:
                cuerpo[k] = opciones[k]
        if formato_json:
            cuerpo['response_format'] = {'type': 'json_object'}
        elif 'format' in opciones:
            cuerpo['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'salida', 'schema': opciones['format']}}
        destino = url.rstrip('/') + '/v1/chat/completions'
    pet = urllib.request.Request(destino, json.dumps(cuerpo).encode(), {'Content-Type': 'application/json'})
    with urllib.request.urlopen(pet, timeout=timeout) as r:
        datos = json.load(r)
    return datos['response'] if api == 'ollama' else datos['choices'][0]['message']['content']


def generar(casos, modelo, llamar):
    filas = []
    for c in casos:
        inicio = time.monotonic()
        try:
            salida = llamar(modelo, c.get('system'), c['prompt'], c.get('opciones'))
            filas.append({'caso': c['id'], 'modelo': modelo, 'salida': salida.strip(),
                          'ms': round((time.monotonic() - inicio) * 1000)})
        except Exception as e:  # un caso fallido no tumba la tanda
            filas.append({'caso': c['id'], 'modelo': modelo, 'error': str(e)})
        print('%s %s %s' % (modelo, c['id'], 'error' if 'error' in filas[-1] else '%d ms' % filas[-1]['ms']),
              file=sys.stderr)
    return filas


def contexto(caso):
    return caso.get('contexto') or caso['prompt'][-CONTEXTO_MAX:]


def pares(tandas, casos, semilla=0):
    """tandas: listas de salidas, una por modelo. Devuelve (pares, clave)."""
    por_modelo = {}
    for tanda in tandas:
        for f in tanda:
            if 'salida' in f:
                por_modelo.setdefault(f['modelo'], {})[f['caso']] = f['salida']
    ctx = {c['id']: contexto(c) for c in casos}
    brutos = []
    for a, b in itertools.combinations(sorted(por_modelo), 2):
        for caso in sorted(set(por_modelo[a]) & set(por_modelo[b]) & set(ctx)):
            for x, y in ((a, b), (b, a)):
                brutos.append((caso, x, y))
    random.Random(semilla).shuffle(brutos)
    lista, clave = [], {}
    for i, (caso, x, y) in enumerate(brutos, 1):
        par = 'p%03d' % i
        lista.append({'par': par, 'caso': caso, 'contexto': ctx[caso], 'X': por_modelo[x][caso], 'Y': por_modelo[y][caso]})
        clave[par] = {'X': x, 'Y': y}
    return lista, clave


PROMPT_JUEZ = """Compara dos respuestas a la misma situación según la rúbrica. Ignora cuál va primero y la longitud
salvo que la rúbrica la pida. Responde solo con JSON: {{"ganador": "X" | "Y" | "empate", "motivo": "<una frase>"}}.

Rúbrica:
{rubrica}

Situación:
{contexto}

Respuesta X:
{x}

Respuesta Y:
{y}
"""


def juzgar(lista, juez, rubrica, llamar):
    veredictos = []
    for p in lista:
        try:
            texto = llamar(juez, None, PROMPT_JUEZ.format(rubrica=rubrica, contexto=p['contexto'], x=p['X'], y=p['Y']),
                           {'temperature': 0}, True)
        except Exception as e:  # un par fallido no tira los veredictos ya obtenidos
            veredictos.append({'par': p['par'], 'error': str(e)})
            continue
        try:
            v = json.loads(texto)
        except ValueError:
            v = {}
        v = v if isinstance(v, dict) else {}
        ganador = v.get('ganador') if v.get('ganador') in ('X', 'Y', 'empate') else None
        veredictos.append({'par': p['par'], 'ganador': ganador or 'empate', 'motivo': v.get('motivo', ''),
                           **({} if ganador else {'aviso': 'respuesta del juez ilegible: %s' % texto[:200]})})
    return veredictos


def resumen(lista, clave, veredictos):
    caso_de = {p['par']: p['caso'] for p in lista}
    por_ronda = {}  # (caso, pareja de modelos) -> [modelo ganador o None por empate]
    gana_x = juzgados = 0
    derrotas = {}  # modelo -> pares que pierde, con el motivo del juez
    for v in veredictos:
        par = v['par']
        if par not in clave or 'error' in v:
            continue
        juzgados += 1
        g = v.get('ganador')  # un veredicto escrito a mano sin ganador cuenta como empate, como el ilegible
        gana_x += g == 'X'
        modelos = tuple(sorted(clave[par].values()))
        por_ronda.setdefault((caso_de[par], modelos), []).append(clave[par][g] if g in ('X', 'Y') else None)
        if g in ('X', 'Y'):
            perdedor = clave[par]['Y' if g == 'X' else 'X']
            derrotas.setdefault(perdedor, []).append({'caso': caso_de[par], 'contra': clave[par][g],
                                                      'motivo': v.get('motivo', '')})
    puntos, jugadas = {}, {}
    cara, por_caso = {}, {}
    consistentes = completas = repetidas = 0
    for (caso, modelos), ganadores in por_ronda.items():
        if len(ganadores) > 2:  # el mismo par juzgado otra vez (veredictos añadidos dos veces): no cuenta
            repetidas += 1
            continue
        if len(ganadores) == 2:
            completas += 1
            if ganadores[0] == ganadores[1]:
                consistentes += 1
            else:
                ganadores = [None, None]  # cambia al girarlo: empate
        for g in ganadores:
            for m in modelos:
                jugadas[m] = jugadas.get(m, 0) + 1
                w = 1 if g == m else 0.5 if g is None else 0
                puntos[m] = puntos.get(m, 0) + w
                otro = modelos[1] if m == modelos[0] else modelos[0]
                c = cara.setdefault(m, {}).setdefault(otro, [0, 0])
                c[0] += w
                c[1] += 1
                por_caso.setdefault(caso, {})[m] = por_caso.get(caso, {}).get(m, 0) + w
    return {
        'modelos': {m: {'puntos': puntos[m], 'jugadas': jugadas[m], 'tasa': round(puntos[m] / jugadas[m], 3)}
                    for m in sorted(jugadas, key=lambda m: -puntos[m] / jugadas[m])},
        'consistencia': round(consistentes / completas, 3) if completas else None,
        'sesgo_x': round(gana_x / juzgados, 3) if juzgados else None,
        'juzgados': juzgados, 'sin_juzgar': len(lista) - juzgados, 'repetidas': repetidas,
        'cara_a_cara': {m: {o: round(p / n, 3) for o, (p, n) in sorted(d.items())} for m, d in cara.items()},
        'por_caso': {c: por_caso[c] for c in sorted(por_caso)},
        'derrotas': {m: sorted(d, key=lambda x: x['caso']) for m, d in derrotas.items()},
    }


def imprimir_detalle(res):
    modelos = list(res['modelos'])
    print('\ncara a cara (tasa de la fila contra la columna):')
    print('  %-28s ' % '' + ' '.join('%10s' % m[:10] for m in modelos))
    for m in modelos:
        fila = res['cara_a_cara'].get(m, {})
        print('  %-28s ' % m[:28] + ' '.join('%10s' % (fila[o] if o in fila else '—') for o in modelos))
    print('\npuntos por caso:')
    for caso, d in res['por_caso'].items():
        print('  %-16s ' % caso + ' '.join('%10s' % ('%g' % d[m] if m in d else '—') for m in modelos))
    for m in modelos:
        print('\npierde %s:' % m)
        for x in res['derrotas'].get(m, []):
            print('  %s contra %s: %s' % (x['caso'], x['contra'], x['motivo']))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='orden', required=True)
    g = sub.add_parser('generar')
    g.add_argument('casos')
    g.add_argument('--modelo', required=True)
    g.add_argument('--salida', required=True)
    p = sub.add_parser('pares')
    p.add_argument('salidas', nargs='+')
    p.add_argument('--casos', required=True)
    p.add_argument('--salida', required=True)
    p.add_argument('--clave', required=True)
    p.add_argument('--semilla', type=int, default=0)
    j = sub.add_parser('juzgar')
    j.add_argument('pares')
    j.add_argument('--juez', required=True)
    j.add_argument('--rubrica', required=True)
    j.add_argument('--salida', required=True)
    for s in (g, j):
        s.add_argument('--url', default=URL_OLLAMA)
        s.add_argument('--api', choices=('ollama', 'openai'), default='ollama')
    r = sub.add_parser('resumen')
    r.add_argument('pares')
    r.add_argument('clave')
    r.add_argument('veredictos')
    r.add_argument('--json', action='store_true')
    r.add_argument('--detalle', action='store_true')
    a = ap.parse_args(argv)

    if a.orden in ('generar', 'juzgar'):
        def llamar(modelo, system, prompt, opciones, formato_json=False):
            return llamar_http(a.url, a.api, modelo, system, prompt, opciones, formato_json)
    if a.orden == 'generar':
        escribir_jsonl(a.salida, generar(leer_jsonl(a.casos), a.modelo, llamar))
    elif a.orden == 'pares':
        lista, clave = pares([leer_jsonl(s) for s in a.salidas], leer_jsonl(a.casos), a.semilla)
        escribir_jsonl(a.salida, lista)
        with open(a.clave, 'w', encoding='utf-8') as f:
            json.dump(clave, f, ensure_ascii=False, indent=1)
        print('%d pares' % len(lista))
    elif a.orden == 'juzgar':
        with open(a.rubrica, encoding='utf-8') as f:
            rubrica = f.read()
        escribir_jsonl(a.salida, juzgar(leer_jsonl(a.pares), a.juez, rubrica, llamar))
    else:
        with open(a.clave, encoding='utf-8') as f:
            clave = json.load(f)
        res = resumen(leer_jsonl(a.pares), clave, leer_jsonl(a.veredictos))
        if a.json:
            print(json.dumps(res, ensure_ascii=False, indent=1))
        else:
            for m, d in res['modelos'].items():
                print('%-40s tasa %.3f (%s de %d)' % (m, d['tasa'], d['puntos'], d['jugadas']))
            print('consistencia al girar: %s · gana X: %s · juzgados %d, sin juzgar %d'
                  % (res['consistencia'], res['sesgo_x'], res['juzgados'], res['sin_juzgar']))
            if res['repetidas']:
                print('AVISO: %d pares juzgados más de una vez no cuentan; quita los veredictos repetidos' % res['repetidas'])
            if a.detalle:
                imprimir_detalle(res)


if __name__ == '__main__':
    main()
