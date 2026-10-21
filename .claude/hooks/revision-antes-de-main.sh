#!/bin/bash
# Traído de Tarkor. QA-50 (retro del 2026-10-12): no se crea ni se fusiona un PR a main sin `/code-review
# --max-findings all` del mismo commit (paso 6 de docs/runbooks/skills-y-modelos.md). En Tarkor se saltó en el
# PR #43 y casi en el #44. La marca la deja `tools/qa/revisado.sh` tras la revisión.
# QA-62 (retro del 2026-10-12): al fusionar, además, todas las comprobaciones (CI) del commit de cabeza
# del PR tienen que haber terminado en verde. En Tarkor, el #47 se fusionó con el backend aún corriendo.
# FLU-1 (revisión del flujo en el instalador): la cabeza de un PR nuevo es la de la rama en GitHub, no la
# del checkout; la fusión automática cuenta como fusionar, y cambiar la base a main, como crear.
entrada="$(cat)"
raiz="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
python3 - "$raiz" "$entrada" <<'PY'
import json, subprocess, sys
raiz, entrada = sys.argv[1], json.loads(sys.argv[2])
herramienta = entrada.get('tool_name', '')
datos = entrada.get('tool_input', {}) or {}


def gh(ruta):
    r = subprocess.run(['gh', 'api', ruta], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


repo = f"repos/{datos.get('owner')}/{datos.get('repo')}"
if herramienta.endswith('create_pull_request'):
    if datos.get('base') != 'main':
        sys.exit(0)
    # Un commit revisado pero sin subir no cuenta: se mira lo que hay en GitHub.
    remota = subprocess.run(
        ['git', '-C', raiz, 'ls-remote', 'origin', f"refs/heads/{datos.get('head', '')}"],
        capture_output=True, text=True,
    ).stdout.split()
    cabeza = remota[0] if remota else f"(la rama {datos.get('head')} no está en GitHub)"
elif herramienta.endswith('update_pull_request'):
    if datos.get('base') != 'main':
        sys.exit(0)
    info = gh(f"{repo}/pulls/{datos.get('pullNumber')}")
    try:
        cabeza = info['head']['sha']
    except (KeyError, TypeError):
        cabeza = '(no se pudo consultar el PR)'
else:
    # Fusionar o activar la fusión automática: la base y la cabeza son las del PR, no las de este
    # checkout. Si no se pueden consultar, se bloquea (mejor un falso bloqueo que un PR sin revisar en main).
    info = gh(f"{repo}/pulls/{datos.get('pullNumber')}")
    try:
        if info['base']['ref'] != 'main':
            sys.exit(0)
        cabeza = info['head']['sha']
    except (KeyError, TypeError):
        cabeza = '(no se pudo consultar el PR)'
    else:
        ci = gh(f"{repo}/commits/{cabeza}/check-runs?per_page=100")
        try:
            corridas = ci['check_runs']
        except (KeyError, TypeError):
            corridas = None
        if not corridas:
            pendiente = ['no se pudieron leer las comprobaciones' if corridas is None else 'el CI aún no ha empezado']
        else:
            pendiente = [
                f"{c['name']}: {c.get('conclusion') or c['status']}"
                for c in corridas
                if c['status'] != 'completed' or c.get('conclusion') not in ('success', 'skipped', 'neutral')
            ]
        if pendiente:
            print(
                f'Bloqueado (QA-62): el CI del PR no está en verde ({"; ".join(pendiente)}). '
                'Espera al aviso del PR (suscrito con subscribe_pr_activity) y fusiona con todo en verde; '
                'la fusión automática tampoco se activa antes.',
                file=sys.stderr,
            )
            sys.exit(2)
try:
    marca = open(f'{raiz}/.claude/revision-main.sha').read().strip()
except OSError:
    marca = ''
if marca and marca == cabeza:
    sys.exit(0)
print(
    f'Bloqueado (QA-50): antes de un PR a main, `/code-review --max-findings all` del diff contra main, '
    f'arreglar lo que encuentre, subirlo y marcar con `bash tools/qa/revisado.sh` (marca: {marca or "ninguna"}, '
    f'commit en GitHub: {cabeza}). La descripción, con la skill `pr`.',
    file=sys.stderr,
)
sys.exit(2)
PY
