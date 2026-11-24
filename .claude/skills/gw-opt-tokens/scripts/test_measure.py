"""Tests of `measure.py` (skill `gw-opt-tokens`) against a synthetic session log whose lines have the shape of Claude Code's
real ones. Ported from the World-Maker-Fantasy pilot (tools/qa/tests/test_measure.py, @ e433d1d), with the helpers of its
`comun.py` inlined. Run: python3 -m unittest discover -s skills/gw-opt-tokens/scripts"""
import atexit
import datetime as dt
import itertools
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MEASURE = os.path.join(HERE, 'measure.py')

HOUR = '2026-10-19T10:00:00.000Z'
_UUID = itertools.count()


def folder() -> str:
    path = tempfile.mkdtemp(prefix='opt-tokens-test-')
    atexit.register(shutil.rmtree, path, True)
    return path


def copy_config_file(rel: str, repo: str) -> None:
    """D145: copy `scripts/config.py` or `schema/gw.schema.json` into a test repo, from the workflow repo root or, with
    the workflow installed in a project, from `.claude/gw/`."""
    top = os.path.join(HERE, '..', '..', '..')  # the workflow repo root, or .claude/ or .agents/ in an installed project
    project = os.path.join(top, '..')  # the project root, for the copy in .agents/skills/ (agentsSkillsDir)
    for src in (os.path.join(top, rel), os.path.join(top, 'gw', rel), os.path.join(project, '.claude', 'gw', rel)):
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(os.path.join(repo, rel)), exist_ok=True)
            shutil.copy(src, os.path.join(repo, rel))
            return
    raise FileNotFoundError(f'{rel} not found at the workflow root nor in .claude/gw/')


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


class Measure(unittest.TestCase):
    def measure(self, parts: list, subagents: dict | None = None, hours: str = '0', extra: tuple = ()) -> str:
        d = folder()
        path = log(os.path.join(d, 's.jsonl'), *parts)
        for name, (kind, sub) in (subagents or {}).items():
            write(os.path.join(d, 's', 'subagents', f'{name}.meta.json'),
                  json.dumps(kind if isinstance(kind, dict) else {'agentType': kind}))
            log(os.path.join(d, 's', 'subagents', f'{name}.jsonl'), *sub)
        r = subprocess.run(['python3', MEASURE, '--session', path, '--hours', hours, *extra],
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
            # `git config` keys and an e-mail domain are not files; what the command reads after them is.
            response('m6', 100, call('t6', 'git config user.email me@example.com && cat docs/z.md')),
            result('t6', 'x' * 350),
            # It stops at a new line or a quote, and a path after `@` is still read (review of the 0.7.0).
            response('m7', 100, call('t7', 'git config user.name Z\ncat docs/w.md')),
            result('t7', 'x' * 350),
            response('m8', 100, call('t8', 'grep -rn "git config user" docs/v.md && curl -d @docs/u.json')),
            result('t8', 'x' * 350),
            response('m9', 100))
        r = subprocess.run(['python3', MEASURE, '--session', path, '--hours', '0'], capture_output=True, text=True, cwd=root)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertRegex(out, r'backend/src/services/narrator.ts\s+2x\s+200 tok')
        self.assertRegex(out, r'AGENTS.md\s+1x\s+100 tok')
        self.assertRegex(out, r'CLAUDE.md\s+1x\s+100 tok')
        by_file = out.split('BY FILE')[1]
        self.assertNotIn('docs/x.md', by_file)
        self.assertRegex(by_file, r'docs/y.md\s+1x')
        self.assertRegex(by_file, r'docs/z.md\s+1x')
        for name in ('docs/w.md', 'docs/v.md', 'docs/u.json'):
            self.assertRegex(by_file, name + r'\s+1x')
        for name in ('user.email', 'example.com'):
            self.assertNotIn(name, by_file)
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

    def run_on(self, *parts) -> str:
        d = folder()
        path = log(os.path.join(d, 's', 'subagents', 'agent-x.jsonl'), *parts)
        r = subprocess.run(['python3', MEASURE, '--session', path, '--hours', '0'], capture_output=True, text=True, cwd=d)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_subagent_log_all_sidechain_is_measured_like_a_main_one(self):
        out = self.run_on(*noise(), response('a1', 100, isSidechain=True), response('a2', 300, isSidechain=True))
        self.assertIn('API calls: 2', out)
        self.assertIn('Input 400 tokens', out)

    def test_subagent_log_counts_each_response_once_and_keeps_tool_results(self):
        out = self.run_on(response('a1', 100, text('t'), call('t1', '', name='Read', file_path='/a'), isSidechain=True),
                          result('t1', 'x' * 350, isSidechain=True), response('a2', 300, isSidechain=True))
        self.assertIn('API calls: 2', out)
        self.assertRegex(out, r'Read\s+1 calls\s+100 tok')

    def test_mixed_log_still_drops_the_sidechain_lines(self):
        out = self.run_on(response('m1', 100), response('a1', 9999, isSidechain=True))
        self.assertIn('API calls: 1', out)
        self.assertIn('Input 100 tokens', out)

    def test_empty_subagent_log_reports_no_calls(self):
        d = folder()
        path = log(os.path.join(d, 's', 'subagents', 'agent-x.jsonl'))
        r = subprocess.run(['python3', MEASURE, '--session', path, '--hours', '0'], capture_output=True, text=True, cwd=d)
        self.assertEqual(r.returncode, 1)
        self.assertIn('No calls in that period', r.stderr)

    def test_subagent_log_with_lines_without_usage(self):
        out = self.run_on(_line('user', 'hi', isSidechain=True), response('a1', 50, isSidechain=True),
                          _line('assistant', [text('no usage')], isSidechain=True))
        self.assertIn('API calls: 1', out)
        self.assertIn('Input 50 tokens', out)

    def test_main_session_still_ignores_its_subagents_sidechain_lines(self):
        out = self.measure([response('m1', 100)], {'agent-a': ('Explore', [response('s1', 500, isSidechain=True)])})
        self.assertIn('API calls: 1', out)
        self.assertIn('Input 100 tokens', out)

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
            r = subprocess.run(['python3', MEASURE, '--session', path, '--since', value], capture_output=True, text=True, cwd=repo)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('API calls: 2  |', r.stdout, value)
        bad = subprocess.run(['python3', MEASURE, '--session', path, '--since', 'no-such-xyz'],
                             capture_output=True, text=True, cwd=repo)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn('--since: "no-such-xyz" is neither a commit nor an ISO-8601 date', bad.stderr)

    def test_since_picks_the_session_that_covers_the_period(self):
        """D70: the newest log (a later session) must not win over the one that has the calls of the period."""
        home, repo = folder(), folder()
        subprocess.run(['git', 'init', '-q', repo], check=True)
        proj = os.path.join(home, '.claude', 'projects', '-home-user')
        old = log(os.path.join(proj, 'old.jsonl'), response('a', 10, timestamp=ago(50)), response('b', 20, timestamp=ago(49)))
        new = log(os.path.join(proj, 'new.jsonl'), response('c', 30, timestamp=ago(1)))
        os.utime(old, (1, 1))  # new.jsonl is the newest file
        env = {**os.environ, 'HOME': home, 'CLAUDE_CODE_REMOTE': 'true'}
        run = lambda *args: subprocess.run(['python3', MEASURE, *args], capture_output=True, text=True, cwd=repo, env=env)
        r = run('--since', ago(60))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('Session: old.jsonl', r.stdout)
        self.assertIn('API calls: 2  |', r.stdout)
        recent = run('--since', ago(2))  # only the newest has calls there
        self.assertIn('Session: new.jsonl', recent.stdout)
        none = run('--since', ago(0.5))  # nobody covers it: the newest, then the usual "no calls" exit
        self.assertNotEqual(none.returncode, 0)
        self.assertIn('No calls in that period', none.stderr)
        self.assertTrue(os.path.exists(new))

    def clear_line(self, hours_ago: float) -> dict:
        return _line('user', '<command-name>/clear</command-name>\n<command-message>clear</command-message>\n'
                             '<command-args></command-args>', timestamp=ago(hours_ago))

    def run_session(self, parts: list, *args: str) -> subprocess.CompletedProcess:
        d = folder()
        path = log(os.path.join(d, 's.jsonl'), *parts)
        return subprocess.run(['python3', MEASURE, '--session', path, *args], capture_output=True, text=True, cwd=d)

    def test_d138_default_starts_after_the_last_clear(self):
        parts = [response('a', 10, timestamp=ago(5)), response('b', 20, timestamp=ago(4)), self.clear_line(3),
                 response('c', 30, timestamp=ago(2))]
        r = self.run_session(parts)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('API calls: 1  |', r.stdout)
        self.assertIn('period: since the last /clear (', r.stdout)

    def test_d138_without_a_clear_keeps_the_24_hours(self):
        parts = [response('a', 10, timestamp=ago(30)), response('b', 20, timestamp=ago(5)), response('c', 30, timestamp=ago(2))]
        r = self.run_session(parts)
        self.assertIn('API calls: 2  |', r.stdout)
        self.assertIn('period: last 24 h', r.stdout)

    def test_d138_the_later_of_clear_and_compaction_wins(self):
        def boundary(hours_ago):
            return _line('system', subtype='compact_boundary', content='Conversation compacted', timestamp=ago(hours_ago))
        later_compaction = [response('a', 10, timestamp=ago(6)), self.clear_line(5), response('b', 20, timestamp=ago(4)),
                            boundary(3), response('c', 30, timestamp=ago(2)), response('d', 40, timestamp=ago(1))]
        r = self.run_session(later_compaction)
        self.assertIn('API calls: 2  |  compactions: 0', r.stdout)
        self.assertIn('since the last compaction (', r.stdout)
        later_clear = [response('a', 10, timestamp=ago(6)), boundary(5), response('b', 20, timestamp=ago(4)),
                       self.clear_line(3), response('c', 30, timestamp=ago(2))]
        r = self.run_session(later_clear)
        self.assertIn('API calls: 1  |', r.stdout)
        self.assertIn('since the last /clear (', r.stdout)

    def test_d138_explicit_since_or_hours_do_not_apply_it(self):
        parts = [response('a', 10, timestamp=ago(5)), self.clear_line(3), response('c', 30, timestamp=ago(2))]
        for args in (('--since', ago(10)), ('--hours', '10'), ('--hours', '0')):
            r = self.run_session(parts, *args)
            self.assertIn('API calls: 2  |', r.stdout, args)
            self.assertNotIn('/clear (', r.stdout, args)

    def test_d138_a_clear_mentioned_in_text_is_not_a_clear(self):
        parts = [response('a', 10, timestamp=ago(5)),
                 _line('user', 'I ran <command-name>/clear</command-name> before', timestamp=ago(4)),
                 response('b', 20, timestamp=ago(3))]
        self.assertIn('API calls: 2  |', self.run_session(parts).stdout)

    def test_d138_clear_is_found_with_the_message_tag_first_or_list_content(self):
        for content in ('<command-message>clear</command-message>\n<command-name>/clear</command-name>\n<command-args></command-args>',
                        [{'type': 'text', 'text': '<command-message>clear</command-message>\n'
                                                  '<command-name>/clear</command-name>'}]):
            parts = [response('a', 10, timestamp=ago(5)), _line('user', content, timestamp=ago(3)),
                     response('b', 30, timestamp=ago(2))]
            r = self.run_session(parts)
            self.assertIn('API calls: 1  |', r.stdout, content)
            self.assertIn('since the last /clear (', r.stdout, content)

    def break_session(self, calls_before: int, break_line, calls_after: int, prev_calls: int = 3) -> subprocess.CompletedProcess:
        """D138: no --session; `cur.jsonl` (newest) has `calls_before` calls, a break 1 h ago, `calls_after` after it."""
        home, repo = folder(), folder()
        subprocess.run(['git', 'init', '-q', repo], check=True)
        proj = os.path.join(home, '.claude', 'projects', '-home-user')
        prev = log(os.path.join(proj, 'prev.jsonl'),
                   *[response(f'p{n}', 50, timestamp=ago(4), gitBranch='feat') for n in range(prev_calls)])
        os.utime(prev, (100, 100))
        parts = [response(f'b{n}', 10, timestamp=ago(3), gitBranch='feat') for n in range(calls_before)]
        parts.append(break_line)
        parts += [response(f'a{n}', 10, timestamp=ago(0.5), gitBranch='feat') for n in range(calls_after)]
        log(os.path.join(proj, 'cur.jsonl'), *parts)
        env = {**os.environ, 'HOME': home, 'CLAUDE_CODE_REMOTE': 'true'}
        return subprocess.run(['python3', MEASURE], capture_output=True, text=True, cwd=repo, env=env)

    def test_d138_min_calls_looks_at_the_stretch_after_the_break(self):
        compaction_line = _line('system', subtype='compact_boundary', content='Conversation compacted', timestamp=ago(1))
        # 300 calls in 24 h but 1 after the compaction: the fallback triggers on the reported stretch
        r = self.break_session(300, compaction_line, 1)
        self.assertIn('Note: the current session has 1 calls (under measure.minCalls = 5)', r.stdout)
        self.assertIn('Session: prev.jsonl', r.stdout)
        # the previous session is measured whole, not cut to its own tail by its own break
        r = self.break_session(2, self.clear_line(1), 6)
        self.assertIn('Session: cur.jsonl', r.stdout)
        self.assertNotIn('Note:', r.stdout)
        self.assertIn('API calls: 6  |', r.stdout)

    def d139_logs(self, own_mtime, parent_mtime):
        home, repo = folder(), folder()
        subprocess.run(['git', 'init', '-q', repo], check=True)
        root = os.path.realpath(repo)
        parent = os.path.join(home, '.claude', 'projects', re.sub(r'[^A-Za-z0-9]', '-', os.path.dirname(root)))
        own = os.path.join(home, '.claude', 'projects', re.sub(r'[^A-Za-z0-9]', '-', root))
        up = log(os.path.join(parent, 'up.jsonl'), *[response(f'p{n}', 5, timestamp=ago(2)) for n in range(4)])
        mine = log(os.path.join(own, 'own.jsonl'), response('o', 5, timestamp=ago(2)))
        os.utime(mine, (own_mtime, own_mtime))
        os.utime(up, (parent_mtime, parent_mtime))
        env = {**os.environ, 'HOME': home}
        return lambda *a: subprocess.run(['python3', MEASURE, *a], capture_output=True, text=True, cwd=root, env=env), mine

    def test_d139_the_repo_folder_wins_over_a_parent_folder_with_more_calls(self):
        run, mine = self.d139_logs(500, 500)  # D144: only on a tie; the explicit period keeps the covering rule
        r = run('--since', ago(3))
        self.assertIn('Session: own.jsonl', r.stdout)
        self.assertIn('API calls: 1  |', r.stdout)
        os.remove(mine)  # the repo's folder has none: the parent's is the fallback
        self.assertIn('Session: up.jsonl', run('--since', ago(3)).stdout)

    def test_d144_without_a_period_the_newest_session_of_all_folders_is_measured(self):
        run, _ = self.d139_logs(100, 500)  # the parent folder's log is newer (the session in progress)
        r = run()
        self.assertIn('Session: up.jsonl', r.stdout)
        self.assertIn('API calls: 4  |', r.stdout)
        run, _ = self.d139_logs(500, 100)  # the repo folder's log is newer
        self.assertIn('Session: own.jsonl', run().stdout)
        run, _ = self.d139_logs(500, 500)  # a tie in mtime: D139 prefers the repo folder
        self.assertIn('Session: own.jsonl', run().stdout)

    def test_d151_a_new_session_without_branch_never_measures_one_of_another_branch(self):
        r = self.short_session(2, previous=(('other', 'main'),), branch=None, args=())  # the default period: 24 h
        self.assertIn('Session: cur.jsonl', r.stdout)
        self.assertNotIn('other.jsonl', r.stdout)
        self.assertIn('API calls: 2', r.stdout)

    def test_d151_explicit_period_never_picks_a_log_of_another_branch(self):
        for args in (('--hours', '24'), ('--since', ago(5))):
            r = self.short_session(5, previous=(('other', 'main'),), args=args, previous_calls=7)  # other has more calls
            self.assertIn('Session: cur.jsonl', r.stdout, args)
            self.assertNotIn('other.jsonl', r.stdout)

    def test_d151_explicit_period_current_log_without_branch_uses_the_repo_branch(self):
        for args in (('--hours', '24'), ('--since', ago(5))):
            r = self.short_session(5, previous=(('other', 'main'),), args=args, previous_calls=7, branch=None,
                                   repo_branch='feat')  # other has more calls and is of another branch
            self.assertIn('Session: cur.jsonl', r.stdout, args)
            self.assertNotIn('other.jsonl', r.stdout)
        r = self.short_session(5, previous=(('same', 'feat'),), args=('--hours', '24'), previous_calls=7, branch=None,
                               repo_branch='feat')  # a log of the repo's branch still competes
        self.assertIn('Session: same.jsonl', r.stdout)

    def test_d144_newest_session_without_calls_in_the_default_period_is_still_the_one(self):
        home, repo = folder(), folder()
        subprocess.run(['git', 'init', '-q', repo], check=True)
        proj = os.path.join(home, '.claude', 'projects', '-home-user')
        old = log(os.path.join(proj, 'older.jsonl'), *[response(f'o{n}', 5, timestamp=ago(2)) for n in range(3)])
        log(os.path.join(proj, 'cur.jsonl'), response('c', 5, timestamp=ago(30)))  # the newest file, calls out of the 24 h
        os.utime(old, (100, 100))
        env = {**os.environ, 'HOME': home, 'CLAUDE_CODE_REMOTE': 'true'}
        r = subprocess.run(['python3', MEASURE], capture_output=True, text=True, cwd=repo, env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('No calls in that period', r.stderr)
        self.assertNotIn('older.jsonl', r.stdout)

    def test_artifact_rows_show_the_action(self):
        """B22: HEAVIEST RESULTS tells `quickstart` from `publish` for Artifact calls."""
        parts = [response('a', 100, call('t1', '', name='Artifact', action='quickstart', intent='other')),
                 result('t1', 'x' * 7000),
                 response('b', 200, call('t2', '', name='Artifact', file_path='/tmp/p.html', icon='chart')),
                 result('t2', 'y' * 3500),
                 response('c', 300, text('end'))]
        out = self.measure(parts)
        self.assertIn('Artifact: action=quickstart {"intent": "other"}', out)
        self.assertIn('Artifact: action=publish file_path=/tmp/p.html', out)

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

    def default_log(self, remote: str | None) -> subprocess.CompletedProcess:
        """Run without --session in a repo whose only log is in `-home-user`, with a temp HOME."""
        home, repo = folder(), folder()
        subprocess.run(['git', 'init', '-q', repo], check=True)
        log(os.path.join(home, '.claude', 'projects', '-home-user', 's.jsonl'), response('m1', 100))
        env = {k: v for k, v in os.environ.items() if k != 'CLAUDE_CODE_REMOTE'}
        env['HOME'] = home
        if remote is not None:
            env['CLAUDE_CODE_REMOTE'] = remote
        return subprocess.run(['python3', MEASURE, '--hours', '0'], capture_output=True, text=True, cwd=repo, env=env)

    def test_cloud_start_folder_gives_no_outside_the_repo_warning(self):
        cloud = self.default_log('true')
        self.assertEqual(cloud.returncode, 0, cloud.stderr)
        self.assertIn('API calls: 1', cloud.stdout)  # the same log is chosen
        self.assertNotIn('opened outside the repo', cloud.stderr)

    def test_outside_the_repo_warns_when_not_in_the_cloud(self):
        for remote in (None, 'false'):
            local = self.default_log(remote)
            self.assertEqual(local.returncode, 0, local.stderr)
            self.assertIn('API calls: 1', local.stdout)
            self.assertIn('warning: log from a session opened outside the repo, in folder -home-user', local.stderr)

    def short_session(self, current: int, config=None, previous: tuple = (('prev', 'feat'),), branch: str | None = 'feat',
                      args: tuple = ('--hours', '0'), previous_calls: int = 3, branches: tuple = (),
                      repo_branch: str | None = None) -> subprocess.CompletedProcess:
        """B29: no --session; the current log (`cur.jsonl`, newest, `current` calls on `branch`) and older logs given
        as (name, branch) with 3 calls each; `config` is the text of the repo's .claude/gw.json (None = no file)."""
        home, repo = folder(), folder()
        subprocess.run(['git', 'init', '-q', repo], check=True)
        if repo_branch:
            subprocess.run(['git', '-C', repo, 'symbolic-ref', 'HEAD', f'refs/heads/{repo_branch}'], check=True)
        proj = os.path.join(home, '.claude', 'projects', '-home-user')
        for i, (name, b) in enumerate(previous):
            extra = {'gitBranch': b} if b else {}
            path = log(os.path.join(proj, f'{name}.jsonl'),
                       *[response(f'{name}{n}', 50, timestamp=ago(2), **extra) for n in range(previous_calls)])
            os.utime(path, (100 + i if i >= 0 else 100, 100 + i))
        extra = {'gitBranch': branch} if branch else {}
        parts = [response(f'c{n}', 10, timestamp=ago(0.1), **extra) for n in range(current)]
        for b in branches:  # the session ends on the last of these branches
            parts.insert(0, response('sw', 10, timestamp=ago(0.2), gitBranch=b))
        log(os.path.join(proj, 'cur.jsonl'), *parts)
        if config is not None:
            write(os.path.join(repo, '.claude', 'gw.json'), config)
            for rel in ('scripts/config.py', 'schema/gw.schema.json'):
                copy_config_file(rel, repo)
        env = {**os.environ, 'HOME': home, 'CLAUDE_CODE_REMOTE': 'true'}
        return subprocess.run(['python3', MEASURE, *args], capture_output=True, text=True, cwd=repo, env=env)

    CONFIG = '{"version": "0.1.0", "language": "en", "log": "docs/log.md", "protectedBranch": "main", ' \
             '"pushToProtected": "pr", "check": ["make check"], "reviewMark": "docs/reviewed.txt", ' \
             '"content": ["^docs/"]%s}'

    def test_short_session_measures_the_previous_one_of_the_same_branch(self):
        r = self.short_session(2)  # no config file: minCalls 5
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('Session: prev.jsonl', r.stdout)
        self.assertIn('API calls: 3', r.stdout)
        self.assertIn('Note: the current session has 2 calls (under measure.minCalls = 5); '
                      'measuring the previous session of branch feat: prev.jsonl', r.stdout)

    def test_enough_calls_measures_the_current_one(self):
        for n in (5, 6):  # the threshold itself is enough
            r = self.short_session(n)
            self.assertIn('Session: cur.jsonl', r.stdout)
            self.assertNotIn('Note:', r.stdout)

    def test_previous_session_of_another_branch_or_without_branch_is_not_used(self):
        r = self.short_session(2, previous=(('other', 'main'),))
        self.assertIn('Session: cur.jsonl', r.stdout)
        self.assertIn('there is no previous session of branch feat: measuring cur.jsonl', r.stdout)
        self.assertIn('API calls: 2', r.stdout)
        # the previous one is the newest of the same branch, skipping other branches in between
        r = self.short_session(2, previous=(('old', 'feat'), ('mid', 'main')))
        self.assertIn('Session: old.jsonl', r.stdout)

    def test_no_previous_session_measures_the_current_one_with_a_note(self):
        r = self.short_session(2, previous=())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('Session: cur.jsonl', r.stdout)
        self.assertIn('Note: the current session has 2 calls (under measure.minCalls = 5) and there is no '
                      'previous session of branch feat: measuring cur.jsonl', r.stdout)

    def test_previous_session_without_calls_in_the_period_is_skipped(self):
        r = self.short_session(2, args=('--since', ago(1)))  # prev.jsonl calls are stamped HOUR (2026-10-19)
        self.assertIn('Session: cur.jsonl', r.stdout)
        self.assertIn('there is no previous session', r.stdout)

    def test_min_calls_zero_turns_it_off(self):
        r = self.short_session(1, config=self.CONFIG % ', "measure": {"minCalls": 0}')
        self.assertIn('Session: cur.jsonl', r.stdout)
        self.assertNotIn('Note:', r.stdout)

    def test_min_calls_comes_from_the_config(self):
        low = self.short_session(2, config=self.CONFIG % ', "measure": {"minCalls": 2}')
        self.assertIn('Session: cur.jsonl', low.stdout)
        high = self.short_session(5, config=self.CONFIG % ', "measure": {"minCalls": 6}')
        self.assertIn('Session: prev.jsonl', high.stdout)
        self.assertIn('measure.minCalls = 6', high.stdout)
        absent = self.short_session(2, config=self.CONFIG % '')  # valid config without the key: the default
        self.assertIn('Session: prev.jsonl', absent.stdout)

    def chars_per_token_in(self, config):
        import importlib.util
        spec = importlib.util.spec_from_file_location('measure_mod', MEASURE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        repo = folder()
        subprocess.run(['git', 'init', '-q', repo], check=True)
        if config is not None:
            write(os.path.join(repo, '.claude', 'gw.json'), config)
            for rel in ('scripts/config.py', 'schema/gw.schema.json'):
                copy_config_file(rel, repo)
        return mod.chars_per_token(repo)

    def test_chars_per_token_comes_from_the_context_guard_config(self):
        self.assertEqual(self.chars_per_token_in(None), 3.5, 'no config: the built-in value')
        self.assertEqual(self.chars_per_token_in(self.CONFIG % ''), 3.5, 'valid config without the key: the default')
        self.assertEqual(self.chars_per_token_in(self.CONFIG % ', "contextGuard": {"charsPerToken": 4}'), 4.0)
        self.assertEqual(self.chars_per_token_in(self.CONFIG % ', "contextGuard": {"charsPerToken": 0}'), 3.5,
                         'an invalid value (the config fails closed) keeps 3.5')
        self.assertEqual(self.chars_per_token_in('{not json'), 3.5)

    def measure_value_in(self, config, name, default, integer):
        import importlib.util
        spec = importlib.util.spec_from_file_location('measure_mod2', MEASURE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        repo = folder()
        subprocess.run(['git', 'init', '-q', repo], check=True)
        if config is not None:
            write(os.path.join(repo, '.claude', 'gw.json'), config)
            for rel in ('scripts/config.py', 'schema/gw.schema.json'):
                copy_config_file(rel, repo)
        return mod.measure_value(repo, name, default, integer)

    def test_a13_measure_constants_default_set_and_bad_values(self):
        for name, default, integer, good, shown in (('imageTokens', 1600, True, 2000, 2000),
                                                    ('mixedRatio', 1.5, False, 2.5, 2.5),
                                                    ('minOutput', 100, True, 7, 7)):
            def in_(config):
                return self.measure_value_in(config, name, default, integer)
            self.assertEqual(in_(None), default, name + ': no config')
            self.assertEqual(in_(self.CONFIG % ''), default, name + ': valid config without the key')
            self.assertEqual(in_(self.CONFIG % ', "measure": {"%s": %s}' % (name, good)), shown, name + ': set value')
            for bad in ('0', '-3', '"x"'):  # the config fails closed (its reason: the schema minimum or type): default
                self.assertEqual(in_(self.CONFIG % ', "measure": {"%s": %s}' % (name, bad)), default, name + bad)
            self.assertEqual(in_('{not json'), default)

    def fixed_startup_run(self, with_workflow: bool, *extra, installed_guard: str = '', sidechain: bool = False) -> str:
        """E76: a repo with AGENTS.md of 3,500 characters (1,000 tokens), no log and no skills, and a session of three
        calls of 10,000 tokens each: the fixed startup is the first call minus the project's part."""
        repo = folder()
        subprocess.run(['git', 'init', '-q', repo], check=True)
        write(os.path.join(repo, 'AGENTS.md'), 'x' * 3500)
        if with_workflow:
            for rel in ('scripts', 'schema'):
                top = os.path.join(HERE, '..', '..', '..')
                for base in (top, os.path.join(top, 'gw'), os.path.join(top, '..', '.claude', 'gw')):
                    if os.path.isdir(os.path.join(base, rel)):
                        break
                shutil.copytree(os.path.join(base, rel), os.path.join(repo, rel),
                                ignore=shutil.ignore_patterns('__pycache__'))
        if installed_guard:  # an installed copy that fails on import
            write(os.path.join(repo, '.claude', 'gw', 'scripts', 'context_guard.py'), installed_guard)
        calls = [response(f'm{i}', 10000, isSidechain=sidechain) for i in (1, 2, 3)]
        path = log(os.path.join(repo, 's.jsonl'), *calls, *extra)
        r = subprocess.run(['python3', MEASURE, '--session', path, '--hours', '0'], capture_output=True, text=True,
                           cwd=repo, env={**os.environ, 'HOME': folder()})
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_e76_the_fixed_startup_is_shown_apart_from_the_project_cost(self):
        out = self.fixed_startup_run(True)
        self.assertIn('Fixed startup (system prompt, tools, MCP; per call, neither /clear nor the project shrinks it, so '
                      'the total falls only with fewer calls or fewer MCP servers and connectors; it also holds the '
                      'SessionStart hook output, which the log does not keep): ~9,000 tokens per call x 3 calls = '
                      '27,000 input (90 %)', out)
        self.assertIn('Project cost (the rest: instructions, log, skills, conversation, results): '
                      '3,000 input (10 %)', out)

    def test_e76_synthetic_messages_do_not_count_as_calls_carrying_the_fixed_startup(self):
        out = self.fixed_startup_run(True, response('x1', 0, model='<synthetic>'), response('x2', 0, model='<synthetic>'))
        self.assertIn('~9,000 tokens per call x 3 calls = 27,000 input (90 %)', out)

    def test_e76_a_failing_installed_copy_gives_way_to_the_repo_one(self):
        out = self.fixed_startup_run(True, installed_guard='raise SystemExit(3)\n')
        self.assertIn('~9,000 tokens per call x 3 calls', out)

    def test_e76_a_failing_copy_alone_says_why(self):
        out = self.fixed_startup_run(False, installed_guard='raise SystemExit(3)\n')
        self.assertIn('Fixed startup: unknown (.claude/gw/scripts/context_guard.py failed: SystemExit(3))', out)

    def test_e76_a_subagent_log_says_the_split_does_not_apply(self):
        out = self.fixed_startup_run(True, sidechain=True)
        self.assertIn('Fixed startup: unknown (the split does not apply to a subagent log)', out)

    def test_e76_without_the_workflow_scripts_the_fixed_startup_is_unknown(self):
        out = self.fixed_startup_run(False)
        self.assertIn('Fixed startup: unknown (no context_guard.py of the workflow in .claude/gw/scripts/ or scripts/)',
                      out)
        self.assertNotIn('Project cost', out)

    def test_malformed_or_invalid_config_falls_back_to_the_default(self):
        for config in ('{not json', self.CONFIG % ', "measure": {"minCalls": -1}',
                       self.CONFIG % ', "measure": {"minCalls": "x"}'):
            r = self.short_session(2, config=config)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('Session: prev.jsonl', r.stdout, config)
            self.assertIn('measure.minCalls = 5', r.stdout)

    def test_default_period_after_a_clear_still_measures_the_previous_session(self):
        """The previous log (more calls, inside the 24 h) must not be taken as the current session."""
        r = self.short_session(1, previous_calls=8, args=())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('Session: prev.jsonl', r.stdout)
        self.assertIn('API calls: 8', r.stdout)
        self.assertIn('Note: the current session has 1 calls', r.stdout)
        enough = self.short_session(6, previous_calls=8, args=())  # current has enough: the usual choice
        self.assertNotIn('Note:', enough.stdout)

    def test_session_that_switched_branch_counts_by_its_last_branch(self):
        r = self.short_session(2, previous=(('onfeat', 'feat'), ('onmain', 'main')), branches=('main',), branch='feat')
        self.assertIn('Session: onfeat.jsonl', r.stdout)  # ended on feat, though it began on main
        r = self.short_session(2, previous=(('onfeat', 'feat'), ('onmain', 'main')), branches=('feat',), branch='main')
        self.assertIn('Session: onmain.jsonl', r.stdout)

    def test_current_session_without_branch_is_measured_with_a_note(self):
        r = self.short_session(2, branch=None)  # detached HEAD or an old log: no gitBranch
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('Session: cur.jsonl', r.stdout)
        self.assertIn('there is no previous session of its branch: measuring cur.jsonl', r.stdout)

    def test_previous_sessions_with_the_same_mtime_break_the_tie_by_name(self):
        home, repo = folder(), folder()
        subprocess.run(['git', 'init', '-q', repo], check=True)
        proj = os.path.join(home, '.claude', 'projects', '-home-user')
        for name in ('a', 'b'):
            os.utime(log(os.path.join(proj, f'{name}.jsonl'),
                         *[response(f'{name}{n}', 5, gitBranch='feat', timestamp=ago(2)) for n in range(3)]), (100, 100))
        log(os.path.join(proj, 'cur.jsonl'), response('c', 10, gitBranch='feat', timestamp=ago(0.1)))
        env = {**os.environ, 'HOME': home, 'CLAUDE_CODE_REMOTE': 'true'}
        r = subprocess.run(['python3', MEASURE, '--hours', '0'], capture_output=True, text=True, cwd=repo, env=env)
        self.assertIn('Session: b.jsonl', r.stdout)

    def test_explicit_session_is_never_replaced(self):
        out = self.measure([response('a', 10, gitBranch='feat')])  # --session with 1 call
        self.assertIn('Session: s.jsonl', out)
        self.assertNotIn('Note:', out)


if __name__ == '__main__':
    unittest.main()
