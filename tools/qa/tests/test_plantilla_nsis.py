"""INS-44: la plantilla NSIS propia (app/src-tauri/windows/installer.nsi) parte de la de Tauri de la versión de
@tauri-apps/cli en uso; al subirla se rehace la copia y se reaplican los cambios marcados `; TARKOR:`.
"""
import json
import os
import re
import unittest

from comun import QA, leer

RAIZ = os.path.abspath(os.path.join(QA, '..', '..'))
SRC_TAURI = os.path.join(RAIZ, 'app', 'src-tauri')
BASE = re.compile(r'^; tauri-cli base: (\S+)\s*$', re.MULTILINE)


class PlantillaNsis(unittest.TestCase):
    def test_la_version_base_es_la_del_cli(self):
        bloqueado = json.loads(leer(os.path.join(RAIZ, 'app', 'package-lock.json')))
        cli = bloqueado['packages']['node_modules/@tauri-apps/cli']['version']
        base = BASE.search(leer(os.path.join(SRC_TAURI, 'windows', 'installer.nsi')))
        self.assertIsNotNone(base, 'installer.nsi sin la línea `; tauri-cli base: X.Y.Z` en la cabecera')
        self.assertEqual(base.group(1), cli,
                         f'@tauri-apps/cli está en {cli} y la plantilla parte de {base.group(1)}: rehaz la copia de '
                         f'installer.nsi desde el tag tauri-cli-v{cli} de tauri-apps/tauri, reaplica los cambios '
                         'marcados `; TARKOR:` y actualiza la línea `; tauri-cli base:`')

    def test_la_config_apunta_a_una_plantilla_que_existe(self):
        conf = json.loads(leer(os.path.join(SRC_TAURI, 'tauri.conf.json')))
        ruta = conf['bundle']['windows']['nsis'].get('template')
        self.assertTrue(ruta, 'tauri.conf.json sin bundle.windows.nsis.template')
        self.assertTrue(os.path.isfile(os.path.join(SRC_TAURI, ruta)), f'la plantilla {ruta} no existe en app/src-tauri')

    def test_la_plantilla_trae_lo_de_tarkor(self):
        t = leer(os.path.join(SRC_TAURI, 'windows', 'installer.nsi'))
        for pieza in ('--desinstalar', '--info-desinstalar', '/BORRARPARTIDAS', '/BORRARIA', '; TARKOR:'):
            self.assertIn(pieza, t, f'la plantilla NSIS no trae `{pieza}`')
        for resto in ('$(deleteAppData)', 'DeleteAppDataCheckbox'):
            self.assertNotIn(resto, t, f'la plantilla aún trae la casilla de Tauri (`{resto}`)')


if __name__ == '__main__':
    unittest.main()
