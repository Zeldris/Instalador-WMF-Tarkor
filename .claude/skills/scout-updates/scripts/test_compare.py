import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compare


def git(root, *args):
    return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args], cwd=root,
                          capture_output=True, text=True, check=True).stdout.strip()


class CompareTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        for name, text in (('package.json', '{"dependencies": {"express": "4.17.1"}}'), ('.nvmrc', '16\n'),
                           ('.env.example', 'LLM_MODEL=model-a\n')):
            with open(os.path.join(self.d, name), 'w') as f:
                f.write(text)
        git(self.d, 'init', '-q')
        git(self.d, 'add', '.')
        git(self.d, 'commit', '-qm', 'one')
        self.commit = git(self.d, 'rev-parse', '--short', 'HEAD')
        self.arch = os.path.join(self.d, 'architecture.md')
        with open(self.arch, 'w') as f:
            f.write('# A\n\n## Constraints\n\n- local\n\n'
                    '## AI models\n<!-- seal: 2026-01-10 | %s | .env.example -->\n\n'
                    '## Runtimes\n<!-- seal: 2026-01-10 | %s | .nvmrc, package.json -->\n\n'
                    '## Infrastructure\n\nno seal\n' % (self.commit, self.commit))

    def test_same_changed_unsealed_uncounted(self):
        with open(os.path.join(self.d, '.nvmrc'), 'w') as f:
            f.write('22\n')
        with open(os.path.join(self.d, 'Dockerfile'), 'w') as f:
            f.write('FROM node:22\n')
        res = compare.compare(self.arch, self.d)
        self.assertEqual([s['section'] for s in res['same']], ['AI models'])
        self.assertEqual(res['changed'], [{'section': 'Runtimes', 'date': '2026-01-10', 'files': ['.nvmrc']}])
        self.assertEqual([s['section'] for s in res['unsealed']], ['Infrastructure'])
        self.assertEqual(res['uncounted'], ['Dockerfile'])

    def test_deleted_file_and_unknown_commit(self):
        os.unlink(os.path.join(self.d, '.env.example'))
        with open(self.arch, 'a') as f:
            f.write('## Other\n<!-- seal: 2026-01-10 | deadbeef | x -->\n')
        res = compare.compare(self.arch, self.d)
        self.assertEqual(res['changed'][0]['files'], ['.env.example'])
        self.assertIn({'section': 'Other', 'reason': 'unknown commit deadbeef'}, res['unsealed'])

    def test_seal_without_files_and_folder(self):
        os.makedirs(os.path.join(self.d, '.github', 'workflows'))
        with open(os.path.join(self.d, '.github', 'workflows', 'ci.yml'), 'w') as f:
            f.write('jobs: {}\n')
        with open(self.arch, 'a') as f:
            f.write('## CI\n<!-- seal: 2026-01-10 | %s | .github/workflows -->\n'
                    '## Empty\n<!-- seal: 2026-01-10 | %s |  -->\n' % (self.commit, self.commit))
        res = compare.compare(self.arch, self.d)
        self.assertNotIn('.github/workflows/ci.yml', res['uncounted'])
        self.assertIn({'section': 'Empty', 'reason': 'seal without files'}, res['unsealed'])

    def test_section(self):
        text = '# A\n\n## AI models\n\none\n\n## Runtimes\n\ntwo\n'
        self.assertEqual(compare.section(text, 'models'), '## AI models\n\none\n')
        self.assertIsNone(compare.section(text, 'nothing'))

    def test_report_uncovered(self):
        arch = ('## Constraints\n\n| Component | x |\n|---|---|\n| memory | 6 GB |\n\n'
                '## AI models\n\n| Component | Version |\n|---|---|\n| narrator | a |\n| `chronicler` | b |\n')
        report = '# R\n\n## Coverage\n\n| Component | Result |\n|---|---|\n| Narrator | P-001 |\n'
        self.assertEqual(compare.uncovered(arch, report), ['chronicler'])
        self.assertEqual(compare.uncovered(arch, report + '| chronicler | no news |\n'), [])
        self.assertEqual(compare.uncovered(arch, '| narrator | outside Coverage |\n'), ['narrator', 'chronicler'])

    def test_spanish_titles(self):
        """A Spanish memory (`sello`, `Restricciones`, `Cobertura`, `Componente`) is read like the English one."""
        with open(self.arch, 'w') as f:
            f.write('# A\n\n## Restricciones\n\n| Componente | x |\n|---|---|\n| memoria | 6 GB |\n\n'
                    '## Modelos de IA\n<!-- sello: 2026-01-10 | %s | .env.example -->\n\n'
                    '| Componente | Versión |\n|---|---|\n| narrador | a |\n\n'
                    '## Entornos\n<!-- sello: 2026-01-10 | %s | .nvmrc, package.json -->\n' % (self.commit, self.commit))
        res = compare.compare(self.arch, self.d)
        self.assertEqual([s['section'] for s in res['same']], ['Modelos de IA', 'Entornos'])
        self.assertEqual(res['unsealed'], [])
        report = '# I\n\n## Cobertura\n\n| Componente | Resultado |\n|---|---|\n| Narrador | P-001 |\n'
        with open(self.arch) as f:
            arch = f.read()
        self.assertEqual(compare.uncovered(arch, report), [])  # `memoria` (Restricciones) is no component
        self.assertEqual(compare.uncovered(arch, '## Cobertura\n\n| Componente |\n|---|\n'), ['narrador'])

    def test_default_architecture_from_scout_dir(self):
        """Without a path, it is `<scoutDir>/architecture.md`; the message says how to fix a missing config.py."""
        with self.assertRaises(SystemExit) as e:
            compare.main(['--root', self.d])
        self.assertIn('scoutDir: ', str(e.exception.code))
        self.assertIn('config.py not found', str(e.exception.code))
        self.assertIn('aplicar.py --update', str(e.exception.code))
        repo = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..')
        gw = os.path.join(self.d, '.claude', 'gw')
        os.makedirs(os.path.join(gw, 'scripts'))
        os.makedirs(os.path.join(gw, 'schema'))
        shutil.copy(os.path.join(repo, 'scripts', 'config.py'), os.path.join(gw, 'scripts'))
        shutil.copy(os.path.join(repo, 'schema', 'gw.schema.json'), os.path.join(gw, 'schema'))
        config = {'version': '0.2.0', 'language': 'es', 'log': 'l.md', 'protectedBranch': 'main',
                  'pushToProtected': 'pr', 'check': ['true'], 'reviewMark': 'r.txt', 'content': ['^docs/']}
        for scout, folder in ((None, '.claude/gw/scout'), ('docs/scout', 'docs/scout')):
            with open(os.path.join(self.d, '.claude', 'gw.json'), 'w') as f:
                json.dump(dict(config, **({'scoutDir': scout} if scout else {})), f)
            self.assertEqual(compare.scout_dir(self.d), folder)
        with open(os.path.join(self.d, '.claude', 'gw.json'), 'w') as f:
            f.write('{not json')
        with self.assertRaises(SystemExit) as e:
            compare.scout_dir(self.d)
        self.assertIn('could not read it', str(e.exception.code))
        self.assertIn('config.py validate', str(e.exception.code))
        with open(os.path.join(self.d, '.claude', 'gw.json'), 'w') as f:
            json.dump(dict(config, scoutDir='docs/scout'), f)
        os.makedirs(os.path.join(self.d, 'docs', 'scout'))
        shutil.move(self.arch, os.path.join(self.d, 'docs', 'scout', 'architecture.md'))
        out = io.StringIO()
        with redirect_stdout(out):
            compare.main(['--root', self.d])
        self.assertIn('same       AI models', out.getvalue())

    def test_default_root_is_never_the_current_directory(self):
        """Run from a subfolder without --root: the installed copy takes the project holding it, the source copy the
        git top level; either way the Dockerfile at the root is seen (from the subfolder it would not be)."""
        with open(os.path.join(self.d, 'Dockerfile'), 'w') as f:
            f.write('FROM node:22\n')
        sub = os.path.join(self.d, 'sub', 'deeper')
        os.makedirs(sub)
        here = os.path.dirname(os.path.abspath(__file__))
        installed = os.path.join(self.d, '.claude', 'skills', 'scout-updates', 'scripts')
        os.makedirs(installed)
        for name in ('compare.py', 'inventory.py'):
            shutil.copy(os.path.join(here, name), installed)
        r = subprocess.run([sys.executable, os.path.join(installed, 'compare.py'), self.arch, '--json'], cwd=sub,
                           capture_output=True, text=True)
        self.assertIn('Dockerfile', json.loads(r.stdout)['uncounted'], r.stderr)
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(sub)
        out = io.StringIO()
        with redirect_stdout(out):
            compare.main([self.arch, '--json'])
        self.assertIn('Dockerfile', json.loads(out.getvalue())['uncounted'])
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside)
        os.chdir(outside)
        with self.assertRaises(SystemExit) as e:
            compare.main([self.arch])
        self.assertIn('--root <project root>', str(e.exception.code))

    def test_exit_code(self):
        with open(self.arch, 'w') as f:
            f.write('## Runtimes\n<!-- seal: 2026-01-10 | %s | .nvmrc, package.json, .env.example -->\n' % self.commit)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(compare.main([self.arch, '--root', self.d]), 0)
        with open(os.path.join(self.d, 'package.json'), 'a') as f:
            f.write('\n')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(compare.main([self.arch, '--root', self.d]), 1)


if __name__ == '__main__':
    unittest.main()
