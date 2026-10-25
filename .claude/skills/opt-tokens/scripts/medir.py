#!/usr/bin/env python3
"""Where the tokens of a Claude Code session went (skill `opt-tokens`). Python 3 standard library only.

Reads the session log (`~/.claude/projects/<folder>/<session>.jsonl`) and reports:
  - the real API usage (input, cache written, cache read, output) of the calls in the period;
  - per tool: calls, the tokens its results put into the context and the tokens **dragged along** (every result is
    sent again on every later call until the next compaction: a 5k-token result with 200 calls after it weighs 1M);
  - the heaviest results, images, errors, and repeats (same file read or same command run again);
  - per file: how many times each was read (Read, or Bash with cat/sed/head/grep... on its path) and what those
    reads dragged along: a big file that is re-read wants a pointer in a map or a tool;
  - per model, the main session and its subagents (`<session>/subagents/*.jsonl`): is mechanical work going to the
    expensive model, or design to a cheap one;
  - per subagent (description, type, model, calls, average context, input, output) and the session + subagents total.
    Output is the largest value among the lines of a response, not the first.

Session lookup: the project root comes from `git rev-parse --show-toplevel`. The log is searched in the folder of
the root and in the folders of its parent directories (a session opened in a folder that contains the repo stores
its log there), never in sibling repos; the newest log wins. If it is not the root's own folder, a warning goes to
stderr: that session may belong to another project, and it did not load the repo's `.claude/settings.json`. Last
resort: the log folder of the home directory's cloud start (`-home-user`). Pass `--session` to skip the search.

Tokens of a result are estimated from its size (characters / 3.5; an image counts ~1,600). API usage is exact.
"""
import argparse
import collections
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys

IMAGE_TOKENS = 1600
CHARS_PER_TOKEN = 3.5
MIXED_RATIO = 1.5  # peaks of closed stretches whose max/min exceeds this: the session mixes compaction windows
MIN_OUTPUT = 100  # output tokens per call below which a subagent log's output is not trustworthy


def git(*args, cwd=None):
    """stdout of a git command, or None if git is missing or the command fails."""
    try:
        r = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True)
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def project_root():
    """Repo root via git (never $CLAUDE_PROJECT_DIR or the cwd, which move when a tool does `cd`)."""
    return git('rev-parse', '--show-toplevel') or os.getcwd()


def since_moment(value):
    """`--since` takes a commit (its commit date) or an ISO-8601 date (no zone = UTC). Always returns UTC."""
    sha = git('rev-parse', '--verify', '--quiet', f'{value}^{{commit}}')
    if sha:
        stamp = dt.datetime.fromisoformat(git('show', '-s', '--format=%cI', sha))
    else:
        try:
            stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            sys.exit(f'--since: "{value}" is neither a commit nor an ISO-8601 date')
    return (stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)).astimezone(dt.timezone.utc)


def folder_of(path):
    """Name Claude Code gives to the log folder of a working directory."""
    return re.sub(r'[^A-Za-z0-9]', '-', path)


def default_session(root):
    """Newest `.jsonl` of the root's log folder or of a parent folder's; exits if there is none."""
    root = os.path.abspath(root)
    folders, current = [], root
    while True:
        folders.append(folder_of(current))
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    folders.append('-home-user')  # cloud sessions start in /home/user whatever repo they work on
    candidates = [p for f in dict.fromkeys(folders)
                  for p in glob.glob(os.path.expanduser(f'~/.claude/projects/{f}/*.jsonl'))]
    if not candidates:
        sys.exit(f'No sessions in ~/.claude/projects/{folder_of(root)}/ or its parent folders (use --session)')
    path = max(candidates, key=os.path.getmtime)
    folder = os.path.basename(os.path.dirname(path))
    if folder != folder_of(root):
        print(f'(warning: log from a session opened outside the repo, in folder {folder}; '
              f'if it is not this session, pass --session)', file=sys.stderr)
    return path


def tokens_of(content):
    """Estimated tokens and image count of a `tool_result`."""
    if isinstance(content, str):
        return len(content) / CHARS_PER_TOKEN, 0
    total, images = 0.0, 0
    for block in content or []:
        if block.get('type') == 'image':
            images += 1
            total += IMAGE_TOKENS
        else:
            total += len(block.get('text', '') or '') / CHARS_PER_TOKEN
    return total, images


def input_summary(entry):
    for key in ('command', 'file_path', 'pattern', 'url', 'query', 'skill', 'description'):
        if key in entry:
            return f'{key}={str(entry[key])[:110]}'
    return json.dumps(entry, ensure_ascii=False)[:110]


FILE_RE = re.compile(r'(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.(?:[a-z]{1,5}))(?![\w/])')
READS = re.compile(r'(?:^|[|;&(]\s*|\s)(?:cat|sed|head|tail|grep|rg|awk|wc|less|nl|cut)\s')
CD = re.compile(r'^\s*cd\s+(\S+)\s*&&')
# What comes right after an interpreter (or `./`) is executed, not read: `bash scripts/run.sh grep ...`.
EXECUTES = re.compile(r'(?:^|[|;&(]\s*|\s)(?:(?:bash|sh|python3?|node)\s+(?:-\S+\s+)*|(?=\./))(\S+)')


def files_read(name, entry, root):
    """Files a call reads, as paths from the repo root. Read: its `file_path`; Bash: the paths of the command if it
    has a read command (relative to `<dir>` after a leading `cd <dir> &&`), except the scripts it executes."""
    if name == 'Read' and entry.get('file_path'):
        paths = [entry['file_path']]
    elif name == 'Bash' and READS.search(entry.get('command') or ''):
        command = entry['command']
        cd = CD.match(command)
        base = cd.group(1) if cd else ''
        executed = {os.path.normpath(e) for e in EXECUTES.findall(command)}
        paths = [p if p.startswith('/') or not base else os.path.join(base, p)
                 for p in FILE_RE.findall(command) if os.path.normpath(p) not in executed]
    else:
        return []
    prefix = root.rstrip('/') + '/'
    return sorted({repo_path(os.path.normpath(p[len(prefix):] if p.startswith(prefix) else p), root) for p in paths})


def repo_path(path, root, cache={}):
    """A path relative to another working directory (`src/x.ts` from `backend/`) is resolved to the only tracked
    file that ends the same way; if there are several or none, it stays as it is."""
    if root not in cache:
        cache[root] = (git('ls-files', cwd=root) or '').split()
    if path in cache[root] or path.startswith('/'):
        return path
    same = [f for f in cache[root] if f.endswith('/' + path)]
    return same[0] if len(same) == 1 else path


def parse_time(stamp):
    return dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))


def responses_of(path, since):
    """API responses of a log, one per message id: list of (model, context, output).
    Claude Code writes one line per block with the same `usage`, but `output_tokens` grows from one line to the
    next (the first holds a provisional value): the real output is the maximum over the lines of one id."""
    by_id = {}
    with open(path, encoding='utf-8') as log:
        for line in log:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            m = d.get('message') or {}
            if d.get('type') != 'assistant' or not m.get('usage') or (m.get('model') or '').startswith('<'):
                continue
            stamp = d.get('timestamp')
            if since and stamp and parse_time(stamp) < since:
                continue
            u = m['usage']
            ctx = sum(u.get(k) or 0 for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'))
            key = m.get('id') or d.get('requestId') or d.get('uuid')
            before = by_id.get(key)
            by_id[key] = (m.get('model') or '?', ctx, max(u.get('output_tokens') or 0, before[2] if before else 0))
    return list(by_id.values())


def add_model_usage(path, since, per_model, who):
    """Add a subagent log's calls, input and output to `per_model[(who, model)]`; return its responses."""
    responses = responses_of(path, since)
    for model, ctx, out in responses:
        p = per_model[(who, model)]
        p[0] += 1
        p[1] += ctx
        p[2] += out
    return responses


def main():
    ap = argparse.ArgumentParser(
        description='Where the tokens of a Claude Code session went: API usage, context curve, heavy results, '
                    'repeats, per-file reads, per-model and per-subagent split. Standard library only.')
    ap.add_argument('--session', metavar='PATH.jsonl',
                    help='session log to read (default: newest of the repo folder or its parent folders)')
    ap.add_argument('--hours', type=float, default=24, help='period in hours, 0 = the whole session (default 24)')
    ap.add_argument('--since', metavar='ISO|SHA',
                    help='only from that moment (commit: its date; ISO-8601 date, no zone = UTC); replaces --hours')
    ap.add_argument('--top', type=int, default=12, help='rows per list (default 12)')
    a = ap.parse_args()
    root = project_root()
    path = a.session or default_session(root)
    since = None
    if a.since:
        since = since_moment(a.since)
    elif a.hours > 0:
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=a.hours)

    usage = collections.Counter()
    api_calls = 0
    contexts = []  # context of each call, for the curve between compactions
    tool_uses = {}  # id -> (name, summary, full input)
    tool_files = {}  # id -> files it reads
    results = []  # (call_index, id, tokens, images, is_error)
    cuts = []  # call index at which a compaction happened
    seen = {}  # message id -> index of its call (to keep the largest output)
    outputs = []  # output of each call
    call_models = []  # model of each call (or None)
    per_model = collections.defaultdict(lambda: [0, 0, 0])  # (who, model) -> calls, input, output
    clipped = False  # with --hours/--since: the session started before the period
    with open(path, encoding='utf-8') as log:
        for line in log:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            stamp = d.get('timestamp')
            if since and stamp and parse_time(stamp) < since:
                clipped = True
                continue
            if d.get('isSidechain'):
                continue
            if d.get('type') == 'system' and d.get('subtype') == 'compact_boundary':
                cuts.append(api_calls)
                continue
            m = d.get('message') or {}
            if d.get('type') == 'assistant':
                u = m.get('usage')
                # One line per block (reasoning, text, tool) of the same response, all repeating its `usage`:
                # count once per message id.
                key = m.get('id') or d.get('requestId') or d.get('uuid')
                if u and key in seen:
                    outputs[seen[key]] = max(outputs[seen[key]], u.get('output_tokens') or 0)
                elif u:
                    seen[key] = len(outputs)
                    api_calls += 1
                    for k in ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'):
                        usage[k] += u.get(k) or 0
                    contexts.append(sum(u.get(k) or 0 for k in
                                        ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')))
                    outputs.append(u.get('output_tokens') or 0)
                    call_models.append(m['model'] if not (m.get('model') or '<').startswith('<') else None)
                for b in m.get('content') or []:
                    if isinstance(b, dict) and b.get('type') == 'tool_use':
                        entry = b.get('input') or {}
                        tool_uses[b['id']] = (b.get('name', '?'), input_summary(entry), json.dumps(entry, sort_keys=True))
                        tool_files[b['id']] = files_read(b.get('name'), entry, root)
            elif d.get('type') == 'user':
                for b in m.get('content') or [] if isinstance(m.get('content'), list) else []:
                    if isinstance(b, dict) and b.get('type') == 'tool_result':
                        t, img = tokens_of(b.get('content'))
                        results.append((api_calls, b.get('tool_use_id'), t, img, bool(b.get('is_error'))))

    if api_calls == 0:
        sys.exit('No calls in that period (try --hours 0)')
    usage['output_tokens'] = sum(outputs)
    for model, ctx, out in zip(call_models, contexts, outputs):
        if model:
            p = per_model[('main', model)]
            p[0] += 1
            p[1] += ctx
            p[2] += out

    def drag(idx):
        # Later calls until the next compaction: each one reads the result again.
        end = next((c for c in cuts if c > idx), api_calls)
        return max(end - idx, 1)

    per_tool = collections.defaultdict(lambda: [0, 0.0, 0.0, 0, 0])  # calls, tokens, dragged, images, errors
    rows = []
    repeated = collections.Counter()
    per_file = collections.defaultdict(lambda: [0, 0.0, 0.0])  # reads, tokens, dragged
    for idx, tid, t, img, err in results:
        read = tool_files.get(tid) or []
        for r in read:  # a command that reads several files splits its result among them
            q = per_file[r]
            q[0] += 1
            q[1] += t / len(read)
            q[2] += t * drag(idx) / len(read)
        name, summary, full = tool_uses.get(tid, ('?', '', ''))
        dragged = t * drag(idx)
        p = per_tool[name]
        p[0] += 1
        p[1] += t
        p[2] += dragged
        p[3] += img
        p[4] += err
        rows.append((dragged, t, name, summary, img, err))
        if name in ('Read', 'Bash', 'Grep', 'Glob', 'WebFetch'):
            repeated[(name, full, summary)] += 1

    total_in = usage['input_tokens'] + usage['cache_creation_input_tokens'] + usage['cache_read_input_tokens']
    period = ('whole session' if not since else f'since {since:%Y-%m-%d %H:%M} UTC' if a.since
              else f'last {a.hours:g} h')
    print(f'Session: {os.path.basename(path)}  |  period: {period}')
    print(f'API calls: {api_calls}  |  compactions: {len(cuts)}')
    print(f'Input {total_in:,.0f} tokens (cache read {usage["cache_read_input_tokens"]:,.0f} = '
          f'{100 * usage["cache_read_input_tokens"] / max(total_in, 1):.0f} %, written '
          f'{usage["cache_creation_input_tokens"]:,.0f}, uncached {usage["input_tokens"]:,.0f})  |  '
          f'output {usage["output_tokens"]:,.0f}')
    print(f'Average context per call: {total_in / api_calls:,.0f} tokens  ->  every extra call costs that '
          f'(at cache price, ~{total_in / api_calls / 10:,.0f} tokens of normal input)')
    print(f'Average output per call: {usage["output_tokens"] / api_calls:,.0f} tokens (includes reasoning)')
    # Curve between compactions: the floor is the fixed context (instructions, tools, summary) and the ceiling is
    # how far it grows before compacting. A ceiling far above the floor says compaction comes too late.
    stretches, closed, start = [], [], 0  # closed: the stretch ended in a compaction (it peaked where compaction fires)
    for c in cuts + [api_calls]:
        if c > start:
            stretches.append(contexts[start:c])
            closed.append(c in cuts)
        start = c
    # With a clipped period the first stretch starts midway (no compaction opened it): its first call is no floor.
    partial = clipped and (not cuts or cuts[0] > 0) and len(stretches) > 1
    if partial:
        stretches, closed = stretches[1:], closed[1:]
    if stretches:
        floors = [s[0] for s in stretches]
        ceilings = [max(s) for s in stretches]
        print(f'Stretches between compactions: {len(stretches)}  |  average floor {sum(floors) / len(floors):,.0f}  |  '
              f'average ceiling {sum(ceilings) / len(ceilings):,.0f}  |  '
              f'{sum(map(len, stretches)) / len(stretches):,.0f} calls per stretch'
              + ('  (without the first, which began before the period)' if partial else ''))
        # The overall average mixes stretches with different compaction ceilings (if the limit changed in the period
        # it will not match the ceiling). Each stretch on its own, the last 8, shows the current regime.
        print('Per stretch, oldest to latest (average/ceiling, thousands): ' + '  '.join(
            f'{sum(s) / len(s) / 1000:,.0f}/{max(s) / 1000:,.0f}' for s in stretches[-8:]))
        # Stretches that ended in a compaction peak where the window fires. Peaks far apart mean the window changed
        # (or a compaction was manual) inside the period: every average above mixes regimes.
        peaks = [max(s) for s, c in zip(stretches, closed) if c]
        if len(peaks) > 1 and max(peaks) > MIXED_RATIO * min(peaks):
            print(f'WARNING: this session mixes compaction windows (stretches ended in a compaction at '
                  f'{min(peaks) / 1000:,.0f}k to {max(peaks) / 1000:,.0f}k): the averages above mix regimes; '
                  f'measure the current one with --since <date or commit of the change>')
        if partial:
            rest = [c for s in stretches for c in s]
            print(f'Average context without the first stretch: {sum(rest) / len(rest):,.0f} tokens')
    print()
    print('BY TOOL (tokens put into the context | dragged along on later calls)')
    for name, (n, t, dragged, img, err) in sorted(per_tool.items(), key=lambda x: -x[1][2])[: a.top]:
        extra = (f' | {img} images' if img else '') + (f' | {err} errors' if err else '')
        print(f'  {name:<28} {n:>5} calls  {t:>9,.0f} tok  {dragged:>13,.0f} dragged{extra}')
    print()
    print('HEAVIEST RESULTS (dragged)')
    for dragged, t, name, summary, img, err in sorted(rows, reverse=True)[: a.top]:
        print(f'  {dragged:>12,.0f}  ({t:>7,.0f} tok) {name}: {summary}{" [image]" if img else ""}{" [error]" if err else ""}')
    if per_file:
        print()
        print('BY FILE (reads with Read or Bash | tokens | dragged; a command with several files splits its result)')
        for r, (n, t, dragged) in sorted(per_file.items(), key=lambda x: -x[1][2])[: a.top]:
            print(f'  {r[-60:]:<60} {n:>4}x  {t:>9,.0f} tok  {dragged:>13,.0f} dragged')
    rep = [(n, k) for k, n in repeated.items() if n > 1]
    if rep:
        print()
        print('REPEATED (the same read or command, identical, more than once)')
        for n, (name, _, summary) in sorted(rep, reverse=True)[: a.top]:
            print(f'  {n:>3}x {name}: {summary}')
    # Which model did what. Mechanical work (code with a closed plan, searching, manual batches) can go to a
    # subagent with a cheaper model; design and review to the large one.
    kinds = collections.Counter()
    subs = []  # (description, type, model, responses)
    for sub in sorted(glob.glob(os.path.join(os.path.splitext(path)[0], 'subagents', '*.jsonl'))):
        try:
            with open(sub[:-len('.jsonl')] + '.meta.json', encoding='utf-8') as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            meta = {}
        kind = meta.get('agentType') or '?'
        resp = add_model_usage(sub, since, per_model, 'subagents')
        if resp:
            model = resp[-1][0]
            kinds[(kind, model)] += 1
            subs.append((meta.get('description') or os.path.basename(sub)[:-len('.jsonl')], kind, model, resp))
    # One row per subagent, with its average context (what each of its calls costs) and its output. The totals above
    # are the main session only; here come the subagents' and the sum of everything. "startup" is the context of
    # its first call: the fixed price each subagent pays before doing anything.
    if subs:
        print()
        print('BY SUBAGENT (one row per log in <session>/subagents/)')
        # Some subagent logs only keep the `usage` of a half-written block: below MIN_OUTPUT per call the output is
        # not believed and shows as "-".
        no_output = False
        for desc, kind, model, resp in sorted(subs, key=lambda x: -sum(r[1] for r in x[3]))[: a.top]:
            ent = sum(r[1] for r in resp)
            out = sum(r[2] for r in resp)
            out_txt = f'{out:>9,}' if out >= MIN_OUTPUT * len(resp) else f'{"-":>9}'
            no_output |= out < MIN_OUTPUT * len(resp)
            print(f'  {desc[:34]:<34} {kind[:15]:<15} {model:<20} {len(resp):>4} calls  {ent / len(resp):>8,.0f} avg ctx  '
                  f'{resp[0][1]:>7,} startup  {ent:>12,} input  {out_txt} output')
        if no_output:
            print(f'  "-": the subagent log does not keep its final output (under {MIN_OUTPUT} per call); '
                  f'the output in the totals falls short')
        if len(subs) > a.top:
            print(f'  ... and {len(subs) - a.top} more (--top {len(subs)})')
        n_sub = sum(len(x[3]) for x in subs)
        in_sub = sum(r[1] for x in subs for r in x[3])
        out_sub = sum(r[2] for x in subs for r in x[3])
        print(f'  Subagents in total: {len(subs)} logs | {n_sub:,} calls | {in_sub:,} input | {out_sub:,} output')
        print(f'  Average startup: {sum(x[3][0][1] for x in subs) / len(subs):,.0f} tokens (what each subagent pays before '
              f'doing anything: a fix of a few calls that the main session already has in context is cheaper there)')
        print(f'  Session + subagents: {api_calls + n_sub:,} calls | {total_in + in_sub:,} input | '
              f'{usage["output_tokens"] + out_sub:,} output')
    print()
    print('BY MODEL (API input and output)')
    for (who, model), (n, ent, out) in sorted(per_model.items(), key=lambda x: (x[0][0] != 'main', -x[1][1])):
        print(f'  {who:<10} {model:<28} {n:>5} calls  {ent:>13,} input  {out:>10,} output')
    if kinds:
        print('  Subagents: ' + ' | '.join(f'{n} {t} ({m})' for (t, m), n in kinds.most_common()))


if __name__ == '__main__':
    main()
