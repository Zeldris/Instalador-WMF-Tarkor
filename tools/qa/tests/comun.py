"""QA-74: utilidades de los tests de tools/qa (repos de git de prueba en carpetas temporales)."""
import atexit
import itertools
import json
import os
import shutil
import subprocess
import tempfile

QA = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ENV_GIT = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't',
           'GIT_COMMITTER_EMAIL': 't@t', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_SYSTEM': os.devnull}


def git(cwd: str, *args: str) -> str:
    return subprocess.run(['git', *args], cwd=cwd, env=ENV_GIT, check=True, capture_output=True, text=True).stdout.strip()


def escribir(ruta: str, texto: str) -> None:
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, 'w', encoding='utf-8') as f:
        f.write(texto)


def leer(ruta: str) -> str:
    with open(ruta, encoding='utf-8') as f:
        return f.read()


def carpeta() -> str:
    ruta = tempfile.mkdtemp(prefix='qa-test-')
    atexit.register(shutil.rmtree, ruta, True)
    return ruta


# QA-119 (retro del 2026-10-19): líneas de un registro de sesión de Claude Code (`~/.claude/projects/…/*.jsonl`) con la
# forma de las reales, para todos los tests de herramientas que leen registros (`medir.py`, `recuperar.py`). Los tests
# hechos a mano a la medida del código dejaron pasar seis fallos; el que lea registros parte de aquí.
HORA = '2026-10-19T10:00:00.000Z'
_UUID = itertools.count()


def _linea(tipo: str, contenido=None, **extra) -> dict:
    d = {'type': tipo, 'isSidechain': False, 'timestamp': HORA, 'sessionId': 's', 'uuid': f'u{next(_UUID)}'}
    if contenido is not None:
        d['message'] = {'role': tipo, 'content': contenido}
    return {**d, **extra}


def respuesta(id_mensaje: str, contexto: int, *bloques: dict, modelo: str = 'claude-opus-5-5', **extra) -> list:
    """Una respuesta de la API: Claude Code escribe una línea por bloque (razonamiento, texto, herramienta) y todas
    repiten el mismo `id` y `usage`."""
    uso = {'input_tokens': 0, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': contexto, 'output_tokens': 10}
    lineas = []
    for b in bloques or ({'type': 'thinking', 'thinking': '', 'signature': 'x'},):
        d = _linea('assistant', [b], requestId=f'req_{id_mensaje}', **extra)
        d['message'].update(id=id_mensaje, model=modelo, usage=uso)
        lineas.append(d)
    return lineas


def texto(t: str) -> dict:
    return {'type': 'text', 'text': t}


def orden(id_uso: str, comando: str, nombre: str = 'Bash', **entrada) -> dict:
    """Un `tool_use`: en Bash, la orden completa como la escribe el agente (`python3 tools/qa/x.py …`)."""
    return {'type': 'tool_use', 'id': id_uso, 'name': nombre,
            'input': {'command': comando, 'description': 'd', **entrada} if nombre == 'Bash' else entrada}


def resultado(id_uso: str, contenido, **extra) -> dict:
    return _linea('user', [{'type': 'tool_result', 'tool_use_id': id_uso, 'content': contenido}], **extra)


def usuaria(t: str, **extra) -> dict:
    return _linea('user', t, **extra)


def aviso(t: str) -> dict:
    """Lo que Claude Code inyecta en un turno de la usuaria (skills, imágenes, avisos): `isMeta`."""
    return _linea('user', [{'type': 'text', 'text': t}], isMeta=True)


def compactacion() -> list:
    """El corte y el resumen que abre el tramo siguiente."""
    return [_linea('system', subtype='compact_boundary', content='Conversation compacted', level='info'),
            _linea('user', 'This session is being continued… Resumen.', isCompactSummary=True)]


def ruido() -> list:
    """Líneas sin `message` que las herramientas tienen que saltar."""
    return [{'type': 'queue-operation', 'operation': 'enqueue', 'sessionId': 's', 'timestamp': HORA},
            {'type': 'cost-state', 'sessionId': 's', 'totalCostUSD': 1.0}, {'type': 'mode', 'mode': 'auto', 'sessionId': 's'}]


def registro(ruta: str, *partes) -> str:
    """Escribe el registro; cada parte es una línea (dict) o una lista de líneas."""
    lineas = [l for p in partes for l in (p if isinstance(p, list) else [p])]
    escribir(ruta, ''.join(json.dumps(l, ensure_ascii=False) + '\n' for l in lineas))
    return ruta
