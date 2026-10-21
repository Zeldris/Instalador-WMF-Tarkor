"""QA-120 (retro del 2026-10-19): los ganchos de `.claude/settings.json`.

`session-start.sh` corría también al compactar (sin `matcher`) y metía la instalación del entorno en el contexto tras
cada compactación. Cada `SessionStart` dice cuándo corre, al compactar solo corre `recuperar.py --estado` (QA-116), y
cada orden apunta a un archivo del repo que existe.
"""
import json
import os
import re
import unittest

from comun import QA

RAIZ = os.path.abspath(os.path.join(QA, '..', '..'))


class Settings(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(RAIZ, '.claude', 'settings.json'), encoding='utf-8') as f:
            self.ganchos = json.load(f).get('hooks', {})

    def test_cada_inicio_dice_cuando_corre_y_al_compactar_solo_el_estado(self):
        inicio = self.ganchos.get('SessionStart', [])
        self.assertTrue(inicio)
        for entrada in inicio:
            self.assertIn('matcher', entrada, entrada)
            ordenes = [h['command'] for h in entrada['hooks']]
            if 'compact' in entrada['matcher'].split('|'):
                self.assertEqual(ordenes, ['python3 "$CLAUDE_PROJECT_DIR/tools/qa/recuperar.py" --estado'])
        self.assertTrue(any('compact' in e['matcher'].split('|') for e in inicio))

    def test_cada_orden_apunta_a_un_archivo_que_existe(self):
        for evento, entradas in self.ganchos.items():
            for entrada in entradas:
                for h in entrada['hooks']:
                    rutas = re.findall(r'\$CLAUDE_PROJECT_DIR/([^"\s]+)', h.get('command', ''))
                    self.assertTrue(rutas, f'{evento}: {h}')
                    for r in rutas:
                        self.assertTrue(os.path.isfile(os.path.join(RAIZ, r)), f'{evento}: {r} no existe')


if __name__ == '__main__':
    unittest.main()
