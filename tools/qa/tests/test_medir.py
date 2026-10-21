"""QA-113: .claude/skills/opt-tokens/medir.py (QA-111), con un registro de sesión de prueba (líneas de `comun`, QA-119)."""
import datetime as dt
import json
import os
import subprocess
import unittest

from comun import QA, carpeta, compactacion, escribir, orden, registro, respuesta, resultado, ruido, texto

MEDIR = os.path.join(QA, '..', '..', '.claude', 'skills', 'opt-tokens', 'medir.py')


class Medir(unittest.TestCase):
    def medir(self, partes: list, subagentes: dict | None = None, horas: str = '0', extra: tuple = ()) -> str:
        d = carpeta()
        ruta = registro(os.path.join(d, 's.jsonl'), *partes)
        for nombre, (tipo, sub) in (subagentes or {}).items():
            escribir(os.path.join(d, 's', 'subagents', f'{nombre}.meta.json'), json.dumps(tipo if isinstance(tipo, dict) else {'agentType': tipo}))
            registro(os.path.join(d, 's', 'subagents', f'{nombre}.jsonl'), *sub)
        r = subprocess.run(['python3', MEDIR, '--sesion', ruta, '--horas', horas, *extra], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_cuenta_una_vez_cada_respuesta_y_saca_los_tramos(self):
        salida = self.medir([
            *ruido(),
            # Dos bloques de la misma respuesta: dos líneas con el mismo uso, que cuenta una vez.
            respuesta('m1', 100, texto('pienso'), orden('t1', '', nombre='Read', file_path='/a')),
            resultado('t1', 'x' * 350),
            respuesta('m2', 300),
            *compactacion(),
            respuesta('m3', 50),
            respuesta('s', 9999, isSidechain=True),
        ])
        self.assertIn('Llamadas a la API: 3  ·  compactaciones: 1', salida)
        self.assertIn('Entrada 450 tokens', salida)
        self.assertIn('Tramos entre compactaciones: 2  ·  suelo medio 75  ·  techo medio 175', salida)
        # El resultado de Read (100 tokens) se arrastra a la llamada siguiente del tramo: 1 llamada.
        self.assertRegex(salida, r'Read\s+1 llamadas\s+100 tok\s+100 arrastrados')

    def test_por_archivo_junta_read_y_bash_con_la_ruta_desde_la_raiz(self):
        # QA-175: Read con ruta absoluta, Bash tras `cd backend &&` con ruta relativa a esa carpeta, y una orden que
        # lee dos archivos (se reparte); `git status` no lee ninguno.
        raiz = os.path.abspath(os.path.join(QA, '..', '..'))
        antes = os.environ.get('CLAUDE_PROJECT_DIR')
        os.environ['CLAUDE_PROJECT_DIR'] = raiz
        self.addCleanup(lambda: os.environ.pop('CLAUDE_PROJECT_DIR') if antes is None else os.environ.update(CLAUDE_PROJECT_DIR=antes))
        salida = self.medir([
            respuesta('m1', 100, orden('t1', '', nombre='Read', file_path=f'{raiz}/backend/src/services/narrador.ts')),
            resultado('t1', 'x' * 350),
            respuesta('m2', 100, orden('t2', 'cd backend && sed -n 1,5p src/services/narrador.ts')),
            resultado('t2', 'x' * 350),
            respuesta('m3', 100, orden('t3', 'head -3 CLAUDE.md AGENTS.md | cut -c1-80')),
            resultado('t3', 'x' * 700),
            respuesta('m4', 100, orden('t4', 'git status docs/x.md')),
            resultado('t4', 'x' * 3500),
            # QA-179: los scripts que se ejecutan no se leen; lo que lee la orden que lanzan, sí.
            respuesta('m5', 100, orden('t5', 'bash tools/qa/host.sh grep -n x docs/y.md && ./tools/z.sh && python3 -I a/b.py')),
            resultado('t5', 'x' * 350),
            respuesta('m6', 100),
        ])
        self.assertRegex(salida, r'backend/src/services/narrador.ts\s+2×\s+200 tok')
        self.assertRegex(salida, r'AGENTS.md\s+1×\s+100 tok')
        self.assertRegex(salida, r'CLAUDE.md\s+1×\s+100 tok')
        por_archivo = salida.split('POR ARCHIVO')[1]
        self.assertNotIn('docs/x.md', por_archivo)
        self.assertRegex(por_archivo, r'docs/y.md\s+1×')
        for script in ('host.sh', 'z.sh', 'b.py'):
            self.assertNotIn(script, por_archivo)

    def test_reparte_por_modelo_la_sesion_y_sus_subagentes(self):
        """QA-117: qué modelo hizo qué, con los subagentes de `<sesión>/subagents/`."""
        salida = self.medir([respuesta('m1', 100), respuesta('m2', 200),
                             # Un subagente escrito en el registro principal no es de la sesión principal.
                             respuesta('s9', 5000, isSidechain=True)], {
            'agent-a': ('general-purpose', [respuesta('s1', 40, texto('a'), texto('b'), modelo='claude-sonnet-5-5')]),
            'agent-b': ('Explore', [respuesta('s2', 7, modelo='claude-haiku-5-5')]),
        })
        self.assertRegex(salida, r'principal\s+claude-opus-5-5\s+2 llamadas\s+300 entrada\s+20 salida')
        self.assertRegex(salida, r'subagentes\s+claude-sonnet-5-5\s+1 llamadas\s+40 entrada')
        self.assertIn('Subagentes: 1 general-purpose (claude-sonnet-5-5) · 1 Explore (claude-haiku-5-5)', salida)

    def test_desglosa_por_subagente_y_cuenta_la_salida_mayor_de_cada_respuesta(self):
        """QA-146: una fila por subagente (descripción, tipo, modelo, llamadas, contexto medio, entrada, salida) y totales
        con su salida; `output_tokens` crece entre las líneas de una misma respuesta, vale la última."""
        a = respuesta('s1', 1000, texto('a'), texto('b'), modelo='claude-sonnet-5-5')
        a[0]['message']['usage']['output_tokens'] = 20  # valor provisional de la primera línea
        a[1]['message']['usage']['output_tokens'] = 700
        b = respuesta('s2', 3000, modelo='claude-sonnet-5-5')
        c = respuesta('s3', 500, modelo='claude-haiku-5-5')
        salida = self.medir([respuesta('m1', 100)], {
            'agent-a': ({'agentType': 'general-purpose', 'description': 'Arreglo del turno'}, [a, b]),
            'agent-b': ({'agentType': 'Explore'}, [c]),
            'agent-c': ({'agentType': 'Explore'}, []),  # sin respuestas: no sale
        })
        self.assertIn('POR SUBAGENTE', salida)
        self.assertRegex(salida, r'Arreglo del turno\s+general-purpose\s+claude-sonnet-5-5\s+2 llamadas\s+2,000 ctx medio'
                                 r'\s+1,000 arranque\s+4,000 entrada\s+710 salida')
        self.assertRegex(salida, r'agent-b\s+Explore\s+claude-haiku-5-5\s+1 llamadas\s+500 ctx medio\s+500 arranque\s+500 entrada\s+— salida')
        self.assertIn('«—»: el registro del subagente no guarda la salida final', salida)
        self.assertIn('Subagentes en total: 2 registros · 3 llamadas · 4,500 entrada · 720 salida', salida)
        self.assertIn('Arranque medio: 750 tokens', salida)
        self.assertIn('Sesión + subagentes: 4 llamadas · 4,600 entrada · 730 salida', salida)
        self.assertRegex(salida, r'subagentes\s+claude-sonnet-5-5\s+2 llamadas\s+4,000 entrada\s+710 salida')

    def test_subagente_sin_modelo_y_synthetic(self):
        """Modelo a null: sale como «?» sin reventar; `<synthetic>` no sale en la tabla ni cuenta en POR MODELO."""
        salida = self.medir([respuesta('m1', 100)], {
            'agent-a': ({'agentType': 'Explore', 'description': 'Sin modelo'}, [respuesta('s1', 50, modelo=None)]),
            'agent-b': ({'agentType': 'Explore', 'description': 'Solo sintetico'}, [respuesta('s2', 60, modelo='<synthetic>')]),
        })
        self.assertRegex(salida, r'Sin modelo\s+Explore\s+\?\s+1 llamadas')
        self.assertNotIn('Solo sintetico', salida)
        self.assertNotIn('synthetic', salida)

    def test_sin_subagentes_no_hay_seccion(self):
        self.assertNotIn('POR SUBAGENTE', self.medir([respuesta('m1', 100)]))

    def test_con_horas_el_primer_tramo_a_medias_no_cuenta_como_suelo(self):
        def hace(horas):
            return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=horas)).isoformat().replace('+00:00', 'Z')
        corte = compactacion()
        for l in corte:
            l['timestamp'] = hace(1.3)
        salida = self.medir([
            respuesta('m0', 10, timestamp=hace(5)),  # fuera del periodo: el tramo empezó antes
            respuesta('m1', 900, timestamp=hace(1.5)), respuesta('m2', 1000, timestamp=hace(1.4)),
            *corte,
            respuesta('m3', 100, timestamp=hace(1.2)), respuesta('m4', 300, timestamp=hace(1.1)),
        ], horas='2')
        self.assertIn('Tramos entre compactaciones: 1  ·  suelo medio 100  ·  techo medio 300  ·  2 llamadas por tramo'
                      '  (sin el primero, que empezó antes del periodo)', salida)
        # QA-127: el medio de todo el periodo (575) mezcla el tramo a medias; sin él, el del régimen actual (200).
        self.assertIn('Contexto medio por llamada: 575 tokens', salida)
        self.assertIn('Contexto medio sin el primer tramo: 200 tokens', salida)
        self.assertIn('Por tramo, del más antiguo al último (medio/techo, en miles): 0/0', salida)

    def test_desde_recorta_como_horas_con_fecha_o_sha(self):
        """QA-134: `--desde` con una fecha ISO o un sha de commit mide solo desde ahí."""
        def hace(horas):
            return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=horas)).isoformat().replace('+00:00', 'Z')
        corte = compactacion()
        for l in corte:
            l['timestamp'] = hace(1.3)
        partes = [respuesta('m0', 10, timestamp=hace(5)), respuesta('m1', 900, timestamp=hace(1.5)), *corte,
                  respuesta('m3', 100, timestamp=hace(1.2)), respuesta('m4', 300, timestamp=hace(1.1))]
        salida = self.medir(partes, extra=('--desde', hace(2)))
        self.assertIn('Llamadas a la API: 3  ·  compactaciones: 1', salida)
        self.assertIn('(sin el primero, que empezó antes del periodo)', salida)
        # Con un sha: la fecha del commit (con su offset, +02:00 = 10:00 UTC) recorta; una ISO sin zona es UTC.
        repo = carpeta()
        entorno = {**os.environ, 'GIT_COMMITTER_DATE': '2026-01-01T12:00:00+02:00', 'GIT_AUTHOR_DATE': '2026-01-01T12:00:00+02:00',
                   'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_SYSTEM': os.devnull}
        for orden_git in (['init', '-q'], ['-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'x']):
            subprocess.run(['git', *orden_git], cwd=repo, env=entorno, check=True)
        sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo, capture_output=True, text=True).stdout.strip()
        ruta = registro(os.path.join(repo, 's.jsonl'), respuesta('a', 10, timestamp='2026-01-01T09:00:00Z'),
                        respuesta('b', 20, timestamp='2026-01-01T11:00:00Z'), respuesta('c', 30, timestamp='2026-01-01T12:00:00Z'))
        for valor in (sha, sha[:8], '2026-01-01T10:00:00', '2026-01-01T12:00:00+02:00'):
            r = subprocess.run(['python3', MEDIR, '--sesion', ruta, '--desde', valor], capture_output=True, text=True, cwd=repo)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('Llamadas a la API: 2  ·', r.stdout, valor)
        malo = subprocess.run(['python3', MEDIR, '--desde', 'no-existe-xyz'], capture_output=True, text=True)
        self.assertNotEqual(malo.returncode, 0)


if __name__ == '__main__':
    unittest.main()
