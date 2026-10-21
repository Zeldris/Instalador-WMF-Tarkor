"""QA-113 (retro del 2026-10-19): toda herramienta de tools/qa (y medir.py de opt-tokens) llega con su test.

`mapa-agente.py`, `enlaces-md.py`, `matriz-pruebas.py` y `medir.py` entraron sin test y el `/code-review` les
encontró seis fallos (cifras dobles en medir.py, bloques de código con sangría, `--generar` que borraba filas).
Cada una tiene su `tests/test_<nombre>.py` (guiones como `_`), salvo las de EXCEPCIONES, que necesitan el juego,
Postgres o una sesión de Claude (en el instalador: vitest, cargo o la rama real) y se prueban al usarlas.
"""
import os
import subprocess
import unittest

from comun import QA

RAIZ = os.path.abspath(os.path.join(QA, '..', '..'))
EXCEPCIONES = {
    'revisado.sh': 'marca la revisión de la rama real antes del PR (la comprueba el gancho de QA-50)',
    'rojo-sin-arreglo.sh': 'corre un test de vitest con y sin el arreglo',
    'tests-relacionados.sh': 'corre `vitest related` del asistente y `cargo test` del núcleo',
}


class HerramientasConTest(unittest.TestCase):
    def test_cada_herramienta_tiene_su_test(self):
        archivos = subprocess.run(['git', 'ls-files', 'tools/qa/*.py', 'tools/qa/*.sh', '.claude/skills/*/*.py'],
                                  cwd=RAIZ, capture_output=True, text=True).stdout.split()
        tests = set(os.listdir(os.path.join(QA, 'tests')))

        def tiene_test(ruta):
            # En tools/qa/tests o al lado de la herramienta (QA-137: los de las skills, con su skill).
            nombre = f'test_{os.path.splitext(os.path.basename(ruta))[0].replace("-", "_")}.py'
            return nombre in tests or os.path.exists(os.path.join(RAIZ, os.path.dirname(ruta), nombre))

        sin_test = [a for a in archivos if '/tests/' not in a and not os.path.basename(a).startswith('test_')
                    and os.path.basename(a) not in EXCEPCIONES and not tiene_test(a)]
        self.assertEqual(sin_test, [], 'herramienta sin tools/qa/tests/test_<nombre>.py (o, si necesita el juego, '
                                       'en EXCEPCIONES con el porqué)')

    def test_las_excepciones_existen(self):
        for nombre in EXCEPCIONES:
            self.assertTrue(os.path.exists(os.path.join(QA, nombre)), f'{nombre} ya no existe: quítala de EXCEPCIONES')


if __name__ == '__main__':
    unittest.main()
