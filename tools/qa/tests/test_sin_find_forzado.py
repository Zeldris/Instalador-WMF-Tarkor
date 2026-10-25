"""INS-43 (retro): `sin-find-forzado.py` rechaza `.find(...)!` en el código del asistente y lo dice con archivo:línea."""
import os
import subprocess
import sys
import unittest

from comun import QA, carpeta, escribir

SCRIPT = os.path.join(QA, 'sin-find-forzado.py')
RAIZ = os.path.abspath(os.path.join(QA, '..', '..'))
FORZADO = 'const a = 1\nconst p = perfiles.find((x) => x.id === id)!\n'
LIMPIO = 'const p = perfiles.find((x) => x.id === id) ?? perfiles[0]\nconst q = lista.at(-1)!\n'


def correr(raiz: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, SCRIPT, raiz], capture_output=True, text=True)


def proyecto(**archivos: str) -> str:
    raiz = carpeta()
    for ruta, texto in archivos.items():
        escribir(os.path.join(raiz, 'app', 'src', ruta.replace('__', '/')), texto)
    return raiz


class SinFindForzado(unittest.TestCase):
    def test_un_find_forzado_falla_y_dice_archivo_y_linea(self):
        r = correr(proyecto(**{'pantallas.tsx': FORZADO}))
        self.assertEqual(r.returncode, 1)
        self.assertIn(os.path.join('app', 'src', 'pantallas.tsx') + ':2:', r.stderr)
        self.assertIn('perfilDe', r.stderr)

    def test_lo_forzado_con_otra_cosa_que_find_o_con_respaldo_pasa(self):
        r = correr(proyecto(**{'tipos.ts': LIMPIO}))
        self.assertEqual((r.returncode, r.stderr), (0, ''))

    def test_los_tests_se_ignoran(self):
        r = correr(proyecto(**{'App.test.tsx': FORZADO, 'otro.test.ts': FORZADO, 'test__ayuda.ts': FORZADO, 'testSetup.ts': FORZADO}))
        self.assertEqual((r.returncode, r.stderr), (0, ''))

    def test_solo_lista_el_codigo_cuando_hay_tests_con_lo_mismo(self):
        r = correr(proyecto(**{'App.test.tsx': FORZADO, 'ejemplo.ts': FORZADO, 'sub__otro.tsx': FORZADO}))
        self.assertEqual(r.returncode, 1)
        self.assertIn(os.path.join('app', 'src', 'ejemplo.ts') + ':2:', r.stderr)
        self.assertIn(os.path.join('app', 'src', 'sub', 'otro.tsx') + ':2:', r.stderr)
        self.assertNotIn('App.test.tsx', r.stderr)

    def test_el_codigo_del_repo_esta_limpio(self):
        r = correr(RAIZ)
        self.assertEqual((r.returncode, r.stderr), (0, ''))


if __name__ == '__main__':
    unittest.main()
