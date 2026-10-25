"""opt-tokens de INS-43: `recuperar.py --estado` cuenta también las compactaciones desde que empezó la tarea (la base
con origin/main), no solo las de toda la sesión, para compararlas con el presupuesto de la bitácora."""
import datetime
import importlib.util
import os
import unittest

from comun import QA, carpeta, compactacion, escribir, git, registro, usuaria

_spec = importlib.util.spec_from_file_location(
    'recuperar', os.path.join(QA, '..', '..', '.claude', 'gw', 'scripts', 'recuperar.py'))
recuperar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recuperar)

UTC = datetime.timezone.utc


def a_las(lineas: list, hora: str) -> list:
    return [{**l, 'timestamp': hora} for l in lineas]


class CompactacionesDeLaTarea(unittest.TestCase):
    def setUp(self):
        self.ruta = registro(os.path.join(carpeta(), 's.jsonl'), usuaria('hola'),
                             a_las(compactacion(), '2026-10-25T10:00:00.000Z'),
                             a_las(compactacion(), '2026-10-25T12:00:00.000Z'),
                             a_las(compactacion(), '2026-10-25T14:00:00.000Z'))

    def test_sin_desde_cuenta_toda_la_sesion(self):
        self.assertEqual(recuperar.count_compactions(self.ruta), 3)

    def test_desde_una_hora_solo_cuenta_las_posteriores(self):
        desde = datetime.datetime(2026, 10, 25, 11, 0, tzinfo=UTC)
        self.assertEqual(recuperar.count_compactions(self.ruta, desde), 2)

    def test_la_hora_con_otro_huso_se_compara_bien(self):
        # 13:30+01:00 son las 12:30 UTC: queda fuera la de las 12:00.
        desde = datetime.datetime.fromisoformat('2026-10-25T13:30:00+01:00')
        self.assertEqual(recuperar.count_compactions(self.ruta, desde), 1)

    def test_una_linea_sin_hora_cuenta(self):
        ruta = registro(os.path.join(carpeta(), 's.jsonl'), [{k: v for k, v in l.items() if k != 'timestamp'}
                                                             for l in compactacion()])
        self.assertEqual(recuperar.count_compactions(ruta, datetime.datetime(2030, 1, 1, tzinfo=UTC)), 1)


class InicioDeLaTarea(unittest.TestCase):
    def test_es_la_base_con_origin_main(self):
        repo = carpeta()
        git(repo, 'init', '-q', '-b', 'main')
        escribir(os.path.join(repo, 'a.txt'), 'a')
        git(repo, 'add', '.')
        git(repo, '-c', 'core.hooksPath=/dev/null', 'commit', '-q', '-m', 'base', '--date', '2026-10-25T09:00:00+00:00')
        base = git(repo, 'rev-parse', 'HEAD')
        git(repo, 'update-ref', 'refs/remotes/origin/main', base)
        git(repo, 'checkout', '-q', '-b', 'tarea')
        escribir(os.path.join(repo, 'b.txt'), 'b')
        git(repo, 'add', '.')
        git(repo, '-c', 'core.hooksPath=/dev/null', 'commit', '-q', '-m', 'trabajo')
        sha, inicio = recuperar.task_start(repo)
        self.assertEqual(sha, base[:7])
        self.assertIsNotNone(inicio.tzinfo)

    def test_sin_origin_main_no_hay_inicio(self):
        repo = carpeta()
        git(repo, 'init', '-q', '-b', 'main')
        escribir(os.path.join(repo, 'a.txt'), 'a')
        git(repo, 'add', '.')
        git(repo, '-c', 'core.hooksPath=/dev/null', 'commit', '-q', '-m', 'base')
        self.assertIsNone(recuperar.task_start(repo))


if __name__ == '__main__':
    unittest.main()
