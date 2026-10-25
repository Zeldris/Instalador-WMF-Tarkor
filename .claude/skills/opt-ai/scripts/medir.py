#!/usr/bin/env python3
"""Measure the per-call log of a local-AI run (format: references/log-format.md). Standard library only.

Usage:
  medir.py [<log.jsonl>] [--previous <log.jsonl>] [--profile X] [--exclude-task T ...] [--all-tasks]
           [--cold-ms N] [--json]

Paths: pass them as arguments, or leave them out and put them in the `opt-ai` block of the project's
`.claude/gw/opt-ai.md` (keys `log`, `previous`, `exclude_tasks`, `cold_ms`; relative paths resolve against the
repo root, found with `git rev-parse --show-toplevel`). Arguments win over the file.

Per profile, task and model (`gen_ai.request.model`, '-' if missing; row `profile/task/model`): n, p50 and p95 of
`app.duration_ms`, p50 time to first token, mean input and output tokens, generation tok/s, % cold loads
(`app.load_ms` above --cold-ms, default 100) and % truncated, over the rows that carry the field ('-' if none),
and % errors (over all rows). Failed calls (`app.error`) count in neither percentiles nor tok/s. Tasks named by
--exclude-task (default `warmup`) are left out unless --all-tasks. Retrieval calls (`gen_ai.operation.name` =
`retrieval`) get their own table: n, p50 of `app.rag.embed_ms` and `app.rag.search_ms`, mean score of the first
result. With --previous, every row shows its difference from the earlier log. Corrupt lines are skipped with a
warning; tasks with no profile are warned about.

Per turn: calls (retrieval included) that carry the same `app.turn` (any id the project picks for one user-facing
step) form a turn. One row per profile (`profile/turn/-`): n turns, p50, p95 and max of the turn (start of its first
call to end of its last, from `ts` and `app.duration_ms`), mean calls per turn and % of turns with a failed call.
Calls without `app.turn`, or without a readable `ts` and `app.duration_ms`, are left out of this table; there is no
table without `app.turn`.
Anything finer (which calls of a turn are the user-visible wait) depends on the project's own task names: derive it
from the log with a project script.
"""
import argparse
import datetime as dt
import json
import math
import re
import subprocess
import sys

COLD_MS = 100
NO_PROFILE = 'unknown'
NO_MODEL = '-'
DEFAULT_EXCLUDED = ('warmup',)
CONFIG = '.claude/gw/opt-ai.md'


def percentile(values, p):
    """Percentile p (0-100) by linear interpolation; None if there are no values."""
    v = sorted(values)
    if not v:
        return None
    if len(v) == 1:
        return float(v[0])
    k = (len(v) - 1) * p / 100
    i = int(k)
    return float(v[i]) if i + 1 >= len(v) else v[i] + (v[i + 1] - v[i]) * (k - i)


def mean(values):
    return sum(values) / len(values) if values else None


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def nums(rs, field):
    return [r[field] for r in rs if is_num(r.get(field))]


def pct(part, total):
    return 100 * part / total if total else None


def read_log(path, warnings):
    records = []
    try:
        f = open(path, encoding='utf-8', errors='replace')
    except OSError as e:
        sys.exit(f'Cannot read {path}: {e.strerror}')
    with f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                if not isinstance(r, dict):
                    raise ValueError('not an object')
                records.append(r)
            except ValueError:
                warnings.append(f'{path}: line {n} corrupt, skipped')
    return records


def call_row(rs, cold_ms=COLD_MS):
    n = len(rs)
    ok = [r for r in rs if not r.get('app.error')]
    dec = [r for r in ok if is_num(r.get('gen_ai.usage.output_tokens'))
           and is_num(r.get('app.decode_ms')) and r['app.decode_ms'] > 0]
    toks = sum(r['gen_ai.usage.output_tokens'] for r in dec)
    ms = sum(r['app.decode_ms'] for r in dec)
    dur = nums(ok, 'app.duration_ms')
    loads = nums(rs, 'app.load_ms')
    cuts = [r['app.truncated'] for r in rs if isinstance(r.get('app.truncated'), bool)]
    return {
        'n': n,
        'p50_ms': percentile(dur, 50), 'p95_ms': percentile(dur, 95),
        'ttft_p50_ms': percentile(nums(ok, 'app.ttft_ms'), 50),
        'tok_in': mean(nums(rs, 'gen_ai.usage.input_tokens')),
        'tok_out': mean(nums(rs, 'gen_ai.usage.output_tokens')),
        'tok_s': toks / (ms / 1000) if ms else None,
        'cold_pct': pct(sum(1 for x in loads if x > cold_ms), len(loads)),
        'truncated_pct': pct(sum(1 for x in cuts if x), len(cuts)),
        'error_pct': 100 * sum(1 for r in rs if r.get('app.error')) / n,
    }


def rag_row(rs):
    firsts = []
    for r in rs:
        res = r.get('app.rag.results')
        if isinstance(res, list) and res and isinstance(res[0], dict) and is_num(res[0].get('score')):
            firsts.append(res[0]['score'])
    return {'n': len(rs), 'embed_p50_ms': percentile(nums(rs, 'app.rag.embed_ms'), 50),
            'search_p50_ms': percentile(nums(rs, 'app.rag.search_ms'), 50), 'score_1': mean(firsts)}


def instant(ts):
    """Seconds since the epoch of an ISO 8601 `ts` ('Z' accepted, no zone = UTC); None if unreadable."""
    try:
        stamp = dt.datetime.fromisoformat(ts.replace('Z', '+00:00'))
    except (AttributeError, ValueError):
        return None
    return (stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)).timestamp()


def turn_row(turns):
    """turns: list of lists of call records (same profile, same `app.turn`). A turn with no readable timing is left
    out unless it failed: it still counts in `n` and `error_pct`, with no duration. Duration: earliest start (`ts` - `app.duration_ms`) to latest end (`ts`)."""
    durations, sizes, failed, n = [], [], 0, 0
    for rs in turns:
        timed = [r for r in rs if is_num(r.get('app.duration_ms')) and instant(r.get('ts')) is not None]
        has_error = any(r.get('app.error') for r in rs)
        if not timed and not has_error:
            continue
        n += 1
        failed += has_error
        sizes.append(len(rs))
        if timed:
            start = min(instant(r['ts']) * 1000 - r['app.duration_ms'] for r in timed)
            durations.append(max(instant(r['ts']) * 1000 for r in timed) - start)
    return {'n': n, 'p50_ms': percentile(durations, 50), 'p95_ms': percentile(durations, 95),
            'max_ms': max(durations) if durations else None, 'calls_per_turn': mean(sizes),
            'error_pct': pct(failed, n)}


def group(records, profile=None, excluded=DEFAULT_EXCLUDED, cold_ms=COLD_MS):
    """(call rows, retrieval rows, turn rows), each keyed by (profile, task, model)."""
    calls, rag, turns = {}, {}, {}
    for r in records:
        p = r.get('app.machine_profile') or NO_PROFILE
        if profile and p != profile:
            continue
        if r.get('app.event'):
            continue  # a marker line, not a call
        t = r.get('app.task') or 'no_task'
        if t in excluded:
            continue
        m = r.get('gen_ai.request.model') or NO_MODEL
        if r.get('app.turn'):  # retrieval calls too: the turn is everything the user waited for
            turns.setdefault(p, {}).setdefault(r['app.turn'], []).append(r)
        target = rag if r.get('gen_ai.operation.name') == 'retrieval' else calls
        target.setdefault((p, t, m), []).append(r)
    return ({k: call_row(v, cold_ms) for k, v in sorted(calls.items())},
            {k: rag_row(v) for k, v in sorted(rag.items())},
            {(p, 'turn', NO_MODEL): turn_row(list(ts.values())) for p, ts in sorted(turns.items())})


def analyse(path, profile=None, warnings=None, excluded=DEFAULT_EXCLUDED, cold_ms=COLD_MS):
    warnings = [] if warnings is None else warnings
    regs = read_log(path, warnings)
    if not regs:
        warnings.append(f'{path}: no valid records')
    calls, rag, turns = group(regs, profile, excluded, cold_ms)
    missing = sorted({t for (p, t, _m) in list(calls) + list(rag) if p == NO_PROFILE})
    if missing:
        warnings.append('tasks with no profile (is the profile variable unset?): ' + ', '.join(missing))
    return {'calls': calls, 'rag': rag, 'turns': turns, 'warnings': warnings}


def difference(current, previous):
    """Per row and numeric field: current - previous (None if either is missing); new row: 'no previous'."""
    out = {}
    for key, row in current.items():
        prev = previous.get(key)
        if prev:
            out[key] = {c: (None if not is_num(v) or not is_num(prev.get(c)) else v - prev[c])
                        for c, v in row.items()}
        else:
            out[key] = 'no previous'
    return out


def fmt(v, dec=0):
    return '-' if v is None else f'{v:.{dec}f}'


def fmt_diff(v, dec=0):
    return '' if v is None else f' ({v:+.{dec}f})'


COLS_CALLS = [('n', 0), ('p50_ms', 0), ('p95_ms', 0), ('ttft_p50_ms', 0), ('tok_in', 0), ('tok_out', 0),
              ('tok_s', 1), ('cold_pct', 0), ('truncated_pct', 0), ('error_pct', 0)]
COLS_RAG = [('n', 0), ('embed_p50_ms', 0), ('search_p50_ms', 0), ('score_1', 3)]
COLS_TURN = [('n', 0), ('p50_ms', 0), ('p95_ms', 0), ('max_ms', 0), ('calls_per_turn', 1), ('error_pct', 0)]


def table(title, rows, cols, diffs):
    if not rows:
        return []
    out = [title, '  profile/task/model  ' + '  '.join(c for c, _ in cols)]
    for (p, t, m), row in rows.items():
        d = diffs.get((p, t, m), {})
        note = '  (no previous)' if d == 'no previous' else ''
        d = d if isinstance(d, dict) else {}
        out.append(f'  {p}/{t}/{m}  ' + '  '.join(fmt(row[c], dec) + fmt_diff(d.get(c), dec) for c, dec in cols) + note)
    return out


def repo_root():
    """Repo root via git (never $CLAUDE_PROJECT_DIR or the cwd); None outside a repo."""
    try:
        out = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def read_settings(root):
    """Keys of the fenced `opt-ai` block in .claude/gw/opt-ai.md: `key: value` lines (backticks and `-` allowed)."""
    if not root:
        return {}
    try:
        with open(f'{root}/{CONFIG}', encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return {}
    m = re.search(r'^```opt-ai[ \t]*\n(.*?)^```', text, re.S | re.M)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        kv = re.match(r'^\s*[-*]?\s*([a-z_]+)\s*:\s*(.*?)\s*$', line)
        if kv and not line.lstrip().startswith('#'):
            out[kv.group(1)] = kv.group(2).strip('`')
    return out


def resolve(path, root):
    if not path or path.startswith('/') or not root:
        return path
    return f'{root}/{path}'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('log', nargs='?', help='per-call log (JSON lines); default: `log` in .claude/gw/opt-ai.md')
    ap.add_argument('--previous', help='log of the previous round, for differences; default: `previous` in the file')
    ap.add_argument('--profile', help='only this machine profile')
    ap.add_argument('--exclude-task', action='append', metavar='TASK',
                    help='leave a task out (repeatable; default `warmup`, or `exclude_tasks` in the file)')
    ap.add_argument('--all-tasks', action='store_true', help='do not exclude any task')
    ap.add_argument('--cold-ms', type=float, help=f'load time above which a call counts as cold (default {COLD_MS})')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    root = repo_root()
    cfg = read_settings(root)
    log = a.log or resolve(cfg.get('log'), root)
    if not log:
        sys.exit(f'No log given: pass <log.jsonl> or set `log:` in the opt-ai block of {CONFIG}')
    previous = a.previous or resolve(cfg.get('previous'), root)
    if a.all_tasks:
        excluded = ()
    elif a.exclude_task:
        excluded = tuple(a.exclude_task)
    elif cfg.get('exclude_tasks'):
        excluded = tuple(x.strip() for x in cfg['exclude_tasks'].split(',') if x.strip())
    else:
        excluded = DEFAULT_EXCLUDED
    try:
        cold = a.cold_ms if a.cold_ms is not None else float(cfg.get('cold_ms', COLD_MS))
    except ValueError:
        sys.exit('`cold_ms` must be a number')
    warnings = []
    cur = analyse(log, a.profile, warnings, excluded, cold)
    prev = analyse(previous, a.profile, warnings, excluded, cold) if previous else None
    d_calls = difference(cur['calls'], prev['calls']) if prev else {}
    d_rag = difference(cur['rag'], prev['rag']) if prev else {}
    d_turns = difference(cur['turns'], prev['turns']) if prev else {}
    if a.json:
        keys = lambda d: {f'{p}/{t}/{m}': v for (p, t, m), v in d.items()}
        print(json.dumps({'calls': keys(cur['calls']), 'rag': keys(cur['rag']),
                          'turns': keys(cur['turns']),
                          'difference_calls': keys(d_calls), 'difference_rag': keys(d_rag),
                          'difference_turns': keys(d_turns),
                          'warnings': warnings}, ensure_ascii=False, indent=2))
    else:
        out = table('CALLS (ms; generation tok/s; % cold/truncated/error)', cur['calls'], COLS_CALLS, d_calls)
        out += table('RAG', cur['rag'], COLS_RAG, d_rag)
        out += table('TURNS (ms from the start of the first call to the end of the last; calls with the same '
                     '`app.turn`)', cur['turns'], COLS_TURN, d_turns)
        out += ['WARNING: ' + x for x in warnings]
        print('\n'.join(out) if out else 'No data.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
