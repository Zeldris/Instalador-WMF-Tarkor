"""Retro de INS-47 + FLU-9 (2026-11-14): cada flujo de `.github/workflows/` se carga como YAML y tiene `jobs`.

Un nombre de paso con «: » sin comillas dejó `app.yml` sin cargar (27d57a3): GitHub no arranca un flujo roto y no
sale nada en rojo, así que el fallo solo se ve echando en falta la ejecución.
"""
import glob
import os
import unittest

import yaml

from comun import QA

RAIZ = os.path.abspath(os.path.join(QA, '..', '..'))


class WorkflowsYaml(unittest.TestCase):
    def test_cada_flujo_carga_y_tiene_jobs(self):
        rutas = sorted(glob.glob(os.path.join(RAIZ, '.github', 'workflows', '*.y*ml')))
        self.assertTrue(rutas, 'no hay flujos en .github/workflows')
        for ruta in rutas:
            with self.subTest(flujo=os.path.basename(ruta)):
                with open(ruta, encoding='utf-8') as f:
                    datos = yaml.safe_load(f)
                self.assertIsInstance(datos, dict)
                self.assertIn('jobs', datos)


if __name__ == '__main__':
    unittest.main()
