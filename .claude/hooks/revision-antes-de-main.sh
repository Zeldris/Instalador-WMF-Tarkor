#!/bin/bash
# Traído de Tarkor. QA-50 (retro del 2026-10-12): no se crea ni se fusiona un PR a main sin `/code-review
# --max-findings all` del mismo commit (paso 6 de docs/runbooks/skills-y-modelos.md). En Tarkor se saltó en el
# PR #43 y casi en el #44. La marca la deja `tools/qa/revisado.sh` tras la revisión.
# QA-62 (retro del 2026-10-12): al fusionar, además, todas las comprobaciones (CI) del commit de cabeza
# del PR tienen que haber terminado en verde. En Tarkor, el #47 se fusionó con el backend aún corriendo.
entrada="$(cat)"
raiz="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
python3 - "$raiz" "$entrada" <<'PY'
import json, subprocess, sys
raiz, entrada = sys.argv[1], json.loads(sys.argv[2])
herramienta = entrada.get('tool_name', '')
datos = entrada.get('tool_input', {}) or {}
if herramienta.endswith('create_pull_request'):
    if datos.get('base') != 'main':
        sys.exit(0)
    cabeza = subprocess.run(['git', '-C', raiz, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
else:
    # Fusionar: la base y la cabeza son las del PR, no las de este checkout. Si no se pueden
    # consultar, se bloquea (mejor un falso bloqueo que un PR sin revisar en main).
    pr = subprocess.run(
        ['gh', 'api', f"repos/{datos.get('owner')}/{datos.get('repo')}/pulls/{datos.get('pullNumber')}"],
        capture_output=True, text=True,
    )
    try:
        info = json.loads(pr.stdout)
        if info['base']['ref'] != 'main':
            sys.exit(0)
        cabeza = info['head']['sha']
    except (ValueError, KeyError, TypeError):
        cabeza = '(no se pudo consultar el PR)'
    else:
        ci = subprocess.run(
            ['gh', 'api', f"repos/{datos.get('owner')}/{datos.get('repo')}/commits/{cabeza}/check-runs?per_page=100"],
            capture_output=True, text=True,
        )
        try:
            corridas = json.loads(ci.stdout)['check_runs']
        except (ValueError, KeyError, TypeError):
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
                'Espera al aviso del PR (suscrito con subscribe_pr_activity) y fusiona con todo en verde.',
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
    f'commit: {cabeza}). La descripción, con la skill `pr`.',
    file=sys.stderr,
)
sys.exit(2)
PY
