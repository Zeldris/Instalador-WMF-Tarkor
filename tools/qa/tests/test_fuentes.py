"""INS-67: el asistente lleva solo los subconjuntos latin y latin-ext de Cinzel e Inter, y solo en woff2.

Importar `@fontsource/<familia>/<peso>.css` en `app/src/estilos.css` vuelve a meter cirílico, griego, vietnamita
y los .woff (54 archivos y ~1,5 MB frente a 12 y 260 KB; cifras medidas el 2026-11-15 con @fontsource 5.3.0, la de
app/package-lock.json). Va en Python porque vitest deja vacíos los .css.
"""
import os
import re
import subprocess
import sys
import unittest

from comun import QA

SRC = os.path.abspath(os.path.join(QA, '..', '..', 'app', 'src'))


def leer(nombre):
    with open(os.path.join(SRC, nombre), encoding='utf-8') as f:
        return f.read()


class Fuentes(unittest.TestCase):
    def test_estilos_no_importa_las_hojas_completas(self):
        estilos = leer('estilos.css')
        self.assertNotRegex(estilos, r"@import '@fontsource/")
        self.assertIn("@import './fuentes.css'", estilos)

    def test_solo_latin_en_woff2_con_unicode_range(self):
        fuentes = leer('fuentes.css')
        archivos = re.findall(r'url\(([^)]+)\)', fuentes)
        self.assertEqual(len(archivos), 12)
        for a in archivos:
            self.assertRegex(a, r'-latin(-ext)?-\d00-normal\.woff2$')
            self.assertTrue(os.path.isfile(os.path.normpath(os.path.join(SRC, a))), a)
        self.assertEqual(fuentes.count('unicode-range:'), 12)

    def test_fuentes_css_coincide_con_lo_generado(self):
        raiz = os.path.abspath(os.path.join(SRC, '..', '..'))
        if not os.path.isdir(os.path.join(raiz, 'app', 'node_modules', '@fontsource')):
            self.skipTest('falta app/node_modules/@fontsource (npm ci)')
        r = subprocess.run([sys.executable, os.path.join(raiz, 'tools', 'dev', 'fuentes.py'), '--check'],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == '__main__':
    unittest.main()
