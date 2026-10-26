"""FLU-6 (retro de FLU-6): la versión de Rust fijada en app/rust-toolchain.toml y el `rust-version` de cada miembro
del workspace suben juntos. Están en tres sitios y solo los unía un comentario.
"""
import os
import re
import unittest

from comun import QA

APP = os.path.abspath(os.path.join(QA, '..', '..', 'app'))


def valor(ruta: str, patron: str) -> str | None:
    """Un valor de un TOML sencillo; sin tomllib, que el CI (ubuntu-22.04, Python 3.10) no trae."""
    with open(os.path.join(APP, ruta), encoding='utf-8') as f:
        m = re.search(patron, f.read(), re.MULTILINE)
    return m.group(1) if m else None


class VersionRust(unittest.TestCase):
    def test_rust_version_de_cada_miembro_es_la_fijada(self):
        canal = valor('rust-toolchain.toml', r'^channel\s*=\s*"([^"]+)"')
        fijada = '.'.join(canal.split('.')[:2])
        miembros = re.findall(r'"([^"]+)"', valor('Cargo.toml', r'^members\s*=\s*\[([^\]]*)\]'))
        self.assertTrue(miembros, 'app/Cargo.toml sin members')
        distintas = []
        for miembro in miembros:
            v = valor(os.path.join(miembro, 'Cargo.toml'), r'^rust-version\s*=\s*"([^"]+)"')
            if v != fijada:
                distintas.append(f'app/{miembro}/Cargo.toml: rust-version = {v!r}')
        self.assertEqual(distintas, [], f'app/rust-toolchain.toml fija {canal}; el rust-version de cada miembro '
                                        f'tiene que ser {fijada!r}:\n' + '\n'.join(distintas))


if __name__ == '__main__':
    unittest.main()
