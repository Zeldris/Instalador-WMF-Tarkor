import json, os, sys, unittest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import banco


class BancoTest(unittest.TestCase):
    CASOS = [{'id': 'c1', 'prompt': 'x' * 2000}, {'id': 'c2', 'prompt': 'p', 'contexto': 'abre la puerta'}]

    def test_generar_con_error(self):
        def llamar(modelo, system, prompt, opciones):
            if prompt == 'p':
                raise OSError('caído')
            return ' hola '
        filas = banco.generar(self.CASOS, 'm', llamar)
        self.assertEqual(filas[0]['salida'], 'hola')
        self.assertEqual(filas[1], {'caso': 'c2', 'modelo': 'm', 'error': 'caído'})

    def tandas(self):
        return [[{'caso': c, 'modelo': m, 'salida': '%s-%s' % (m, c)} for c in ('c1', 'c2')] for m in ('a', 'b')]

    def test_pares_dos_ordenes_a_ciegas(self):
        lista, clave = banco.pares(self.tandas(), self.CASOS, semilla=1)
        self.assertEqual(len(lista), 4)
        for p in lista:
            self.assertEqual(set(p), {'par', 'caso', 'contexto', 'X', 'Y'})
            self.assertEqual(p['X'], '%s-%s' % (clave[p['par']]['X'], p['caso']))
        ordenes = {(p['caso'], clave[p['par']]['X']) for p in lista}
        self.assertEqual(ordenes, {('c1', 'a'), ('c1', 'b'), ('c2', 'a'), ('c2', 'b')})
        self.assertEqual(len(next(p for p in lista if p['caso'] == 'c1')['contexto']), banco.CONTEXTO_MAX)
        self.assertEqual(next(p for p in lista if p['caso'] == 'c2')['contexto'], 'abre la puerta')

    def test_juzgar_y_resumen(self):
        lista, clave = banco.pares(self.tandas(), self.CASOS)

        # el juez prefiere siempre a 'a' en c1; en c2 elige siempre X (sesgo de posición)
        def juez(modelo, system, prompt, opciones, formato_json):
            par = next(p for p in lista if 'Respuesta X:\n%s\n' % p['X'] in prompt and 'Respuesta Y:\n%s\n' % p['Y'] in prompt)
            if par['caso'] == 'c2':
                return '{"ganador": "X", "motivo": "primero"}'
            return json.dumps({'ganador': 'X' if clave[par['par']]['X'] == 'a' else 'Y'})
        veredictos = banco.juzgar(lista, 'juez', 'rúbrica', juez)
        res = banco.resumen(lista, clave, veredictos)
        self.assertEqual(res['modelos']['a'], {'puntos': 3.0, 'jugadas': 4, 'tasa': 0.75})
        self.assertEqual(res['modelos']['b']['tasa'], 0.25)
        self.assertEqual(res['consistencia'], 0.5)
        self.assertEqual(res['sesgo_x'], 0.75)
        # detalle, con el mismo conteo: el par de c2 cambia al girarlo y es empate
        self.assertEqual(res['cara_a_cara'], {'a': {'b': 0.75}, 'b': {'a': 0.25}})
        self.assertEqual(res['por_caso'], {'c1': {'a': 2, 'b': 0}, 'c2': {'a': 1.0, 'b': 1.0}})
        self.assertEqual(sorted(x['caso'] for x in res['derrotas']['b']), ['c1', 'c1', 'c2'])
        self.assertEqual(sorted(x['caso'] for x in res['derrotas']['a']), ['c2'])
        self.assertEqual(res['repetidas'], 0)
        # un veredicto repetido no cuenta dos veces y se avisa; uno sin ganador es empate
        res = banco.resumen(lista, clave, veredictos + veredictos[:1] + [{'par': veredictos[1]['par']}])
        self.assertGreaterEqual(res['repetidas'], 1)
        self.assertLess(res['modelos'].get('a', {}).get('jugadas', 0), 5)

    def test_juez_ilegible_es_empate(self):
        lista, clave = banco.pares(self.tandas(), self.CASOS)
        v = banco.juzgar(lista[:1], 'juez', 'r', lambda *a: 'no sé')
        self.assertEqual(v[0]['ganador'], 'empate')
        self.assertIn('ilegible', v[0]['aviso'])
        res = banco.resumen(lista, clave, v)
        self.assertEqual(res['sin_juzgar'], 3)
        self.assertEqual(banco.juzgar(lista[:1], 'juez', 'r', lambda *a: '[1]')[0]['ganador'], 'empate')

    def test_juez_caido_no_pierde_lo_juzgado(self):
        lista, clave = banco.pares(self.tandas(), self.CASOS)

        def juez(*a):
            if juez.n == 1:
                raise OSError('timeout')
            juez.n += 1
            return '{"ganador": "X"}'
        juez.n = 0
        v = banco.juzgar(lista[:2], 'juez', 'r', juez)
        self.assertEqual(v[1], {'par': lista[1]['par'], 'error': 'timeout'})
        self.assertEqual(banco.resumen(lista, clave, v)['juzgados'], 1)

if __name__ == '__main__':
    unittest.main()
