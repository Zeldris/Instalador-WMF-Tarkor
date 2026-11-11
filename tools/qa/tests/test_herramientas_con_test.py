"""QA-113 (retro del 2026-10-19): toda herramienta del proyecto (tools/ y los scripts de las skills) llega con su test.

`agent-map.py`, `md-links.py`, `matriz-pruebas.py` y `medir.py` entraron sin test y el `/code-review` les
encontró seis fallos (cifras dobles en medir.py, bloques de código con sangría, `--generar` que borraba filas).
Cada una tiene su `tests/test_<nombre>.py` (guiones como `_`), salvo las de EXCEPCIONES, que necesitan el juego,
Postgres o una sesión de Claude (en el instalador: vitest, cargo, apt o la rama real) y se prueban al usarlas.
Desde el piloto de Galivelop-workflow (FLU-2) los scripts del flujo viven en `.claude/gw/scripts/` y los prueba
el propio flujo; aquí se miran solo los del proyecto.
"""
import os
import subprocess
import unittest

from comun import QA

RAIZ = os.path.abspath(os.path.join(QA, '..', '..'))
EXCEPCIONES = {
    'tools/qa/en-app.sh': 'corre una orden en app/ del worktree del pre-push (lo prueba cada push)',
    'tools/qa/tests-app.sh': 'corre `vitest related` del asistente y `cargo test` del núcleo',
    'tools/qa/e2e.sh': 'compila la app y corre tauri-driver bajo xvfb (se prueba corriendo los E2E, no con un test)',
    'tools/dev/instalar-entorno.sh': 'instala paquetes de sistema, npm y crates (lo prueba el arranque en la nube)',
}


class HerramientasConTest(unittest.TestCase):
    def test_cada_herramienta_tiene_su_test(self):
        archivos = subprocess.run(['git', 'ls-files', 'tools/*/*.py', 'tools/*/*.sh',
                                   '.claude/skills/*/*.py', '.claude/skills/*/scripts/*.py'],
                                  cwd=RAIZ, capture_output=True, text=True).stdout.split()
        tests = set(os.listdir(os.path.join(QA, 'tests')))

        def tiene_test(ruta):
            # En tools/qa/tests o al lado de la herramienta (QA-137: los de las skills, con su skill).
            nombre = f'test_{os.path.splitext(os.path.basename(ruta))[0].replace("-", "_")}.py'
            return nombre in tests or os.path.exists(os.path.join(RAIZ, os.path.dirname(ruta), nombre))

        sin_test = [a for a in archivos if '/tests/' not in a and not os.path.basename(a).startswith('test_')
                    and a not in EXCEPCIONES and not tiene_test(a)]
        self.assertEqual(sin_test, [], 'herramienta sin tools/qa/tests/test_<nombre>.py (o, si necesita el juego, '
                                       'en EXCEPCIONES con el porqué)')

    def test_las_excepciones_existen(self):
        for nombre in EXCEPCIONES:
            self.assertTrue(os.path.exists(os.path.join(RAIZ, nombre)), f'{nombre} ya no existe: quítala de EXCEPCIONES')


if __name__ == '__main__':
    unittest.main()
