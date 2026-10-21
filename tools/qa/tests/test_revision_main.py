"""FLU-1 (retro del 2026-10-21): .claude/hooks/revision-antes-de-main.sh, el gancho que no deja crear un PR a main
sin la marca de revisión del commit que hay en GitHub. Se probó a mano en la revisión; esto lo vigila.

La rama «remota» es un repo desnudo de prueba (`origin`); las consultas a GitHub (`gh api`) las contesta un `gh` falso
con lo que diga `GH_PR` (el PR) y `GH_CI` (sus comprobaciones).
"""
import json
import os
import subprocess
import unittest

from comun import QA, carpeta, escribir, git

RAIZ = os.path.abspath(os.path.join(QA, '..', '..'))
GANCHO = os.path.join(RAIZ, '.claude', 'hooks', 'revision-antes-de-main.sh')
GH_FALSO = '''#!/bin/sh
case "$2" in *check-runs*) printf '%s' "$GH_CI" ;; *) printf '%s' "$GH_PR" ;; esac
'''
VERDE = json.dumps({'check_runs': [{'name': 'qa', 'status': 'completed', 'conclusion': 'success'}]})


class RevisionAntesDeMain(unittest.TestCase):
    def setUp(self):
        self.origen = carpeta()
        git(self.origen, 'init', '-q', '--bare')
        self.repo = carpeta()
        git(self.repo, 'init', '-q', '-b', 'rama')
        escribir(os.path.join(self.repo, 'a.txt'), 'a\n')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-q', '-m', 'a')
        git(self.repo, 'remote', 'add', 'origin', self.origen)
        git(self.repo, 'push', '-q', 'origin', 'rama')
        self.subido = git(self.repo, 'rev-parse', 'HEAD')
        self.bin = carpeta()
        escribir(os.path.join(self.bin, 'gh'), GH_FALSO)
        os.chmod(os.path.join(self.bin, 'gh'), 0o755)

    def gancho(self, herramienta: str, datos: dict, pr: dict | None = None,
               ci: str = VERDE) -> subprocess.CompletedProcess:
        entrada = json.dumps({'tool_name': f'mcp__github__{herramienta}', 'tool_input': datos})
        env = {**os.environ, 'CLAUDE_PROJECT_DIR': self.repo, 'PATH': self.bin + os.pathsep + os.environ['PATH'],
               'GH_PR': json.dumps(pr or {}), 'GH_CI': ci}
        return subprocess.run(['bash', GANCHO], input=entrada, capture_output=True, text=True, env=env)

    def pr(self, base: str = 'main') -> dict:
        return {'base': {'ref': base}, 'head': {'sha': self.subido}}

    def marcar(self, sha: str) -> None:
        escribir(os.path.join(self.repo, '.claude', 'revision-main.sha'), sha + '\n')

    def test_pr_a_otra_base_pasa(self):
        self.assertEqual(self.gancho('create_pull_request', {'base': 'dev', 'head': 'rama'}).returncode, 0)

    def test_pr_a_main_sin_marca_se_bloquea(self):
        r = self.gancho('create_pull_request', {'base': 'main', 'head': 'rama'})
        self.assertEqual(r.returncode, 2)
        self.assertIn('marca: ninguna', r.stderr)

    def test_marca_del_commit_subido_pasa(self):
        self.marcar(self.subido)
        self.assertEqual(self.gancho('create_pull_request', {'base': 'main', 'head': 'rama'}).returncode, 0)

    def test_commit_revisado_sin_subir_se_bloquea(self):
        escribir(os.path.join(self.repo, 'b.txt'), 'b\n')
        git(self.repo, 'add', 'b.txt')
        git(self.repo, 'commit', '-q', '-m', 'b')
        self.marcar(git(self.repo, 'rev-parse', 'HEAD'))
        r = self.gancho('create_pull_request', {'base': 'main', 'head': 'rama'})
        self.assertEqual(r.returncode, 2)
        self.assertIn(self.subido, r.stderr)

    def test_rama_que_no_esta_en_github_se_bloquea(self):
        self.marcar(self.subido)
        r = self.gancho('create_pull_request', {'base': 'main', 'head': 'otra'})
        self.assertEqual(r.returncode, 2)
        self.assertIn('no está en GitHub', r.stderr)

    def test_editar_un_pr_sin_cambiar_la_base_pasa(self):
        r = self.gancho('update_pull_request', {'owner': 'o', 'repo': 'r', 'pullNumber': 1, 'title': 'x'})
        self.assertEqual(r.returncode, 0)

    def test_head_con_dueno_pasa(self):
        self.marcar(self.subido)
        self.assertEqual(self.gancho('create_pull_request', {'base': 'main', 'head': 'yo:rama'}).returncode, 0)

    def test_cambiar_la_base_a_main_pide_la_marca(self):
        datos = {'owner': 'o', 'repo': 'r', 'pullNumber': 1, 'base': 'main'}
        self.assertEqual(self.gancho('update_pull_request', datos, self.pr('dev')).returncode, 2)
        self.marcar(self.subido)
        self.assertEqual(self.gancho('update_pull_request', datos, self.pr('dev')).returncode, 0)

    def test_fusionar_y_fusion_automatica_piden_ci_verde_y_marca(self):
        datos = {'owner': 'o', 'repo': 'r', 'pullNumber': 1}
        corriendo = json.dumps({'check_runs': [{'name': 'qa', 'status': 'in_progress'}]})
        for herramienta in ('merge_pull_request', 'enable_pr_auto_merge'):
            with self.subTest(herramienta):
                self.marcar(self.subido)
                r = self.gancho(herramienta, datos, self.pr(), corriendo)
                self.assertEqual(r.returncode, 2)
                self.assertIn('QA-62', r.stderr)
                self.assertEqual(self.gancho(herramienta, datos, self.pr()).returncode, 0)
                os.remove(os.path.join(self.repo, '.claude', 'revision-main.sha'))
                self.assertEqual(self.gancho(herramienta, datos, self.pr()).returncode, 2)

    def test_fusionar_un_pr_a_otra_base_pasa(self):
        datos = {'owner': 'o', 'repo': 'r', 'pullNumber': 1}
        self.assertEqual(self.gancho('merge_pull_request', datos, self.pr('dev')).returncode, 0)

    def test_otra_herramienta_de_prs_pasa(self):
        datos = {'owner': 'o', 'repo': 'r', 'pullNumber': 1}
        self.assertEqual(self.gancho('update_pull_request_branch', datos, self.pr()).returncode, 0)

    def test_el_matcher_coge_las_cuatro_y_solo_esas(self):
        with open(os.path.join(RAIZ, '.claude', 'settings.json'), encoding='utf-8') as f:
            ajustes = json.load(f)
        matcher = next(h['matcher'] for h in ajustes['hooks']['PreToolUse']
                       if any('revision-antes-de-main' in g['command'] for g in h['hooks']))
        for nombre in ('create_pull_request', 'merge_pull_request', 'enable_pr_auto_merge', 'update_pull_request'):
            self.assertRegex(f'mcp__github__{nombre}', matcher)
        self.assertNotRegex('mcp__github__update_pull_request_branch', matcher)


if __name__ == '__main__':
    unittest.main()
