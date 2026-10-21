"""FLU-1 (retro del 2026-10-21): las tareas del plan se citan por su `INS-n`, no por la numeración vieja
(«fase 3.5»). La renumeración dejó cinco citas viejas en docs/10 y docs/12 que solo vio el `/code-review`.
"""
import os
import re
import subprocess
import unittest

from comun import QA

RAIZ = os.path.abspath(os.path.join(QA, '..', '..'))
VIEJO = re.compile(r'\bfases? \d\.\d')


class IdsDelPlan(unittest.TestCase):
    def test_ningun_documento_cita_la_numeracion_vieja(self):
        archivos = subprocess.run(['git', 'ls-files', '*.md'], cwd=RAIZ, capture_output=True, text=True).stdout.split()
        malas = []
        for ruta in archivos:
            # Las retros cuentan lo que pasó, con las palabras de entonces.
            if ruta.startswith(('docs/registros/', '.claude/')):
                continue
            with open(os.path.join(RAIZ, ruta), encoding='utf-8') as f:
                for n, linea in enumerate(f, 1):
                    if VIEJO.search(linea):
                        malas.append(f'{ruta}:{n}: {linea.strip()}')
        self.assertEqual(malas, [], 'Citar la tarea por su INS-n (docs/05-plan-de-trabajo.md):\n' + '\n'.join(malas))


if __name__ == '__main__':
    unittest.main()
