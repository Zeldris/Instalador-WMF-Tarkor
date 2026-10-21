"""QA-116: tools/qa/recuperar.py, con un registro de sesión de prueba (líneas de `comun`, QA-119)."""
import json
import os
import subprocess
import unittest

from comun import QA, aviso, carpeta, compactacion, orden, registro, respuesta, resultado, ruido, texto, usuaria

PARTES = [
    *ruido(),
    usuaria('el aviso dice "Territorio de Clan Serhu"\nen la cabecera'),
    respuesta('m1', 100, {'type': 'thinking', 'thinking': '', 'signature': 'x'}, orden('toolu_a', 'npx vitest run zona')),
    resultado('toolu_a', 'FAIL zona.test.ts: esperaba 3, llegó 4'),
    *compactacion(),
    respuesta('m2', 50, texto('otra cosa de Serhu'), isSidechain=True),
    # Una búsqueda anterior con este script y su resultado no se repiten.
    respuesta('m3', 60, orden('toolu_b', 'python3 tools/qa/recuperar.py "Serhu" --max 3')),
    resultado('toolu_b', 'usuaria: Territorio de Clan Serhu'),
    # Nombrar el script no es llamarlo: un diff que lo menciona sí se busca.
    respuesta('m4', 70, texto('cambio en recuperar.py: «Morvath» con comillas')),
    # Lo que inyecta el sistema en un turno de la usuaria no lo dijo ella.
    usuaria('<system-reminder>aviso de Morvath</system-reminder>'),
    aviso('skill cargada sobre Morvath'),
]


class Recuperar(unittest.TestCase):
    def correr(self, *args: str, entrada: str | None = None, sesion: bool = True) -> subprocess.CompletedProcess:
        ruta = registro(os.path.join(carpeta(), 's.jsonl'), *PARTES)
        return subprocess.run(['python3', os.path.join(QA, 'recuperar.py'), *args, *(['--sesion', ruta] if sesion else [])],
                              input=entrada.replace('RUTA', ruta) if entrada else None, capture_output=True, text=True)

    def test_encuentra_lo_de_antes_de_compactar_sin_resumen_ni_subagentes_ni_busquedas_previas(self):
        # Con comillas y salto de línea en el texto: en la línea JSON van escapados.
        r = self.correr('"Territorio de Clan serhu"\nen|resumen')
        self.assertEqual(r.stdout, '[2026-10-19T10:00] usuaria: el aviso dice "Territorio de Clan Serhu" en la cabecera…\n'
                                   '1 fragmentos con /"Territorio de Clan serhu"\nen|resumen/\n')

    def test_menciones_del_script_y_avisos_del_sistema(self):
        r = self.correr('«Morvath»|aviso de|cargada', '--ancho', '200')
        self.assertEqual(r.stdout, '[2026-10-19T10:00] claude: cambio en recuperar.py: «Morvath» con comillas…\n'
                                   '[2026-10-19T10:00] sistema: <system-reminder>aviso de Morvath</system-reminder>…\n'
                                   '[2026-10-19T10:00] sistema: skill cargada sobre Morvath…\n'
                                   '3 fragmentos con /«Morvath»|aviso de|cargada/\n')

    def test_expresion_o_numero_malos_dan_un_error_legible(self):
        self.assertIn('no vale', self.correr('(').stderr)
        self.assertIn('necesita un número', self.correr('x', '--max', 'y').stderr)

    def test_resultados_de_ordenes_recortados_y_con_tope(self):
        r = self.correr('esperaba|vitest', '--ancho', '12', '--max', '1')
        self.assertIn('resultado: …t.ts: espera…', r.stdout)
        self.assertIn('2 fragmentos con /esperaba|vitest/ (los 1 últimos)', r.stdout)

    def test_estado_cuenta_las_compactaciones_y_dice_como_recuperar(self):
        r = self.correr('--estado')
        self.assertIn('- Compactaciones en esta sesión: 1', r.stdout)
        self.assertIn('python3 tools/qa/recuperar.py "<regex>"', r.stdout)

    def test_estado_desde_el_gancho_lee_el_registro_de_la_entrada(self):
        r = self.correr('--estado', entrada=json.dumps({'transcript_path': 'RUTA', 'source': 'compact'}), sesion=False)
        self.assertIn('- Compactaciones en esta sesión: 1', r.stdout)
        self.assertRegex(r.stdout, r'--sesion \S+s\.jsonl')

    def test_sin_patron_da_la_ayuda(self):
        self.assertEqual(self.correr().returncode, 2)


if __name__ == '__main__':
    unittest.main()
