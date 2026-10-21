"""FLU-1 (retro del 2026-10-21): .claude/hooks/revision-antes-de-main.sh, el gancho que no deja crear un PR a main
sin la marca de revisión del commit que hay en GitHub. Se probó a mano en la revisión; esto lo vigila.

La rama «remota» es un repo desnudo de prueba (`origin`); las consultas a GitHub (`gh api`) no se prueban aquí.
"""
import json
import os
import subprocess
import unittest

from comun import QA, carpeta, escribir, git

GANCHO = os.path.abspath(os.path.join(QA, '..', '..', '.claude', 'hooks', 'revision-antes-de-main.sh'))


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

    def gancho(self, herramienta: str, datos: dict) -> subprocess.CompletedProcess:
        entrada = json.dumps({'tool_name': f'mcp__github__{herramienta}', 'tool_input': datos})
        return subprocess.run(['bash', GANCHO], input=entrada, capture_output=True, text=True,
                              env={**os.environ, 'CLAUDE_PROJECT_DIR': self.repo})

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


if __name__ == '__main__':
    unittest.main()
