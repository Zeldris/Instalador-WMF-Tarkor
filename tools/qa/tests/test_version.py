"""FLU-10: tools/dev/version.py copia la versión de tauri.conf.json, saca las notas de CHANGELOG.md y publica."""
import contextlib
import importlib.util
import io
import os
import unittest

from comun import QA, carpeta, escribir, leer

RAIZ = os.path.abspath(os.path.join(QA, '..', '..'))
_spec = importlib.util.spec_from_file_location('version', os.path.join(RAIZ, 'tools', 'dev', 'version.py'))
version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(version)

ARCHIVOS = {
    'app/src-tauri/tauri.conf.json': '{\n  "productName": "Tarkor",\n  "version": "0.2.0",\n  "identifier": "x"\n}\n',
    'app/package.json': '{\n  "name": "t",\n  "version": "0.1.0",\n  "dependencies": {"a": "1"}\n}\n',
    'app/package-lock.json': ('{\n  "name": "t",\n  "version": "0.1.0",\n  "packages": {\n    "": {\n'
                              '      "version": "0.1.0"\n    },\n    "node_modules/a": {\n      "version": "1.0.0"\n'
                              '    }\n  }\n}\n'),
    'app/Cargo.toml': ('[workspace]\nmembers = ["nucleo"]\n\n[workspace.package]\n# comentario\nversion = "0.1.0"\n'
                       'rust-version = "1.94"\n\n[profile.release]\nversion = "no"\n'),
    'app/Cargo.lock': ('[[package]]\nname = "serde"\nversion = "1.0.0"\n\n[[package]]\nname = "tarkor"\n'
                       'version = "0.1.0"\n\n[[package]]\nname = "tarkor-nucleo"\nversion = "0.1.0"\n'),
    'CHANGELOG.md': ('# Registro\n\nTexto.\n\n## [Unreleased]\n\n### Añadido\n\n- Algo nuevo.\n\n'
                     '## [0.1.0] - 2026-11-14\n\n### Añadido\n\n- Lo primero.\n\n'
                     '[Unreleased]: https://github.com/o/r/compare/v0.1.0...HEAD\n'
                     '[0.1.0]: https://github.com/o/r/releases/tag/v0.1.0\n'),
}


def repo() -> str:
    raiz = carpeta()
    for ruta, texto in ARCHIVOS.items():
        escribir(os.path.join(raiz, ruta), texto)
    return raiz


class Copiar(unittest.TestCase):
    def test_detecta_y_copia_sin_tocar_lo_demas(self):
        raiz = repo()
        malas = version.diferencias(raiz)
        self.assertEqual(len(malas), 6, malas)
        self.assertIn('app/package.json: 0.1.0 (se espera 0.2.0)', malas)
        self.assertEqual(version.copiar(raiz), ['app/Cargo.lock', 'app/Cargo.toml', 'app/package-lock.json',
                                                'app/package.json'])
        self.assertEqual(version.diferencias(raiz), [])
        lock = leer(os.path.join(raiz, 'app/package-lock.json'))
        self.assertIn('"node_modules/a": {\n      "version": "1.0.0"', lock)
        cargo = leer(os.path.join(raiz, 'app/Cargo.toml'))
        self.assertIn('version = "0.2.0"\nrust-version', cargo)
        self.assertIn('[profile.release]\nversion = "no"', cargo)
        self.assertIn('name = "serde"\nversion = "1.0.0"', leer(os.path.join(raiz, 'app/Cargo.lock')))
        self.assertEqual(version.copiar(raiz), [])

    def test_falta_una_copia(self):
        raiz = repo()
        escribir(os.path.join(raiz, 'app/Cargo.lock'), '[[package]]\nname = "tarkor"\nversion = "0.1.0"\n')
        self.assertIn('app/Cargo.lock: no se encuentra la versión (0 de 1)', version.diferencias(raiz))
        with self.assertRaisesRegex(SystemExit, 'Cargo.lock: no se encuentra'):
            version.copiar(raiz)

    def test_todo_o_nada(self):
        raiz = repo()
        escribir(os.path.join(raiz, 'app/Cargo.lock'), '[[package]]\nname = "tarkor"\nversion = "0.1.0"\n')
        with self.assertRaisesRegex(SystemExit, 'Cargo.lock: no se encuentra'):
            version.copiar(raiz, '0.3.0')
        self.assertIn('"version": "0.2.0"', leer(os.path.join(raiz, 'app/src-tauri/tauri.conf.json')))
        self.assertEqual(leer(os.path.join(raiz, 'app/package.json')), ARCHIVOS['app/package.json'])

    def test_version_no_semver(self):
        raiz = repo()
        with self.assertRaisesRegex(SystemExit, 'X.Y.Z'):
            version.copiar(raiz, '1.0')


class Notas(unittest.TestCase):
    def test_saca_la_seccion(self):
        raiz = repo()
        self.assertEqual(version.notas('0.1.0', raiz), '### Añadido\n\n- Lo primero.\n')
        with self.assertRaisesRegex(SystemExit, r'no hay sección ## \[9.9.9\]'):
            version.notas('9.9.9', raiz)

    def test_enlace_en_la_intro_no_corta_la_ultima_seccion(self):
        raiz = repo()
        texto = leer(os.path.join(raiz, 'CHANGELOG.md')).replace('Texto.\n', 'Texto.\n\n[roadmap]: docs/x.md\n')
        escribir(os.path.join(raiz, 'CHANGELOG.md'), texto)
        self.assertEqual(version.notas('0.1.0', raiz), '### Añadido\n\n- Lo primero.\n')

    def test_historico_no_exige_la_version_actual(self):
        raiz = repo()
        with self.assertRaisesRegex(SystemExit, 'no coincide'):
            version.main(['notas', 'v0.1.0'], raiz)
        with self.assertRaisesRegex(SystemExit, 'vX.Y.Z'):
            version.main(['notas', '--historico', '0.1.0'], raiz)
        with self.assertRaisesRegex(SystemExit, r'no hay sección ## \[9.9.9\]'):
            version.main(['notas', '--historico', 'v9.9.9'], raiz)
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            version.main(['notas', '--historico', 'v0.1.0'], raiz)
        self.assertEqual(salida.getvalue(), '### Añadido\n\n- Lo primero.\n')

    def test_tag_distinto_de_la_version(self):
        with self.assertRaisesRegex(SystemExit, 'no coincide'):
            version.main(['notas', 'v9.9.9'])
        with self.assertRaisesRegex(SystemExit, 'vX.Y.Z'):
            version.main(['notas', '0.1.0'])


class Publicar(unittest.TestCase):
    def test_pasa_unreleased_a_la_version_nueva(self):
        raiz = repo()
        cambiados = version.publicar('0.3.0', raiz, fecha='2026-12-01')
        self.assertIn('CHANGELOG.md', cambiados)
        self.assertIn('app/src-tauri/tauri.conf.json', cambiados)
        self.assertEqual(version.actual(raiz), '0.3.0')
        self.assertEqual(version.diferencias(raiz), [])
        texto = leer(os.path.join(raiz, 'CHANGELOG.md'))
        self.assertIn('## [Unreleased]\n\n## [0.3.0] - 2026-12-01\n\n### Añadido\n\n- Algo nuevo.', texto)
        self.assertIn('[Unreleased]: https://github.com/o/r/compare/v0.3.0...HEAD\n'
                      '[0.3.0]: https://github.com/o/r/compare/v0.2.0...v0.3.0\n', texto)
        self.assertEqual(version.notas('0.3.0', raiz), '### Añadido\n\n- Algo nuevo.\n')
        with self.assertRaisesRegex(SystemExit, 'vacía'):
            version.publicar('0.4.0', raiz)
        with self.assertRaisesRegex(SystemExit, 'ya hay sección'):
            version.publicar('0.3.0', raiz)

    def test_no_mayor_que_la_actual(self):
        raiz = repo()
        with self.assertRaisesRegex(SystemExit, '0.2.0 no es mayor que la actual 0.2.0'):
            version.publicar('0.2.0', raiz)
        with self.assertRaisesRegex(SystemExit, '0.1.9 no es mayor que la actual 0.2.0'):
            version.publicar('0.1.9', raiz)
        with self.assertRaisesRegex(SystemExit, 'X.Y.Z'):
            version.publicar('1.0', raiz)

    def test_sin_pie_no_escribe_nada(self):
        raiz = repo()
        sin_pie = ARCHIVOS['CHANGELOG.md'].replace('[Unreleased]: https://github.com/o/r/compare/v0.1.0...HEAD\n', '')
        escribir(os.path.join(raiz, 'CHANGELOG.md'), sin_pie)
        with self.assertRaisesRegex(SystemExit, r'falta la línea del pie `\[Unreleased\]: <base>/compare/vX.Y.Z...HEAD`'):
            version.publicar('0.3.0', raiz)
        self.assertEqual(leer(os.path.join(raiz, 'CHANGELOG.md')), sin_pie)
        self.assertEqual(version.actual(raiz), '0.2.0')
        self.assertEqual(leer(os.path.join(raiz, 'app/package.json')), ARCHIVOS['app/package.json'])


class RepoReal(unittest.TestCase):
    def test_todas_las_copias_coinciden(self):
        self.assertEqual(version.diferencias(), [], 'arreglo: python3 tools/dev/version.py copiar')

    def test_changelog_tiene_unreleased(self):
        self.assertIn('Unreleased', version._secciones(leer(os.path.join(RAIZ, 'CHANGELOG.md'))))


if __name__ == '__main__':
    unittest.main()
