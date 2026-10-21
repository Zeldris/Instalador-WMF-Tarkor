import io, os, shutil, subprocess, sys, tempfile, unittest
from contextlib import redirect_stdout

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import contrastar

EJEMPLO = os.path.join(AQUI, 'evals', 'proyecto-ejemplo')


def git(raiz, *args):
    return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args], cwd=raiz,
                          capture_output=True, text=True, check=True).stdout.strip()

class ContrastarTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        for nombre in ('package.json', '.nvmrc', '.env.example'):
            shutil.copy(os.path.join(EJEMPLO, nombre), self.d)
        git(self.d, 'init', '-q')
        git(self.d, 'add', '.')
        git(self.d, 'commit', '-qm', 'uno')
        self.commit = git(self.d, 'rev-parse', '--short', 'HEAD')
        self.arq = os.path.join(self.d, 'arquitectura.md')
        with open(self.arq, 'w') as f:
            f.write('# A\n\n## Restricciones\n\n- local\n\n'
                    '## Modelos de IA\n<!-- sello: 2026-01-10 · %s · .env.example -->\n\n'
                    '## Runtimes\n<!-- sello: 2026-01-10 · %s · .nvmrc, package.json -->\n\n'
                    '## Infraestructura\n\nsin sello\n' % (self.commit, self.commit))

    def test_igual_cambiada_sin_sello_sin_cuenta(self):
        with open(os.path.join(self.d, '.nvmrc'), 'w') as f:
            f.write('22\n')
        with open(os.path.join(self.d, 'Dockerfile'), 'w') as f:
            f.write('FROM node:22\n')
        inf = contrastar.contrastar(self.arq, self.d)
        self.assertEqual([s['seccion'] for s in inf['igual']], ['Modelos de IA'])
        self.assertEqual(inf['cambiada'], [{'seccion': 'Runtimes', 'fecha': '2026-01-10', 'archivos': ['.nvmrc']}])
        self.assertEqual([s['seccion'] for s in inf['sin sello']], ['Infraestructura'])
        self.assertEqual(inf['sin cuenta'], ['Dockerfile'])

    def test_archivo_borrado_y_commit_desconocido(self):
        os.unlink(os.path.join(self.d, '.env.example'))
        with open(self.arq, 'a') as f:
            f.write('## Otra\n<!-- sello: 2026-01-10 · deadbeef · x -->\n')
        inf = contrastar.contrastar(self.arq, self.d)
        self.assertEqual(inf['cambiada'][0]['archivos'], ['.env.example'])
        self.assertIn({'seccion': 'Otra', 'motivo': 'commit deadbeef desconocido'}, inf['sin sello'])

    def test_sello_sin_archivos_y_carpeta(self):
        os.makedirs(os.path.join(self.d, '.github', 'workflows'))
        with open(os.path.join(self.d, '.github', 'workflows', 'ci.yml'), 'w') as f:
            f.write('jobs: {}\n')
        with open(self.arq, 'a') as f:
            f.write('## CI\n<!-- sello: 2026-01-10 · %s · .github/workflows -->\n'
                    '## Vacía\n<!-- sello: 2026-01-10 · %s ·  -->\n' % (self.commit, self.commit))
        inf = contrastar.contrastar(self.arq, self.d)
        self.assertNotIn('.github/workflows/ci.yml', inf['sin cuenta'])
        self.assertIn({'seccion': 'Vacía', 'motivo': 'sello sin archivos'}, inf['sin sello'])

    def test_seccion(self):
        texto = '# A\n\n## Modelos de IA\n\nuno\n\n## Runtimes\n\ndos\n'
        self.assertEqual(contrastar.seccion(texto, 'modelos'), '## Modelos de IA\n\nuno\n')
        self.assertIsNone(contrastar.seccion(texto, 'nada'))

    def test_informe_sin_cubrir(self):
        arq = ('## Restricciones\n\n| Componente | x |\n|---|---|\n| memoria | 6 GB |\n\n'
               '## Modelos de IA\n\n| Componente | Versión |\n|---|---|\n| narrador | a |\n| `cronista` | b |\n')
        informe = '# I\n\n## Cobertura\n\n| Componente | Resultado |\n|---|---|\n| Narrador | P-001 |\n'
        self.assertEqual(contrastar.sin_cubrir(arq, informe), ['cronista'])
        self.assertEqual(contrastar.sin_cubrir(arq, informe + '| cronista | sin novedades |\n'), [])
        self.assertEqual(contrastar.sin_cubrir(arq, '| narrador | fuera de Cobertura |\n'), ['narrador', 'cronista'])

    def test_codigo_de_salida(self):
        with open(self.arq, 'w') as f:
            f.write('## Runtimes\n<!-- sello: 2026-01-10 · %s · .nvmrc, package.json, .env.example -->\n' % self.commit)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(contrastar.main([self.arq, '--raiz', self.d]), 0)
        with open(os.path.join(self.d, 'package.json'), 'a') as f:
            f.write('\n')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(contrastar.main([self.arq, '--raiz', self.d]), 1)

if __name__ == '__main__':
    unittest.main()
