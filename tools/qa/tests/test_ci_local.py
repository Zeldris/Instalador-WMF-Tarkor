"""FLU-3: `tools/qa/ci-local.py`, la CI de GitHub corrida en local mientras está agotada."""
import importlib.util
import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout

from comun import QA, carpeta, escribir, git, leer

_spec = importlib.util.spec_from_file_location('ci_local', os.path.join(QA, 'ci-local.py'))
ci_local = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci_local)

WORKFLOW = """name: Comprobar
on: [push]
jobs:
  linux:
    runs-on: ubuntu-22.04
    defaults:
      run:
        working-directory: app
    steps:
      - uses: actions/checkout@v4
      - name: Dependencias del sistema
        run: sudo apt-get install -y algo
      - run: {uno}
      - name: Dos en bloque
        run: |
          {dos}
          echo bloque >> ../hecho.txt
  windows:
    runs-on: windows-latest
    steps:
      - run: cargo test
  qa:
    runs-on: ubuntu-22.04
    steps:
      - name: Solo en PR
        if: github.event_name == 'pull_request'
        run: echo pr >> hecho.txt
      - run: "echo qa >> hecho.txt"
"""


class CiLocal(unittest.TestCase):
    def setUp(self):
        self.raiz = carpeta()
        os.makedirs(os.path.join(self.raiz, 'app'))
        git(self.raiz, 'init', '-q')
        escribir(os.path.join(self.raiz, 'x.txt'), 'x')
        git(self.raiz, 'add', '-A')
        git(self.raiz, 'commit', '-qm', 'x')
        self.wf = os.path.join(self.raiz, 'comprobar.yml')
        ci_local.RAIZ = self.raiz

    def correr(self, uno='echo uno >> ../hecho.txt', dos='echo dos >> ../hecho.txt', *extra):
        escribir(self.wf, WORKFLOW.format(uno=uno, dos=dos))
        salida, errores = io.StringIO(), io.StringIO()
        with redirect_stdout(salida), redirect_stderr(errores):
            codigo = ci_local.main(['--workflow', self.wf, *extra])
        return codigo, salida.getvalue(), errores.getvalue()

    def test_lee_los_pasos_sin_copiarlos(self):
        jobs = ci_local.leer_jobs(WORKFLOW.format(uno='a', dos='b'))
        self.assertEqual([j['nombre'] for j in jobs], ['linux', 'windows', 'qa'])
        self.assertEqual(jobs[0]['dir'], 'app')
        self.assertEqual([p['run'] for p in jobs[0]['pasos']],
                         [None, 'sudo apt-get install -y algo', 'a', 'b\necho bloque >> ../hecho.txt'])
        self.assertEqual(jobs[2]['pasos'][0]['if'], "github.event_name == 'pull_request'")
        self.assertEqual(jobs[2]['pasos'][1]['run'], 'echo qa >> hecho.txt')

    def test_corre_ubuntu_en_orden_y_salta_apt_pr_y_windows(self):
        codigo, salida, _ = self.correr()
        self.assertEqual(codigo, 0)
        self.assertEqual(leer(os.path.join(self.raiz, 'hecho.txt')).split(), ['uno', 'dos', 'bloque', 'qa'])
        self.assertIn('saltado [linux] Dependencias del sistema: paquetes de sistema', salida)
        self.assertIn("saltado [qa] Solo en PR: solo si github.event_name == 'pull_request'", salida)
        self.assertIn('en verde (3 pasos); sin cubrir: windows (windows-latest)', salida)

    def test_un_paso_que_falla_da_rojo_con_su_nombre(self):
        codigo, salida, errores = self.correr('echo roto >&2; false')
        self.assertEqual(codigo, 1)
        self.assertIn('roto', errores)
        self.assertIn('FALLA [linux] echo roto >&2; false', errores)
        self.assertIn('en rojo ([linux] echo roto >&2; false)', salida)
        # El resto de su job no corre, como en GitHub; los otros jobs, sí.
        self.assertIn('no corrido [linux] Dos en bloque: el job ya falló', salida)
        self.assertEqual(leer(os.path.join(self.raiz, 'hecho.txt')).split(), ['qa'])
        os.remove(os.path.join(self.raiz, 'hecho.txt'))
        # Un bloque con un fallo en medio para ahí (bash -e), como en GitHub.
        codigo, salida, _ = self.correr('true', 'false')
        self.assertEqual(codigo, 1)
        self.assertNotIn('bloque', leer(os.path.join(self.raiz, 'hecho.txt')))
        self.assertIn('en rojo ([linux] Dos en bloque)', salida)

    def test_apuntar_deja_fecha_commit_y_resultado(self):
        sha = git(self.raiz, 'rev-parse', '--short', 'HEAD')
        self.correr('true', 'true', '--apuntar')
        registro = leer(os.path.join(self.raiz, ci_local.REGISTRO))
        self.assertIn('# CI en local', registro)
        self.assertRegex(registro, rf'- \d{{4}}-\d\d-\d\d · `{sha}` · en verde \(3 pasos\); sin cubrir: windows')
        escribir(os.path.join(self.raiz, 'x.txt'), 'cambiado')
        self.correr('true', 'true', '--apuntar')
        registro = leer(os.path.join(self.raiz, ci_local.REGISTRO))
        self.assertEqual(registro.count('# CI en local'), 1)
        self.assertIn(f'`{sha}` (con cambios sin commit)', registro)


if __name__ == '__main__':
    unittest.main()
