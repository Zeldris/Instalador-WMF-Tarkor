import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import medir


def call(dur, profile='small', task='chat', **extra):
    r = {'gen_ai.operation.name': 'text_completion', 'app.machine_profile': profile, 'app.task': task,
         'app.duration_ms': dur}
    r.update(extra)
    return r


class MedirTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.n = 0

    def log(self, lines, name=None):
        self.n += 1
        path = os.path.join(self.dir.name, name or f'log{self.n}.jsonl')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(l if isinstance(l, str) else json.dumps(l) for l in lines) + '\n')
        return path

    def run_main(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            medir.main(argv)
        return buf.getvalue()

    def test_percentiles(self):
        self.assertEqual(medir.percentile([1, 2, 3, 4, 5], 50), 3)
        self.assertAlmostEqual(medir.percentile([10, 20], 95), 19.5)
        self.assertIsNone(medir.percentile([], 50))

    def test_full_row(self):
        rs = [call(1000, **{'gen_ai.usage.input_tokens': 100, 'gen_ai.usage.output_tokens': 50,
                            'app.decode_ms': 1000, 'app.load_ms': 500, 'app.ttft_ms': 200}),
              call(3000, **{'gen_ai.usage.input_tokens': 300, 'gen_ai.usage.output_tokens': 50,
                            'app.decode_ms': 1000, 'app.load_ms': 5, 'app.truncated': True, 'app.error': 'x'})]
        f = medir.call_row(rs)
        self.assertEqual((f['n'], f['p50_ms'], f['tok_in'], f['tok_out']), (2, 1000, 200, 50))  # failed call not in p50
        self.assertEqual(f['tok_s'], 50)
        self.assertEqual((f['cold_pct'], f['truncated_pct'], f['error_pct']), (50, 100, 50))
        self.assertEqual(f['ttft_p50_ms'], 200)

    def test_missing_fields(self):
        f = medir.call_row([call(10)])
        for k in ('tok_s', 'ttft_p50_ms', 'tok_in', 'cold_pct', 'truncated_pct'):
            self.assertIsNone(f[k])
        self.assertEqual(f['error_pct'], 0)

    def test_percentages_over_rows_with_field(self):
        rs = [call(1, **{'app.load_ms': 500, 'app.truncated': True}), call(1),
              call(1, **{'app.load_ms': 1, 'app.truncated': False}), call(1, **{'app.error': 'x'})]
        f = medir.call_row(rs)
        self.assertEqual((f['cold_pct'], f['truncated_pct'], f['error_pct']), (50, 50, 25))

    def test_cold_threshold(self):
        rs = [call(1, **{'app.load_ms': 500}), call(1, **{'app.load_ms': 50})]
        self.assertEqual(medir.call_row(rs, cold_ms=1000)['cold_pct'], 0)
        self.assertEqual(medir.call_row(rs, cold_ms=10)['cold_pct'], 100)

    def test_group_by_model(self):
        r = medir.analyse(self.log([call(10, **{'gen_ai.request.model': 'a'}),
                                    call(30, **{'gen_ai.request.model': 'b'}),
                                    call(50, **{'gen_ai.request.model': 'a'})]))
        self.assertEqual({k: v['n'] for k, v in r['calls'].items()},
                         {('small', 'chat', 'a'): 2, ('small', 'chat', 'b'): 1})

    def test_warmup_excluded_by_default(self):
        path = self.log([call(10), call(9000, task='warmup')])
        self.assertEqual(list(medir.analyse(path)['calls']), [('small', 'chat', '-')])
        self.assertIn(('small', 'warmup', '-'), medir.analyse(path, excluded=())['calls'])

    def test_event_lines_are_not_calls(self):
        r = medir.analyse(self.log([call(10), {'app.event': 'marker', 'app.task': 'chat', 'app.machine_profile': 'small'}]))
        self.assertEqual(r['calls'][('small', 'chat', '-')]['n'], 1)

    def test_corrupt_lines(self):
        r = medir.analyse(self.log([call(10), '{not json', '[1,2]', call(30)]))
        self.assertEqual(r['calls'][('small', 'chat', '-')]['n'], 2)
        self.assertEqual(sum('corrupt' in w for w in r['warnings']), 2)

    def test_no_profile_warns(self):
        r = medir.analyse(self.log([{'app.task': 'classify', 'app.duration_ms': 5}]))
        self.assertIn(('unknown', 'classify', '-'), r['calls'])
        self.assertTrue(any('no profile' in w and 'classify' in w for w in r['warnings']))

    def test_profile_filter(self):
        r = medir.analyse(self.log([call(10), call(20, profile='cpu')]), 'cpu')
        self.assertEqual(list(r['calls']), [('cpu', 'chat', '-')])

    def test_rag(self):
        base = {'gen_ai.operation.name': 'retrieval', 'app.machine_profile': 'small', 'app.task': 'rag'}
        path = self.log([
            dict(base, **{'app.rag.embed_ms': 10, 'app.rag.search_ms': 4,
                          'app.rag.results': [{'id': 'a', 'score': 0.8}, {'id': 'b', 'score': 0.5}]}),
            dict(base, **{'app.rag.embed_ms': 30, 'app.rag.search_ms': 6,
                          'app.rag.results': [{'id': 'c', 'score': 0.6}]})])
        f = medir.analyse(path)['rag'][('small', 'rag', '-')]
        self.assertEqual((f['n'], f['embed_p50_ms'], f['search_p50_ms']), (2, 20, 5))
        self.assertAlmostEqual(f['score_1'], 0.7)

    def test_turn_table(self):
        def turn_call(tid, end, dur, **extra):
            return call(dur, **{'app.turn': tid, 'ts': f'2026-01-01T10:00:{end:02d}Z'}, **extra)
        path = self.log([turn_call('a', 10, 2000), turn_call('a', 13, 1000),  # a: 8 s to 13 s
                         turn_call('b', 30, 1000, **{'app.error': 'x'}),
                         call(500),  # no app.turn: not in the table
                         call(900, task='warmup', **{'app.turn': 'w', 'ts': '2026-01-01T10:01:00Z'}),
                         call(100, **{'app.turn': 'c'})])  # no ts: the turn has no timing
        t = medir.analyse(path)['turns'][('small', 'turn', '-')]
        # a: start 10 s - 2 s = 8 s, end 13 s -> 5000 ms; b: 1000 ms.
        self.assertEqual((t['n'], t['p50_ms'], t['max_ms'], t['calls_per_turn'], t['error_pct']),
                         (2, 3000, 5000, 1.5, 50))
        text = self.run_main([path])
        self.assertIn('TURNS', text)
        self.assertIn('small/turn/-  2  3000  4800  5000  1.5  50', text)

    def test_retrieval_calls_with_the_turn_belong_to_it(self):
        rag = {'gen_ai.operation.name': 'retrieval', 'app.machine_profile': 'small', 'app.task': 'search',
               'app.duration_ms': 3000, 'app.turn': 'a', 'ts': '2026-01-01T10:00:05Z'}  # 2 s to 5 s
        path = self.log([rag, call(4000, **{'app.turn': 'a', 'ts': '2026-01-01T10:00:10Z'})])  # 6 s to 10 s
        t = medir.analyse(path)['turns'][('small', 'turn', '-')]
        self.assertEqual((t['n'], t['max_ms'], t['calls_per_turn']), (1, 8000, 2))

    def test_untimed_failed_turn_counts_in_error_pct(self):
        path = self.log([call(1000, **{'app.turn': 'a', 'ts': '2026-01-01T10:00:10Z'}),
                         call(100, **{'app.turn': 'b', 'app.error': 'x'})])  # failed, no ts: no timing
        t = medir.analyse(path)['turns'][('small', 'turn', '-')]
        self.assertEqual((t['n'], t['p50_ms'], t['error_pct']), (2, 1000, 50))

    def test_no_turn_field_no_turn_table(self):
        path = self.log([call(10)])
        self.assertEqual(medir.analyse(path)['turns'], {})
        self.assertNotIn('TURNS', self.run_main([path]))

    def test_turn_difference(self):
        def turn_call(end, dur):
            return call(dur, **{'app.turn': 'a', 'ts': f'2026-01-01T10:00:{end:02d}Z'})
        cur, prev = self.log([turn_call(10, 4000)]), self.log([turn_call(10, 3000)])
        d = json.loads(self.run_main([cur, '--previous', prev, '--json']))
        self.assertEqual(d['difference_turns']['small/turn/-']['p50_ms'], 1000)
        self.assertEqual(d['turns']['small/turn/-']['n'], 1)

    def test_comparison_json_and_text(self):
        cur = self.log([call(2000, **{'gen_ai.request.model': 'a'}), call(100, **{'gen_ai.request.model': 'b'})])
        prev = self.log([call(1500, **{'gen_ai.request.model': 'a'})])
        d = json.loads(self.run_main([cur, '--previous', prev, '--json']))
        self.assertEqual(d['difference_calls']['small/chat/a']['p50_ms'], 500)
        self.assertEqual(d['difference_calls']['small/chat/b'], 'no previous')
        text = self.run_main([cur, '--previous', prev])
        self.assertIn('(+500)', text)
        self.assertIn('(no previous)', text)

    def test_non_finite_dropped(self):
        r = medir.analyse(self.log(['{"app.machine_profile": "small", "app.task": "chat", "app.duration_ms": Infinity}',
                                    call(10, **{'gen_ai.usage.output_tokens': 5, 'app.decode_ms': float('nan')})]))
        f = r['calls'][('small', 'chat', '-')]
        self.assertEqual((f['n'], f['p50_ms'], f['tok_s']), (2, 10, None))

    def test_missing_file(self):
        with self.assertRaises(SystemExit) as e:
            medir.analyse('/no/such/log.jsonl')
        self.assertIn('Cannot read', str(e.exception.code))

    def test_help(self):
        with self.assertRaises(SystemExit) as e, redirect_stdout(io.StringIO()) as buf:
            medir.main(['--help'])
        self.assertEqual(e.exception.code, 0)
        self.assertIn('--previous', buf.getvalue())


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        subprocess.run(['git', 'init', '-q', self.root], check=True)
        os.makedirs(os.path.join(self.root, '.claude', 'gw'))
        os.makedirs(os.path.join(self.root, 'sub'))
        self.old = os.getcwd()
        os.chdir(os.path.join(self.root, 'sub'))  # the root must come from git, not from the cwd
        self.addCleanup(os.chdir, self.old)

    def write(self, rel, text):
        with open(os.path.join(self.root, rel), 'w', encoding='utf-8') as f:
            f.write(text)

    def run_main(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            medir.main(argv)
        return buf.getvalue()

    def test_root_from_git(self):
        self.assertEqual(os.path.realpath(medir.repo_root()), self.root)

    def test_paths_and_options_from_config(self):
        self.write('runs-now.jsonl', json.dumps(call(2000)) + '\n' + json.dumps(call(5, task='skip')) + '\n')
        self.write('runs-before.jsonl', json.dumps(call(1500)) + '\n')
        self.write('.claude/gw/opt-ai.md',
                   '# Local AI\n\n```opt-ai\n# comment\n- log: `runs-now.jsonl`\nprevious: runs-before.jsonl\n'
                   'exclude_tasks: skip, warmup\ncold_ms: 50\n```\n')
        d = json.loads(self.run_main(['--json']))
        self.assertEqual(list(d['calls']), ['small/chat/-'])
        self.assertEqual(d['difference_calls']['small/chat/-']['p50_ms'], 500)

    def test_argument_wins_over_config(self):
        self.write('a.jsonl', json.dumps(call(100)) + '\n')
        self.write('b.jsonl', json.dumps(call(900)) + '\n')
        self.write('.claude/gw/opt-ai.md', '```opt-ai\nlog: a.jsonl\n```\n')
        d = json.loads(self.run_main([os.path.join(self.root, 'b.jsonl'), '--json']))
        self.assertEqual(d['calls']['small/chat/-']['p50_ms'], 900)

    def test_no_log_anywhere(self):
        with self.assertRaises(SystemExit) as e:
            self.run_main([])
        self.assertIn('No log given', str(e.exception.code))


if __name__ == '__main__':
    unittest.main()
