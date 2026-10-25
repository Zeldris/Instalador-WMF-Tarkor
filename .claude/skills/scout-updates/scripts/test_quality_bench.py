import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quality_bench as bench


class BenchTest(unittest.TestCase):
    CASES = [{'id': 'c1', 'prompt': 'x' * 2000}, {'id': 'c2', 'prompt': 'p', 'context': 'open the door'}]

    def batches(self):
        return [[{'case': c, 'model': m, 'output': '%s-%s' % (m, c)} for c in ('c1', 'c2')] for m in ('a', 'b')]

    def test_generate_with_error(self):
        def call(model, system, prompt, options):
            if prompt == 'p':
                raise OSError('down')
            return ' hello '
        old, sys.stderr = sys.stderr, io.StringIO()
        try:
            rows = bench.generate(self.CASES, 'm', call)
        finally:
            sys.stderr = old
        self.assertEqual(rows[0]['output'], 'hello')
        self.assertEqual(rows[1], {'case': 'c2', 'model': 'm', 'error': 'down'})

    def test_pairs_two_blind_orders(self):
        pair_list, key = bench.pairs(self.batches(), self.CASES, seed=1)
        self.assertEqual(len(pair_list), 4)
        for p in pair_list:
            self.assertEqual(set(p), {'pair', 'case', 'context', 'X', 'Y'})
            self.assertEqual(p['X'], '%s-%s' % (key[p['pair']]['X'], p['case']))
        orders = {(p['case'], key[p['pair']]['X']) for p in pair_list}
        self.assertEqual(orders, {('c1', 'a'), ('c1', 'b'), ('c2', 'a'), ('c2', 'b')})
        self.assertEqual(len(next(p for p in pair_list if p['case'] == 'c1')['context']), bench.CONTEXT_MAX)
        self.assertEqual(next(p for p in pair_list if p['case'] == 'c2')['context'], 'open the door')

    def test_judge_and_summary(self):
        pair_list, key = bench.pairs(self.batches(), self.CASES)

        # the judge always prefers 'a' on c1; on c2 it always picks X (position bias)
        def judge(model, system, prompt, options, json_format):
            pair = next(p for p in pair_list if 'Answer X:\n%s\n' % p['X'] in prompt and 'Answer Y:\n%s\n' % p['Y'] in prompt)
            if pair['case'] == 'c2':
                return '{"winner": "X", "reason": "first"}'
            return json.dumps({'winner': 'X' if key[pair['pair']]['X'] == 'a' else 'Y'})
        verdicts = bench.judge(pair_list, 'judge', 'rubric', judge)
        res = bench.summary(pair_list, key, verdicts)
        self.assertEqual(res['models']['a'], {'points': 3.0, 'played': 4, 'rate': 0.75})
        self.assertEqual(res['models']['b']['rate'], 0.25)
        self.assertEqual(res['consistency'], 0.5)
        self.assertEqual(res['x_bias'], 0.75)
        # detail, same count: the c2 pair changes when flipped, so it is a tie
        self.assertEqual(res['head_to_head'], {'a': {'b': 0.75}, 'b': {'a': 0.25}})
        self.assertEqual(res['per_case'], {'c1': {'a': 2, 'b': 0}, 'c2': {'a': 1.0, 'b': 1.0}})
        self.assertEqual(sorted(x['case'] for x in res['losses']['b']), ['c1', 'c1', 'c2'])
        self.assertEqual(sorted(x['case'] for x in res['losses']['a']), ['c2'])
        self.assertEqual(res['repeated'], 0)
        # a repeated verdict is not counted twice and is reported; one without winner is a tie
        res = bench.summary(pair_list, key, verdicts + verdicts[:1] + [{'pair': verdicts[1]['pair']}])
        self.assertEqual(res['repeated'], 2)
        self.assertEqual((res['judged'], res['x_bias']), (4, 0.75))  # same as without the repeats
        self.assertEqual(res['models']['a']['played'], 4)

    def test_pairs_not_matching_key_say_how_to_fix(self):
        pair_list, key = bench.pairs(self.batches(), self.CASES)
        other = [dict(p, pair='q%s' % p['pair']) for p in pair_list]
        with self.assertRaises(SystemExit) as e:
            bench.summary(other, key, [{'pair': pair_list[0]['pair'], 'winner': 'X'}])
        self.assertIn('different runs', str(e.exception.code))
        self.assertIn('quality_bench.py pairs', str(e.exception.code))
        self.assertIn('--seed', str(e.exception.code))

    def test_unreadable_judge_is_a_tie(self):
        pair_list, key = bench.pairs(self.batches(), self.CASES)
        v = bench.judge(pair_list[:1], 'judge', 'r', lambda *a: 'no idea')
        self.assertEqual(v[0]['winner'], 'tie')
        self.assertIn('unreadable', v[0]['warning'])
        self.assertEqual(bench.summary(pair_list, key, v)['unjudged'], 3)
        self.assertEqual(bench.judge(pair_list[:1], 'judge', 'r', lambda *a: '[1]')[0]['winner'], 'tie')

    def test_failed_judge_keeps_what_was_judged(self):
        pair_list, key = bench.pairs(self.batches(), self.CASES)

        def judge(*a):
            if judge.n == 1:
                raise OSError('timeout')
            judge.n += 1
            return '{"winner": "X"}'
        judge.n = 0
        v = bench.judge(pair_list[:2], 'judge', 'r', judge)
        self.assertEqual(v[1], {'pair': pair_list[1]['pair'], 'error': 'timeout'})
        self.assertEqual(bench.summary(pair_list, key, v)['judged'], 1)

    def test_unreadable_files_say_how_to_fix(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, 'bad.jsonl')
            with open(bad, 'w') as f:
                f.write('{not json\n')
            with self.assertRaises(SystemExit) as e:
                bench.read_jsonl(bad)
            self.assertIn('Cannot read %s as JSON lines' % bad, str(e.exception.code))
            self.assertIn('each line is a JSON object', str(e.exception.code))
            with self.assertRaises(SystemExit) as e:
                bench.main(['summary', bad, os.path.join(d, 'no-key.json'), bad])
            self.assertIn('Cannot read the key', str(e.exception.code))
            self.assertIn('written by `pairs`', str(e.exception.code))

    def test_cli_pairs_and_summary(self):
        with tempfile.TemporaryDirectory() as d:
            def path(n):
                return os.path.join(d, n)
            bench.write_jsonl(path('cases.jsonl'), self.CASES)
            for m, batch in zip('ab', self.batches()):
                bench.write_jsonl(path(m + '.jsonl'), batch)
            with redirect_stdout(io.StringIO()) as buf:
                bench.main(['pairs', path('a.jsonl'), path('b.jsonl'), '--cases', path('cases.jsonl'),
                            '--output', path('pairs.jsonl'), '--key', path('key.json')])
            self.assertEqual(buf.getvalue().strip(), '4 pairs')
            pair_list = bench.read_jsonl(path('pairs.jsonl'))
            bench.write_jsonl(path('v.jsonl'), [{'pair': p['pair'], 'winner': 'X'} for p in pair_list])
            with redirect_stdout(io.StringIO()) as buf:
                bench.main(['summary', path('pairs.jsonl'), path('key.json'), path('v.jsonl'), '--detail'])
            self.assertIn('consistency when flipped: 0.0 | X wins: 1.0 | judged 4, unjudged 0', buf.getvalue())
            self.assertIn('head to head', buf.getvalue())

    def test_cli_repeated_verdicts_say_the_first_counts(self):
        """A pair judged twice keeps its first verdict; the warning says so instead of 'not counted'."""
        with tempfile.TemporaryDirectory() as d:
            def path(n):
                return os.path.join(d, n)
            bench.write_jsonl(path('cases.jsonl'), self.CASES)
            for m, batch in zip('ab', self.batches()):
                bench.write_jsonl(path(m + '.jsonl'), batch)
            with redirect_stdout(io.StringIO()):
                bench.main(['pairs', path('a.jsonl'), path('b.jsonl'), '--cases', path('cases.jsonl'),
                            '--output', path('pairs.jsonl'), '--key', path('key.json')])
            pair_list = bench.read_jsonl(path('pairs.jsonl'))
            verdicts = [{'pair': p['pair'], 'winner': 'X'} for p in pair_list]
            bench.write_jsonl(path('v.jsonl'), verdicts + [dict(verdicts[0], winner='Y')])
            with redirect_stdout(io.StringIO()) as buf:
                bench.main(['summary', path('pairs.jsonl'), path('key.json'), path('v.jsonl')])
            self.assertIn('WARNING: 1 repeated verdicts', buf.getvalue())
            self.assertIn('the first verdict of each pair counts and later ones are ignored', buf.getvalue())
            self.assertIn('judged 4, unjudged 0', buf.getvalue())


if __name__ == '__main__':
    unittest.main()
