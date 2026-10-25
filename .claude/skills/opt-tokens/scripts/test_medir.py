"""Tests of `medir.py` (skill `opt-tokens`) against a synthetic session log whose lines have the shape of Claude Code's
real ones. Ported from the World-Maker-Fantasy pilot (tools/qa/tests/test_medir.py, @ e433d1d), with the helpers of its
`comun.py` inlined. Run: python3 -m unittest discover -s skills/opt-tokens/scripts"""
import atexit
import datetime as dt
import itertools
import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MEDIR = os.path.join(HERE, 'medir.py')

HOUR = '2026-10-19T10:00:00.000Z'
_UUID = itertools.count()


def folder() -> str:
    path = tempfile.mkdtemp(prefix='opt-tokens-test-')
    atexit.register(shutil.rmtree, path, True)
    return path


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def _line(kind: str, content=None, **extra) -> dict:
    d = {'type': kind, 'isSidechain': False, 'timestamp': HOUR, 'sessionId': 's', 'uuid': f'u{next(_UUID)}'}
    if content is not None:
        d['message'] = {'role': kind, 'content': content}
    return {**d, **extra}


def response(message_id: str, context: int, *blocks: dict, model: str | None = 'claude-opus-5-5', **extra) -> list:
    """One API response: Claude Code writes a line per block (reasoning, text, tool) and all repeat the same `id`
    and `usage`."""
    usage = {'input_tokens': 0, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': context, 'output_tokens': 10}
    lines = []
    for b in blocks or ({'type': 'thinking', 'thinking': '', 'signature': 'x'},):
        d = _line('assistant', [b], requestId=f'req_{message_id}', **extra)
        d['message'].update(id=message_id, model=model, usage=dict(usage))
        lines.append(d)
    return lines


def text(t: str) -> dict:
    return {'type': 'text', 'text': t}


def call(use_id: str, command: str, name: str = 'Bash', **entry) -> dict:
    """A `tool_use`; in Bash, the whole command as the agent writes it."""
    return {'type': 'tool_use', 'id': use_id, 'name': name,
            'input': {'command': command, 'description': 'd', **entry} if name == 'Bash' else entry}


def result(use_id: str, content, **extra) -> dict:
    return _line('user', [{'type': 'tool_result', 'tool_use_id': use_id, 'content': content}], **extra)


def compaction() -> list:
    """The cut and the summary that opens the next stretch."""
    return [_line('system', subtype='compact_boundary', content='Conversation compacted', level='info'),
            _line('user', 'This session is being continued... Summary.', isCompactSummary=True)]


def noise() -> list:
    """Lines with no `message` that the tool has to skip."""
    return [{'type': 'queue-operation', 'operation': 'enqueue', 'sessionId': 's', 'timestamp': HOUR},
            {'type': 'cost-state', 'sessionId': 's', 'totalCostUSD': 1.0}, {'type': 'mode', 'mode': 'auto', 'sessionId': 's'}]


def log(path: str, *parts) -> str:
    """Write the log; each part is a line (dict) or a list of lines."""
    lines = [l for p in parts for l in (p if isinstance(p, list) else [p])]
    write(path, ''.join(json.dumps(l, ensure_ascii=False) + '\n' for l in lines))
    return path


def ago(hours: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).isoformat().replace('+00:00', 'Z')


class Medir(unittest.TestCase):
    def measure(self, parts: list, subagents: dict | None = None, hours: str = '0', extra: tuple = ()) -> str:
        d = folder()
        path = log(os.path.join(d, 's.jsonl'), *parts)
        for name, (kind, sub) in (subagents or {}).items():
            write(os.path.join(d, 's', 'subagents', f'{name}.meta.json'),
                  json.dumps(kind if isinstance(kind, dict) else {'agentType': kind}))
            log(os.path.join(d, 's', 'subagents', f'{name}.jsonl'), *sub)
        r = subprocess.run(['python3', MEDIR, '--session', path, '--hours', hours, *extra],
                           capture_output=True, text=True, cwd=d)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_counts_each_response_once_and_gives_the_stretches(self):
        out = self.measure([
            *noise(),
            # Two blocks of the same response: two lines with the same usage, counted once.
            response('m1', 100, text('thinking'), call('t1', '', name='Read', file_path='/a')),
            result('t1', 'x' * 350),
            response('m2', 300),
            *compaction(),
            response('m3', 50),
            response('s', 9999, isSidechain=True),
        ])
        self.assertIn('API calls: 3  |  compactions: 1', out)
        self.assertIn('Input 450 tokens', out)
        self.assertIn('Stretches between compactions: 2  |  average floor 75  |  average ceiling 175', out)
        # The Read result (100 tokens) is dragged along to the next call of the stretch: 1 call.
        self.assertRegex(out, r'Read\s+1 calls\s+100 tok\s+100 dragged')

    def test_by_file_joins_read_and_bash_with_the_path_from_the_root(self):
        # Read with an absolute path, Bash after `cd backend &&` with a path relative to that folder, and a command
        # that reads two files (split between them); `git status` reads none.
        d = folder()
        root = os.path.realpath(d)
        subprocess.run(['git', 'init', '-q', root], check=True)
        write(os.path.join(root, 'backend/src/services/narrator.ts'), 'x')
        subprocess.run(['git', '-C', root, 'add', '-A'], check=True)
        path = log(os.path.join(root, 's.jsonl'),
            response('m1', 100, call('t1', '', name='Read', file_path=f'{root}/backend/src/services/narrator.ts')),
            result('t1', 'x' * 350),
            response('m2', 100, call('t2', 'cd backend && sed -n 1,5p src/services/narrator.ts')),
            result('t2', 'x' * 350),
            response('m3', 100, call('t3', 'head -3 CLAUDE.md AGENTS.md | cut -c1-80')),
            result('t3', 'x' * 700),
            response('m4', 100, call('t4', 'git status docs/x.md')),
            result('t4', 'x' * 3500),
            # The scripts that run are not read; what the command they launch reads, is.
            response('m5', 100, call('t5', 'bash tools/host.sh grep -n x docs/y.md && ./tools/z.sh && python3 -I a/b.py')),
            result('t5', 'x' * 350),
            response('m6', 100))
        r = subprocess.run(['python3', MEDIR, '--session', path, '--hours', '0'], capture_output=True, text=True, cwd=root)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertRegex(out, r'backend/src/services/narrator.ts\s+2x\s+200 tok')
        self.assertRegex(out, r'AGENTS.md\s+1x\s+100 tok')
        self.assertRegex(out, r'CLAUDE.md\s+1x\s+100 tok')
        by_file = out.split('BY FILE')[1]
        self.assertNotIn('docs/x.md', by_file)
        self.assertRegex(by_file, r'docs/y.md\s+1x')
        for script in ('host.sh', 'z.sh', 'b.py'):
            self.assertNotIn(script, by_file)

    def test_splits_by_model_the_session_and_its_subagents(self):
        """Which model did what, with the subagents of `<session>/subagents/`."""
        out = self.measure([response('m1', 100), response('m2', 200),
                            # A subagent written in the main log is not part of the main session.
                            response('s9', 5000, isSidechain=True)], {
            'agent-a': ('general-purpose', [response('s1', 40, text('a'), text('b'), model='claude-sonnet-5-5')]),
            'agent-b': ('Explore', [response('s2', 7, model='claude-haiku-5-5')]),
        })
        self.assertRegex(out, r'main\s+claude-opus-5-5\s+2 calls\s+300 input\s+20 output')
        self.assertRegex(out, r'subagents\s+claude-sonnet-5-5\s+1 calls\s+40 input')
        self.assertIn('Subagents: 1 general-purpose (claude-sonnet-5-5) | 1 Explore (claude-haiku-5-5)', out)

    def test_breaks_down_by_subagent_and_counts_the_largest_output_of_each_response(self):
        """One row per subagent and the totals with their output; `output_tokens` grows between the lines of one
        response, the last one counts."""
        a = response('s1', 1000, text('a'), text('b'), model='claude-sonnet-5-5')
        a[0]['message']['usage']['output_tokens'] = 20  # provisional value of the first line
        a[1]['message']['usage']['output_tokens'] = 700
        b = response('s2', 3000, model='claude-sonnet-5-5')
        c = response('s3', 500, model='claude-haiku-5-5')
        out = self.measure([response('m1', 100)], {
            'agent-a': ({'agentType': 'general-purpose', 'description': 'Turn fix'}, [a, b]),
            'agent-b': ({'agentType': 'Explore'}, [c]),
            'agent-c': ({'agentType': 'Explore'}, []),  # no responses: it does not show
        })
        self.assertIn('BY SUBAGENT', out)
        self.assertRegex(out, r'Turn fix\s+general-purpose\s+claude-sonnet-5-5\s+2 calls\s+2,000 avg ctx'
                              r'\s+1,000 startup\s+4,000 input\s+710 output')
        self.assertRegex(out, r'agent-b\s+Explore\s+claude-haiku-5-5\s+1 calls\s+500 avg ctx\s+500 startup\s+500 input\s+- output')
        self.assertIn('"-": the subagent log does not keep its final output', out)
        self.assertIn('Subagents in total: 2 logs | 3 calls | 4,500 input | 720 output', out)
        self.assertIn('Average startup: 750 tokens', out)
        self.assertIn('Session + subagents: 4 calls | 4,600 input | 730 output', out)
        self.assertRegex(out, r'subagents\s+claude-sonnet-5-5\s+2 calls\s+4,000 input\s+710 output')

    def test_subagent_without_model_and_synthetic(self):
        """Model null: shows as "?" without crashing; `<synthetic>` is neither in the table nor in BY MODEL."""
        out = self.measure([response('m1', 100)], {
            'agent-a': ({'agentType': 'Explore', 'description': 'No model'}, [response('s1', 50, model=None)]),
            'agent-b': ({'agentType': 'Explore', 'description': 'Only synthetic'}, [response('s2', 60, model='<synthetic>')]),
        })
        self.assertRegex(out, r'No model\s+Explore\s+\?\s+1 calls')
        self.assertNotIn('Only synthetic', out)
        self.assertNotIn('synthetic', out)

    def test_no_subagents_no_section(self):
        self.assertNotIn('BY SUBAGENT', self.measure([response('m1', 100)]))

    def test_with_hours_the_first_half_stretch_is_not_a_floor(self):
        cut = compaction()
        for l in cut:
            l['timestamp'] = ago(1.3)
        out = self.measure([
            response('m0', 10, timestamp=ago(5)),  # outside the period: the stretch began before
            response('m1', 900, timestamp=ago(1.5)), response('m2', 1000, timestamp=ago(1.4)),
            *cut,
            response('m3', 100, timestamp=ago(1.2)), response('m4', 300, timestamp=ago(1.1)),
        ], hours='2')
        self.assertIn('Stretches between compactions: 1  |  average floor 100  |  average ceiling 300  |  2 calls per stretch'
                      '  (without the first, which began before the period)', out)
        # The average of the whole period (575) mixes the half stretch; without it, the current regime (200).
        self.assertIn('Average context per call: 575 tokens', out)
        self.assertIn('Average context without the first stretch: 200 tokens', out)
        self.assertIn('Per stretch, oldest to latest (average/ceiling, thousands): 0/0', out)

    def test_since_clips_like_hours_with_a_date_or_a_sha(self):
        """`--since` with an ISO date or a commit sha measures only from there."""
        cut = compaction()
        for l in cut:
            l['timestamp'] = ago(1.3)
        parts = [response('m0', 10, timestamp=ago(5)), response('m1', 900, timestamp=ago(1.5)), *cut,
                 response('m3', 100, timestamp=ago(1.2)), response('m4', 300, timestamp=ago(1.1))]
        out = self.measure(parts, extra=('--since', ago(2)))
        self.assertIn('API calls: 3  |  compactions: 1', out)
        self.assertIn('(without the first, which began before the period)', out)
        # With a sha: the commit date (with its offset, +02:00 = 10:00 UTC) clips; an ISO date with no zone is UTC.
        repo = folder()
        env = {**os.environ, 'GIT_COMMITTER_DATE': '2026-01-01T12:00:00+02:00', 'GIT_AUTHOR_DATE': '2026-01-01T12:00:00+02:00',
               'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_SYSTEM': os.devnull}
        for git_args in (['init', '-q'], ['-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'x']):
            subprocess.run(['git', *git_args], cwd=repo, env=env, check=True)
        sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo, capture_output=True, text=True).stdout.strip()
        path = log(os.path.join(repo, 's.jsonl'), response('a', 10, timestamp='2026-01-01T09:00:00Z'),
                   response('b', 20, timestamp='2026-01-01T11:00:00Z'), response('c', 30, timestamp='2026-01-01T12:00:00Z'))
        for value in (sha, sha[:8], '2026-01-01T10:00:00', '2026-01-01T12:00:00+02:00'):
            r = subprocess.run(['python3', MEDIR, '--session', path, '--since', value], capture_output=True, text=True, cwd=repo)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('API calls: 2  |', r.stdout, value)
        bad = subprocess.run(['python3', MEDIR, '--session', path, '--since', 'no-such-xyz'],
                             capture_output=True, text=True, cwd=repo)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn('--since: "no-such-xyz" is neither a commit nor an ISO-8601 date', bad.stderr)

    def test_warns_when_the_session_mixes_compaction_windows(self):
        """Stretches that ended in a compaction at 1,000 and then at 300: the window changed inside the period."""
        mixed = self.measure([response('a', 500), response('b', 1000), *compaction(),
                              response('c', 100), response('d', 300), *compaction(), response('e', 100)])
        self.assertIn('WARNING: this session mixes compaction windows (stretches ended in a compaction at 0k to 1k)', mixed)
        self.assertIn('--since <date or commit of the change>', mixed)
        same = self.measure([response('a', 500), response('b', 1000), *compaction(),
                             response('c', 500), response('d', 1000), *compaction(), response('e', 100)])
        self.assertNotIn('WARNING', same)
        # The open last stretch has not reached its window yet: it is no evidence of a change.
        open_last = self.measure([response('a', 500), response('b', 1000), *compaction(), response('c', 100)])
        self.assertNotIn('WARNING', open_last)


if __name__ == '__main__':
    unittest.main()
