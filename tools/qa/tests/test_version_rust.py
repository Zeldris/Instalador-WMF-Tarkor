"""FLU-6 (retro de FLU-6): la versión de Rust fijada en app/rust-toolchain.toml y la mínima del workspace
(`[workspace.package] rust-version` de app/Cargo.toml) suben juntas; los miembros la heredan.
"""
import os
import re
import subprocess
import unittest

from comun import QA, leer

RAIZ = os.path.abspath(os.path.join(QA, '..', '..'))
# Un valor de un TOML sencillo, con comillas dobles o simples; sin tomllib, que el job qa del CI (ubuntu-22.04,
# Python 3.10) no trae.
CANAL = re.compile(r'''^channel\s*=\s*["']([^"']+)["']''', re.MULTILINE)
PROPIA = re.compile(r'''^rust-version\s*=\s*["']([^"']+)["']''', re.MULTILINE)


class VersionRust(unittest.TestCase):
    def test_la_minima_del_workspace_es_la_fijada(self):
        canal = CANAL.search(leer(os.path.join(RAIZ, 'app', 'rust-toolchain.toml')))
        self.assertIsNotNone(canal, 'app/rust-toolchain.toml sin `channel = "X.Y.Z"`')
        self.assertRegex(canal.group(1), r'^\d+\.\d+(\.\d+)?$', 'el channel de app/rust-toolchain.toml es una versión')
        fijada = '.'.join(canal.group(1).split('.')[:2])
        minima = PROPIA.search(leer(os.path.join(RAIZ, 'app', 'Cargo.toml')))
        self.assertIsNotNone(minima, 'app/Cargo.toml sin `rust-version` en [workspace.package]')
        self.assertIn(minima.group(1), (fijada, canal.group(1)),
                      f'app/rust-toolchain.toml fija {canal.group(1)}: la rust-version de app/Cargo.toml va con ella')

    def test_los_miembros_la_heredan(self):
        archivos = subprocess.run(['git', 'ls-files', '-z', 'app/*Cargo.toml'], cwd=RAIZ, capture_output=True,
                                  text=True).stdout.split('\0')
        propias = [r for r in archivos if r and r != 'app/Cargo.toml' and PROPIA.search(leer(os.path.join(RAIZ, r)))]
        self.assertEqual(propias, [], 'Con `rust-version.workspace = true`, no una versión propia:\n' + '\n'.join(propias))


if __name__ == '__main__':
    unittest.main()
