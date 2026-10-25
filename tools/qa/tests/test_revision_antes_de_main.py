"""Parche local de `.claude/gw/scripts/revision-antes-de-main.sh` (2026-10-25): con la CI de GitHub sin arrancar
(aviso de pago o de tope de gasto), la fusión pasa si `docs/registros/ci-local.md` tiene en verde la cabeza del PR o
un antecesor con solo contenido después. El gancho corre de verdad, con un `gh` falso que da las respuestas de la API.
"""
import json
import os
import shutil
import stat
import subprocess
import unittest

from comun import ENV_GIT, carpeta, escribir, git

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
SIN_ARRANCAR = ("The job was not started because recent account payments have failed or your spending limit needs "
                "to be increased. Please check the 'Billing & plans' section in your settings")
GH_FALSO = '''#!/usr/bin/env python3
import json, sys
respuestas = json.load(open(%r))
ruta = sys.argv[-1]
if ruta not in respuestas:
    sys.exit("gh falso: sin respuesta para " + ruta)
print(json.dumps(respuestas[ruta]))
'''


class CiSinArrancar(unittest.TestCase):
    def setUp(self):
        self.d = carpeta()
        origen, self.w = os.path.join(self.d, 'origin.git'), os.path.join(self.d, 'w')
        git(self.d, 'init', '-q', '--bare', '-b', 'main', origen)
        git(self.d, 'clone', '-q', origen, self.w)
        git(self.w, 'checkout', '-q', '-b', 'main')
        for parte in ('.claude/gw/scripts', '.claude/gw/schema'):
            shutil.copytree(os.path.join(RAIZ, parte), os.path.join(self.w, parte),
                            ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy(os.path.join(RAIZ, '.claude', 'gw.json'), os.path.join(self.w, '.claude'))
        escribir(os.path.join(self.w, 'app.txt'), 'uno\n')
        self.commit('base')
        git(self.w, 'push', '-q', 'origin', 'main')
        self.bin = os.path.join(self.d, 'bin')
        os.makedirs(self.bin)
        gh = os.path.join(self.bin, 'gh')
        escribir(gh, GH_FALSO % os.path.join(self.d, 'api.json'))
        os.chmod(gh, os.stat(gh).st_mode | stat.S_IEXEC)

    def commit(self, mensaje):
        git(self.w, 'add', '-A')
        git(self.w, 'commit', '-qm', mensaje)
        return git(self.w, 'rev-parse', 'HEAD')

    def rama(self, codigo_tras_ci_local=False):
        """feat: código, la línea de ci-local.md que lo da en verde y la marca de revisión; devuelve la cabeza."""
        git(self.w, 'checkout', '-q', '-b', 'feat')
        escribir(os.path.join(self.w, 'app.txt'), 'dos\n')
        verde = self.commit('código')
        escribir(os.path.join(self.w, 'docs', 'registros', 'ci-local.md'),
                 f'# CI en local\n- 2026-10-25 · `{verde[:7]}` · en verde (9 pasos); sin cubrir: windows\n')
        revisado = self.commit('ci-local')
        if codigo_tras_ci_local:
            escribir(os.path.join(self.w, 'app.txt'), 'tres\n')
            revisado = self.commit('más código')
        escribir(os.path.join(self.w, 'docs', 'registros', 'revisado.txt'), revisado + '\n')
        cabeza = self.commit('marca')
        git(self.w, 'push', '-q', 'origin', 'feat')
        return cabeza

    def fusionar(self, cabeza, aviso=SIN_ARRANCAR):
        api = {'repos/o/r': {},
               'repos/o/r/pulls/6': {'base': {'ref': 'main'}, 'head': {'sha': cabeza, 'ref': 'feat'}, 'state': 'open'},
               f'repos/o/r/commits/{cabeza}/check-runs?per_page=100&page=1':
                   {'total_count': 1, 'check_runs': [{'id': 1, 'name': 'linux', 'status': 'completed',
                                                      'conclusion': 'failure'}]},
               f'repos/o/r/commits/{cabeza}/status?per_page=100': {'statuses': []},
               'repos/o/r/check-runs/1/annotations': [{'message': aviso}]}
        escribir(os.path.join(self.d, 'api.json'), json.dumps(api))
        evento = {'tool_name': 'mcp__github__merge_pull_request',
                  'tool_input': {'owner': 'o', 'repo': 'r', 'pullNumber': 6}}
        env = {k: v for k, v in ENV_GIT.items() if k not in ('GITHUB_TOKEN', 'GH_TOKEN')}
        env['PATH'] = self.bin + os.pathsep + env['PATH']
        return subprocess.run(['bash', os.path.join(self.w, '.claude', 'gw', 'scripts', 'revision-antes-de-main.sh')],
                              input=json.dumps(evento), env=env, cwd=self.w, capture_output=True, text=True)

    def test_ci_local_en_verde_deja_fusionar(self):
        r = self.fusionar(self.rama())
        self.assertEqual((r.returncode, r.stderr), (0, ''))

    def test_codigo_tras_ci_local_bloquea(self):
        r = self.fusionar(self.rama(codigo_tras_ci_local=True))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn('GitHub did not start the CI', r.stderr)
        self.assertIn('ci-local.py --apuntar', r.stderr)

    def test_un_fallo_de_verdad_no_se_salta(self):
        r = self.fusionar(self.rama(), aviso='Process completed with exit code 1.')
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn('is not green: linux: failure', r.stderr)


if __name__ == '__main__':
    unittest.main()
