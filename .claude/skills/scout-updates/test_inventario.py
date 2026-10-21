import io, json, os, shutil, sys, tempfile, unittest
from contextlib import redirect_stdout

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import inventario

EJEMPLO = os.path.join(AQUI, 'evals', 'proyecto-ejemplo')
DIFICILES = os.path.join(AQUI, 'evals', 'manifiestos-dificiles')


def salida_dificil():
    """(nombre, versión) por sección del inventario de `manifiestos-dificiles`; su README dice cómo regenerarla."""
    inv = inventario.inventariar(DIFICILES)
    return {s: sorted([c['nombre'], c['version']] for c in v) for s, v in inv.items() if s != 'manifiestos'}


class InventarioTest(unittest.TestCase):
    def test_proyecto_ejemplo(self):
        inv = inventario.inventariar(EJEMPLO)
        nombres = lambda s: {(c['nombre'], c['version']) for c in inv[s]}
        self.assertIn(('node', '16'), nombres('runtimes'))
        self.assertIn(('node', '16-alpine'), nombres('runtimes'))
        self.assertIn(('express', '4.17.1'), nombres('dependencias'))
        self.assertIn(('pandas', '==1.3.5'), nombres('dependencias'))
        self.assertIn(('actions/checkout', 'v2'), nombres('infraestructura'))
        self.assertIn(('runner', 'ubuntu-20.04'), nombres('infraestructura'))
        self.assertEqual({c['nombre'] for c in inv['modelos de IA']}, {'gpt-3.5-turbo', 'text-embedding-ada-002'})
        self.assertIn('requirements.txt', inv['manifiestos'])

    def test_fusiona_origenes_y_excluye_claude(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        os.makedirs(os.path.join(d, 'src', 'config'))
        os.makedirs(os.path.join(d, '.claude', 'x'))
        with open(os.path.join(d, '.env.example'), 'w') as f:
            f.write('LLM_MODEL=modelo-a\n')
        with open(os.path.join(d, 'src', 'config', 'env.ts'), 'w') as f:
            f.write("export const m = process.env.LLM_MODEL ?? 'modelo-a';\n")
        with open(os.path.join(d, '.claude', 'x', 'package.json'), 'w') as f:
            f.write('{"dependencies": {"nada": "1"}}')
        with open(os.path.join(d, 'Cargo.toml'), 'w') as f:
            f.write('[package]\nname = "x"\n\n[dependencies]\nserde = "1.0"\ntokio = { version = "1", features = ["full"] }\n')
        with open(os.path.join(d, 'pyproject.toml'), 'w') as f:
            f.write('[project]\nrequires-python = ">=3.9"\ndependencies = ["requests>=2", "uvicorn[standard]>=0.30", "rich"]\n')
        os.makedirs(os.path.join(d, 'modelfiles'))
        with open(os.path.join(d, 'modelfiles', 'q-32k.Modelfile'), 'w') as f:
            f.write('FROM base-b\n')
        with open(os.path.join(d, 'opencode.json'), 'w') as f:
            f.write('{"plugin": ["p-uno", "@org/p-dos@1.2"], "agent": {"lore": {"model": "ollama/q-32k"}}}')
        inv = inventario.inventariar(d)
        otros = {(c['nombre'], c['uso']) for c in inv['modelos de IA']} - {('modelo-a', 'LLM_MODEL')}
        self.assertEqual(otros, {('base-b', 'base del Modelfile'), ('ollama/q-32k', 'agente lore')})
        self.assertIn(('@org/p-dos', '1.2'), {(c['nombre'], c['version']) for c in inv['dependencias']})
        inv['modelos de IA'] = [c for c in inv['modelos de IA'] if c['nombre'] == 'modelo-a']
        inv['dependencias'] = [c for c in inv['dependencias'] if c['origen'] != 'opencode.json']
        self.assertEqual(inv['modelos de IA'],
                         [{'nombre': 'modelo-a', 'version': '-', 'origen': '.env.example, src/config/env.ts', 'uso': 'LLM_MODEL'}])
        deps = {(c['nombre'], c['version']) for c in inv['dependencias']}
        self.assertEqual(deps, {('serde', '1.0'), ('tokio', '1'), ('requests', '>=2'), ('uvicorn[standard]', '>=0.30'), ('rich', '*')})
        self.assertIn(('python', '>=3.9'), {(c['nombre'], c['version']) for c in inv['runtimes']})
        self.assertNotIn('.claude/x/package.json', inv['manifiestos'])

    def test_imagenes_con_puerto_digest_y_etapas(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        with open(os.path.join(d, 'Dockerfile'), 'w') as f:
            f.write('FROM registry:5000/team/app:1.2 AS build\nFROM node@sha256:abc\nFROM build\n')
        imgs = {(c['nombre'], c['version']) for c in inventario.inventariar(d)['runtimes']}
        self.assertEqual(imgs, {('registry:5000/team/app', '1.2'), ('node', 'latest')})

    def test_manifiestos_dificiles(self):
        with open(os.path.join(DIFICILES, 'esperado.json'), encoding='utf-8') as f:
            self.assertEqual(salida_dificil(), json.load(f))

    def test_salida_texto(self):
        out = io.StringIO()
        with redirect_stdout(out):
            inventario.main([EJEMPLO])
        self.assertIn('## modelos de IA (2)', out.getvalue())
        self.assertIn('- gpt-3.5-turbo - · .env.example · OPENAI_MODEL', out.getvalue())

    def test_ollama_caido(self):
        self.assertIsNone(inventario.modelos_ollama('http://127.0.0.1:9'))

if __name__ == '__main__':
    unittest.main()
