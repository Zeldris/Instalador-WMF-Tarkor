import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inventory


def write(root, path, text):
    full = os.path.join(root, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as f:
        f.write(text)


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)

    def pairs(self, inv, section):
        return {(c['name'], c['version']) for c in inv[section]}

    def test_small_project(self):
        write(self.d, '.nvmrc', '16\n')
        write(self.d, 'package.json', '{"engines": {"node": ">=16"}, "dependencies": {"express": "4.17.1"}}')
        write(self.d, 'package-lock.json', '{}')
        write(self.d, 'requirements.txt', 'pandas==1.3.5\n# comment\n-r other.txt\n')
        write(self.d, 'Dockerfile', 'FROM node:16-alpine\n')
        write(self.d, '.github/workflows/ci.yml',
              'jobs:\n  t:\n    runs-on: ubuntu-20.04\n    steps:\n      - uses: actions/checkout@v2\n')
        write(self.d, '.env.example', 'OPENAI_MODEL=gpt-3.5-turbo\nPORT=3000\n')
        inv = inventory.inventory(self.d)
        self.assertIn(('node', '16'), self.pairs(inv, 'runtimes'))
        self.assertIn(('node', '16-alpine'), self.pairs(inv, 'runtimes'))
        self.assertIn(('express', '4.17.1'), self.pairs(inv, 'dependencies'))
        self.assertIn(('pandas', '==1.3.5'), self.pairs(inv, 'dependencies'))
        self.assertIn(('actions/checkout', 'v2'), self.pairs(inv, 'infrastructure'))
        self.assertIn(('runner', 'ubuntu-20.04'), self.pairs(inv, 'infrastructure'))
        self.assertEqual({c['name'] for c in inv['ai models']}, {'gpt-3.5-turbo'})
        self.assertIn('requirements.txt', inv['manifests'])
        self.assertEqual([c['lock'] for c in inv['dependencies'] if c['name'] == 'express'], ['package-lock.json'])

    def test_merges_origins_and_excludes_claude_folder(self):
        write(self.d, '.env.example', 'LLM_MODEL=model-a\n')
        write(self.d, 'src/config/env.ts', "export const m = process.env.LLM_MODEL ?? 'model-a';\n")
        write(self.d, '.claude/x/package.json', '{"dependencies": {"nothing": "1"}}')
        write(self.d, 'Cargo.toml',
              '[package]\nname = "x"\n\n[dependencies]\nserde = "1.0"\ntokio = { version = "1", features = ["full"] }\n')
        write(self.d, 'pyproject.toml',
              '[project]\nrequires-python = ">=3.9"\ndependencies = ["requests>=2", "uvicorn[standard]>=0.30", "rich"]\n')
        write(self.d, 'modelfiles/q-32k.Modelfile', 'FROM base-b\n')
        write(self.d, 'opencode.json', '{"plugin": ["p-one", "@org/p-two@1.2"], "agent": {"lore": {"model": "ollama/q-32k"}}}')
        inv = inventory.inventory(self.d)
        others = {(c['name'], c['use']) for c in inv['ai models']} - {('model-a', 'LLM_MODEL')}
        self.assertEqual(others, {('base-b', 'Modelfile base'), ('ollama/q-32k', 'agent lore')})
        self.assertIn(('@org/p-two', '1.2'), self.pairs(inv, 'dependencies'))
        self.assertEqual([c for c in inv['ai models'] if c['name'] == 'model-a'],
                         [{'name': 'model-a', 'version': '-', 'origin': '.env.example, src/config/env.ts', 'use': 'LLM_MODEL'}])
        deps = {(c['name'], c['version']) for c in inv['dependencies'] if c['origin'] != 'opencode.json'}
        self.assertEqual(deps, {('serde', '1.0'), ('tokio', '1'), ('requests', '>=2'),
                                ('uvicorn[standard]', '>=0.30'), ('rich', '*')})
        self.assertIn(('python', '>=3.9'), self.pairs(inv, 'runtimes'))
        self.assertNotIn('.claude/x/package.json', inv['manifests'])

    def test_images_with_port_digest_and_stages(self):
        write(self.d, 'Dockerfile', 'FROM registry:5000/team/app:1.2 AS build\nFROM node@sha256:abc\nFROM build\n')
        self.assertEqual(self.pairs(inventory.inventory(self.d), 'runtimes'),
                         {('registry:5000/team/app', '1.2'), ('node', 'latest')})

    def test_text_output(self):
        write(self.d, '.env.example', 'OPENAI_MODEL=gpt-3.5-turbo\n')
        out = io.StringIO()
        with redirect_stdout(out):
            inventory.main([self.d])
        self.assertIn('## ai models (1)', out.getvalue())
        self.assertIn('- gpt-3.5-turbo - | .env.example | OPENAI_MODEL', out.getvalue())

    def test_ollama_down(self):
        self.assertIsNone(inventory.ollama_models('http://127.0.0.1:9'))


if __name__ == '__main__':
    unittest.main()
