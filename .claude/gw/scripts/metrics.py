#!/usr/bin/env python3
# galivelop-workflow v0.6.0
"""Token ledger (B1/B2): `metrics.py record` appends the tokens the Claude Code transcripts show to a ledger in the repo.

Run as a `Stop` hook (hook JSON on stdin: `session_id`, `transcript_path`, `stop_hook_active`) or by hand
(`--transcript PATH`, `--root R`). Sources: the session transcript `<dir>/<session>.jsonl` and its subagents'
`<dir>/<session>/subagents/agent-*.jsonl` with their `agent-*.meta.json` (only `agentType` is kept: a description can hold
private text). Assistant entries carry `message.usage`; one API response is split over several lines that share
`message.id` (else `requestId`, else `uuid`), so each response counts once, with the maximum of each usage field among
its lines. Synthetic models (`<synthetic>`) are skipped.

Totals are keyed by (session, agent, model, date): date is the UTC date of the entry's `timestamp`; agent is `main` for
the session transcript, else the subagent's `agentType` (`?` without one). The ledger is JSON lines, sorted keys:

  {"agent", "branch", "cacheRead", "cacheWrite", "date", "input", "model", "output", "recorded", "refs", "session"}

`session` is the first 8 characters of the session id; `branch` is the current git branch; `refs` the task ids of the
`Refs:` trailer of HEAD's commit message; `recorded` the UTC time of the write. Tokens only, never money.

Idempotent without a cursor file: the tokens already in the ledger are summed per key and one line is appended per key
whose transcript total exceeds that sum (per field, the difference). Rerunning without new usage writes nothing; a key
whose ledger sum is above the transcript (a rotated transcript) is left alone. The write is one append of all new lines.

Configuration (`metrics` in .claude/gw.json): `ledger` (repo-relative path, its folder is created), `record` (false
writes nothing), `reports` (B4, the folder of the written reports) and `prices` (B3): dated tables of USD per million tokens per model. Money is computed when reading
(`price_of`, `cost_of`; `metrics.py price MODEL [--date D]` prints the price a row of that model and date takes): the
newest table whose `since` is on or before the row's date, then the model key equal to the row's model or, failing
that, the longest key the model starts with followed by `-` (a date suffix). No table or no key = no price (None),
never a guess.

`metrics.py report --period day|week|month|quarter [--date D] [--write]` (B4) sums the ledger rows of the period that
holds D (default today, UTC; weeks are ISO, Monday to Sunday) into a Markdown report: totals, then tokens and USD by
model, agent, branch and task id (`refs`; a row with two ids counts in both, so that table can add up to more than the
total; `(none)` without ids). Rows without a price are counted in tokens and listed apart, never priced. It prints the
report; `--write` also saves it as `<reports>/<daily|weekly|monthly|quarterly>/<name>.md` (`2026-11-09`, `2026-W45`,
`2026-11`, `2026-Q4`), the same bytes for the same ledger. A period without rows writes nothing and says so (exit 0).

`metrics.py compare --period day|week|month|quarter [--date D] [--against D2]` (B5) sets the period that holds D
beside the one before it, or beside the period of the same kind that holds D2: totals and, by model, agent, branch and
task id, the tokens and USD of each and the change (`+n (+x%)`; `new` when the earlier side had none). The USD change
is left out (`n/a`) when either side has unpriced tokens. It only prints; both periods empty says so (exit 0); the same
period twice is an error (exit 2).

`metrics.py quality --period day|week|month|quarter [--date D] [--write]` (B8) sets quality signals beside the spend of
each task id. Spend comes from the period's ledger rows; the signals only from the messages of the commits in the
history from HEAD (no merges) whose committer date (UTC) falls in the period and that have a `Refs:` trailer (the others
are ignored). Per id: `commits`; `red` (subject starts with the `commitWipPrefix`, `WIP:` by default: the check was red); `rework` (commits whose
Conventional Commits type, after a `WIP: ` prefix, is in `metrics.quality.reworkTypes`, and git reverts `Revert "..."`,
not counting the first commit of the id in the whole history); `findings` and `retries` (the sums of the integer values
of the trailers `metrics.quality.findingsTrailer` and `retriesTrailer`, matched case-insensitively; a value that is not a
non-negative integer is ignored and listed under "Ignored trailers"). A second table gives the same by model: the signals
of the ids each model spent on (an id counts for every model that spent on it). It prints the report; `--write` saves it
as `<reports>/<daily|weekly|monthly|quarterly>/<name>-quality.md`. Nothing in the period (no commits with `Refs:` and no
ledger rows) says so on stderr and writes nothing (exit 0); no git repository or a git failure, or a bad config, exit 2.

`metrics.py alert [--date D]` (B6, run by the SessionStart hook) checks D (default today, UTC) and the day before: for
each model, that day's spend against its mean daily spend over the `metrics.alert.days` days before it, counting only
the days with rows of that model, and only when there are at least `minDays` of them. Spend is USD when every row of
the model in that span has a price, else tokens. Above `factor` x the mean it prints one line per model and day, with
the command that shows where it went; nothing to say prints nothing. `factor` 0 turns it off. Always exits 0 except on
a bad config (exit 2).

The record hook never blocks a stop and never fails silently: on any error it exits 0 and prints a `systemMessage` JSON object on
stdout that names `python3 <here>/doctor.py`. A successful record prints nothing; with `stop_hook_active` it records
the same and prints nothing at all. Project root: config.find_root (never the current directory alone).
Python 3.8+ standard library only.
"""
import argparse
import datetime
import glob
import json
import os
import posixpath
import re
import select
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, HERE)
import config  # noqa: E402
import session_log  # noqa: E402

GIT_TIMEOUT = 30  # seconds per git call; the quality report takes `metrics.gitTimeout` instead (same default)
FIELDS = (("input", "input_tokens"), ("cacheWrite", "cache_creation_input_tokens"),
          ("cacheRead", "cache_read_input_tokens"), ("output", "output_tokens"))
TOKEN_KEYS = tuple(k for k, _ in FIELDS)


class MetricsError(Exception):
    pass


def read_event():
    """The hook's JSON object from stdin, or {} when there is none (a terminal, nothing arriving, not an object)."""
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        ready, _, _ = select.select([sys.stdin], [], [], config.hook_stdin_wait())
        if not ready:
            return {}
        data = json.loads(sys.stdin.read())
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def num(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def day_of(stamp):
    """UTC date (YYYY-MM-DD) of an ISO timestamp, or None when it cannot be read."""
    if not isinstance(stamp, str):
        return None
    try:
        when = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is not None:
        when = when.astimezone(datetime.timezone.utc)
    return when.date().isoformat()


def responses_of(path):
    """{response id: (model, date, {field: tokens})} of a transcript, each response once (max per field over its lines).
    Raises OSError when the file cannot be read."""
    by_id = {}
    with open(path, encoding="utf-8", errors="replace") as log:
        for line in log:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            m = d.get("message") if isinstance(d, dict) else None
            if not isinstance(m, dict) or d.get("type") != "assistant" or not isinstance(m.get("usage"), dict):
                continue
            model = m.get("model") or "?"
            if model.startswith("<"):
                continue
            key = m.get("id") or d.get("requestId") or d.get("uuid") or f"line{len(by_id)}"
            usage = {k: num(m["usage"].get(src)) for k, src in FIELDS}
            day = day_of(d.get("timestamp"))
            before = by_id.get(key)
            if before:
                usage = {k: max(v, before[2][k]) for k, v in usage.items()}
                day = before[1] or day  # a response belongs to the day of its first line
            by_id[key] = (model, day, usage)
    return by_id


def totals(transcript):
    """{(session, agent, model, date): {field: tokens}} of the main transcript and its subagents'.
    Raises OSError when the main transcript cannot be read; an unreadable subagent log is skipped."""
    session = os.path.basename(transcript)[:-len(".jsonl")]
    out = {}
    sources = [("main", transcript)]
    for sub in sorted(glob.glob(os.path.join(glob.escape(os.path.splitext(transcript)[0]), "subagents", "agent-*.jsonl"))):
        try:
            with open(sub[:-len(".jsonl")] + ".meta.json", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {}
        kind = meta.get("agentType") if isinstance(meta, dict) else None
        sources.append((kind if isinstance(kind, str) and kind else "?", sub))
    for agent, path in sources:
        try:
            responses = responses_of(path)
        except OSError:
            if agent == "main":
                raise
            continue
        for model, day, usage in responses.values():
            if not day:
                continue
            acc = out.setdefault((session[:8], agent, model, day), dict.fromkeys(TOKEN_KEYS, 0))
            for k in TOKEN_KEYS:
                acc[k] += usage[k]
    return out


def ledger_sums(path):
    """{(session, agent, model, date): {field: tokens}} already in the ledger (lines that do not parse are skipped)."""
    sums = {}
    if not os.path.isfile(path):
        return sums
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
                key = (d["session"], d["agent"], d["model"], d["date"])
            except (ValueError, KeyError, TypeError):
                continue
            acc = sums.setdefault(key, dict.fromkeys(TOKEN_KEYS, 0))
            for k in TOKEN_KEYS:
                acc[k] += num(d.get(k))
    return sums


def price_of(prices, model, day):
    """The price entry ({input, cacheWrite, cacheRead, output} in USD per million tokens, plus `since` and `key`) a
    ledger row of this model and UTC date (YYYY-MM-DD) takes, or None when no table or no model key applies."""
    tables = [t for t in prices if isinstance(t, dict) and isinstance(t.get("since"), str) and t["since"] <= day]
    if not tables or not isinstance(model, str):
        return None
    table = max(tables, key=lambda t: t["since"])  # ISO dates sort as text; a later duplicate `since` loses
    models = table.get("models") if isinstance(table.get("models"), dict) else {}
    key = model if model in models else max((k for k in models if model.startswith(k + "-")), key=len, default=None)
    if key is None:
        return None
    return dict(models[key], since=table["since"], key=key)


def cost_of(row, prices):
    """USD cost of one ledger row with the dated price table, or None when the row has no price."""
    price = price_of(prices, row.get("model"), str(row.get("date", "")))
    if price is None:
        return None
    return sum(num(row.get(k)) * price[k] for k in TOKEN_KEYS) / 1_000_000


PERIODS = {"day": "daily", "week": "weekly", "month": "monthly", "quarter": "quarterly"}


def period_of(kind, day):
    """(name, first day, last day) of the period of `kind` that holds `day` (a datetime.date); days as ISO text."""
    if kind == "day":
        first = last = day
        name = day.isoformat()
    elif kind == "week":
        first = day - datetime.timedelta(days=day.weekday())
        last = first + datetime.timedelta(days=6)
        year, week, _ = day.isocalendar()
        name = f"{year}-W{week:02d}"
    elif kind == "month":
        first = day.replace(day=1)
        last = (first + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
        name = f"{day.year}-{day.month:02d}"
    elif kind == "quarter":
        q = (day.month - 1) // 3
        first = datetime.date(day.year, 3 * q + 1, 1)
        last = (first + datetime.timedelta(days=95)).replace(day=1) - datetime.timedelta(days=1)
        name = f"{day.year}-Q{q + 1}"
    else:
        raise ValueError(f"unknown period {kind!r}")
    return name, first.isoformat(), last.isoformat()


def ledger_rows(path):
    """The ledger's rows (dicts with session, agent, model and date), skipping lines that do not parse."""
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict) and all(isinstance(d.get(k), str) for k in ("session", "agent", "model", "date")):
                rows.append(d)
    return rows


def summarize(rows, prices):
    """Totals and breakdowns of ledger rows: {"total", "sessions", "unpriced": {model: tokens}, "by": {dimension:
    {value: acc}}}; acc = {field: tokens, "tokens": sum, "usd": priced cost, "unpriced": tokens without price}."""
    def new():
        return dict(dict.fromkeys(TOKEN_KEYS, 0), tokens=0, usd=0.0, unpriced=0)

    def add(acc, row, tokens, usd):
        for k in TOKEN_KEYS:
            acc[k] += num(row.get(k))
        acc["tokens"] += tokens
        if usd is None:
            acc["unpriced"] += tokens
        else:
            acc["usd"] += usd

    out = {"total": new(), "sessions": set(), "unpriced": {}, "by": {d: {} for d in ("model", "agent", "branch", "refs")}}
    for row in rows:
        tokens = sum(num(row.get(k)) for k in TOKEN_KEYS)
        usd = cost_of(row, prices)
        add(out["total"], row, tokens, usd)
        out["sessions"].add(row["session"])
        if usd is None:
            out["unpriced"][row["model"]] = out["unpriced"].get(row["model"], 0) + tokens
        refs = row.get("refs") if isinstance(row.get("refs"), list) else []
        values = {"model": [row["model"]], "agent": [row["agent"]],
                  "branch": [row.get("branch") if isinstance(row.get("branch"), str) else "?"],
                  "refs": sorted({r for r in refs if isinstance(r, str)}) or ["(none)"]}
        for dim, keys in values.items():
            for key in keys:
                add(out["by"][dim].setdefault(key, new()), row, tokens, usd)
    return out


def fmt_tokens(n):
    return f"{n:,}"


def fmt_usd(acc):
    text = f"${acc['usd']:,.2f}"
    return text + " + unpriced" if acc["unpriced"] else text


def render_report(kind, name, first, last, summary):
    """The Markdown report of a period summary (deterministic: same rows, same text)."""
    t = summary["total"]
    span = first if first == last else f"{first} to {last}"
    lines = [f"# Token report: {name}", "",
             f"Period: {kind}, {span} (UTC). Source: the token ledger (`metrics.py report`). Money is computed from "
             "`metrics.prices` when the report is made; with a subscription it is a reference, not a bill.", "",
             "## Totals", "",
             "| Sessions | Input | Cache write | Cache read | Output | Tokens | USD |",
             "|---:|---:|---:|---:|---:|---:|---:|",
             f"| {len(summary['sessions'])} | {fmt_tokens(t['input'])} | {fmt_tokens(t['cacheWrite'])} | "
             f"{fmt_tokens(t['cacheRead'])} | {fmt_tokens(t['output'])} | {fmt_tokens(t['tokens'])} | {fmt_usd(t)} |"]
    titles = (("model", "By model", "Model"), ("agent", "By agent", "Agent"), ("branch", "By branch", "Branch"),
              ("refs", "By task id (`Refs`)", "Id"))
    for dim, title, head in titles:
        lines += ["", f"## {title}", ""]
        if dim == "refs":
            lines += ["A row with several ids counts once in each, so this table can add up to more than the total.", ""]
        lines += [f"| {head} | Input | Cache write | Cache read | Output | Tokens | Share | USD |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|"]
        ordered = sorted(summary["by"][dim].items(), key=lambda kv: (-kv[1]["tokens"], kv[0]))
        for key, acc in ordered:
            share = 100.0 * acc["tokens"] / t["tokens"] if t["tokens"] else 0.0
            lines.append(f"| `{key}` | {fmt_tokens(acc['input'])} | {fmt_tokens(acc['cacheWrite'])} | "
                         f"{fmt_tokens(acc['cacheRead'])} | {fmt_tokens(acc['output'])} | {fmt_tokens(acc['tokens'])} | "
                         f"{share:.1f}% | {fmt_usd(acc)} |")
    if summary["unpriced"]:
        lines += ["", "## Without a price", "",
                  "These models have no entry in `metrics.prices` for their date; their tokens are in the tables "
                  "above but not in the USD figures (`metrics.py price MODEL --date D` checks one).", ""]
        lines += [f"- `{m}`: {fmt_tokens(n)} tokens" for m, n in sorted(summary["unpriced"].items())]
    return "\n".join(lines) + "\n"


def period_rows(root, settings, first, last):
    ledger = os.path.join(str(root), *posixpath.normpath(settings["ledger"]).split("/"))
    return [r for r in ledger_rows(ledger) if first <= r["date"] <= last]


def report(root, cfg, kind, day, write=False):
    """(text, path written or None) of the report of the `kind` period that holds `day`; text is None without rows."""
    settings = config.metrics(cfg)
    name, first, last = period_of(kind, day)
    rows = period_rows(root, settings, first, last)
    if not rows:
        return None, None
    text = render_report(kind, name, first, last, summarize(rows, settings["prices"]))
    path = None
    if write:
        path = os.path.join(str(root), *posixpath.normpath(settings["reports"]).split("/"), PERIODS[kind], name + ".md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return text, path


def fmt_change(old, new, money=False):
    """`+n (+x%)` from old to new; `new` when old is 0 and new is not, `=` when both are equal."""
    diff = new - old
    if (abs(diff) < 0.005) if money else diff == 0:
        return "="
    if not old:
        return "new"
    text = f"{'+' if diff > 0 else '-'}${abs(diff):,.2f}" if money else f"{diff:+,}"
    return f"{text} ({100.0 * diff / old:+.1f}%)"


def usd_change(a, b):
    return "n/a" if a["unpriced"] or b["unpriced"] else fmt_change(a["usd"], b["usd"], money=True)


def render_compare(kind, base, current):
    """Markdown of two period summaries side by side; base and current are (name, first, last, summary)."""
    (bn, bf, bl, bs), (cn, cf, cl, cs) = base, current

    def span(first, last):
        return first if first == last else f"{first} to {last}"

    bt, ct = bs["total"], cs["total"]
    lines = [f"# Token comparison: {cn} against {bn}", "",
             f"Period: {kind}. `{bn}` is {span(bf, bl)}, `{cn}` is {span(cf, cl)} (UTC). Source: the token ledger "
             "(`metrics.py compare`). Changes go from the first column to the second; money is computed from "
             "`metrics.prices` when the comparison is made.", "",
             "## Totals", "",
             f"| | `{bn}` | `{cn}` | Change |", "|---|---:|---:|---:|",
             f"| Sessions | {len(bs['sessions'])} | {len(cs['sessions'])} | "
             f"{fmt_change(len(bs['sessions']), len(cs['sessions']))} |"]
    for key, label in (("input", "Input"), ("cacheWrite", "Cache write"), ("cacheRead", "Cache read"),
                       ("output", "Output"), ("tokens", "Tokens")):
        lines.append(f"| {label} | {fmt_tokens(bt[key])} | {fmt_tokens(ct[key])} | {fmt_change(bt[key], ct[key])} |")
    lines.append(f"| USD | {fmt_usd(bt)} | {fmt_usd(ct)} | {usd_change(bt, ct)} |")
    zero = dict(dict.fromkeys(TOKEN_KEYS, 0), tokens=0, usd=0.0, unpriced=0)
    titles = (("model", "By model", "Model"), ("agent", "By agent", "Agent"), ("branch", "By branch", "Branch"),
              ("refs", "By task id (`Refs`)", "Id"))
    for dim, title, head in titles:
        lines += ["", f"## {title}", ""]
        if dim == "refs":
            lines += ["A row with several ids counts once in each, so this table can add up to more than the total.", ""]
        lines += [f"| {head} | Tokens `{bn}` | Tokens `{cn}` | Change | USD `{bn}` | USD `{cn}` | USD change |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        keys = set(bs["by"][dim]) | set(cs["by"][dim])
        accs = {k: (bs["by"][dim].get(k, zero), cs["by"][dim].get(k, zero)) for k in keys}
        for key in sorted(keys, key=lambda k: (-accs[k][1]["tokens"], -accs[k][0]["tokens"], k)):
            a, b = accs[key]
            lines.append(f"| `{key}` | {fmt_tokens(a['tokens'])} | {fmt_tokens(b['tokens'])} | "
                         f"{fmt_change(a['tokens'], b['tokens'])} | {fmt_usd(a)} | {fmt_usd(b)} | {usd_change(a, b)} |")
    unpriced = sorted(set(bs["unpriced"]) | set(cs["unpriced"]))
    if unpriced:
        lines += ["", "## Without a price", "",
                  "These models have no entry in `metrics.prices` for their date; their tokens are in the tables "
                  "above but not in the USD figures, and the USD change is `n/a` where they appear.", ""]
        lines += [f"- `{m}`: {fmt_tokens(bs['unpriced'].get(m, 0))} tokens in `{bn}`, "
                  f"{fmt_tokens(cs['unpriced'].get(m, 0))} in `{cn}`" for m in unpriced]
    return "\n".join(lines) + "\n"


def compare(root, cfg, kind, day, against=None):
    """Markdown comparing the `kind` period that holds `day` with the one before it, or with the one holding
    `against` (a datetime.date); None when both are empty. Raises ValueError when both dates fall in the same period."""
    settings = config.metrics(cfg)
    current = period_of(kind, day)
    if against is None:
        base = period_of(kind, datetime.date.fromisoformat(current[1]) - datetime.timedelta(days=1))
    else:
        base = period_of(kind, against)
        if base == current:
            raise ValueError(f"{day.isoformat()} and {against.isoformat()} are in the same {kind} ({current[0]})")
    sides = []
    for name, first, last in (base, current):
        sides.append((name, first, last, period_rows(root, settings, first, last)))
    if not sides[0][3] and not sides[1][3]:
        return None
    prices = settings["prices"]
    return render_compare(kind, *[(n, f, l, summarize(rows, prices)) for n, f, l, rows in sides])


def alerts(root, cfg, today):
    """Lines warning about each model whose spend on `today` or the day before (datetime.date) passes
    metrics.alert.factor times its mean over the metrics.alert.days days before that day (days with data only, at
    least metrics.alert.minDays of them)."""
    settings = config.metrics(cfg)
    alert = settings["alert"]
    if not alert["factor"]:
        return []
    days = alert["days"]
    first = (today - datetime.timedelta(days=days + 1)).isoformat()
    rows = period_rows(root, settings, first, today.isoformat())
    prices = settings["prices"]
    out = []
    for day in (today - datetime.timedelta(days=1), today):
        start = (day - datetime.timedelta(days=days)).isoformat()
        span = [r for r in rows if start <= r["date"] <= day.isoformat()]
        for model in sorted({r["model"] for r in span if r["date"] == day.isoformat()}):
            own = [r for r in span if r["model"] == model]
            costs = [cost_of(r, prices) for r in own]
            money = all(c is not None for c in costs)
            per_day = {}
            for r, c in zip(own, costs):
                value = c if money else sum(num(r.get(k)) for k in TOKEN_KEYS)
                per_day[r["date"]] = per_day.get(r["date"], 0) + value
            spent = per_day.pop(day.isoformat())
            if len(per_day) < alert["minDays"]:
                continue
            mean = sum(per_day.values()) / len(per_day)
            if mean <= 0 or spent <= alert["factor"] * mean:
                continue
            fmt = (lambda v: f"${v:,.2f}") if money else (lambda v: f"{int(round(v)):,} tokens")
            out.append(f"{model} spent {fmt(spent)} on {day.isoformat()}, {spent / mean:.1f}x its daily mean of "
                       f"{fmt(mean)} over the {days} days before ({len(per_day)} with data; alert at "
                       f"{alert['factor']:g}x, metrics.alert in .claude/gw.json); see where it went: python3 "
                       f"{os.path.join(HERE, 'metrics.py')} report --period day --date {day.isoformat()}")
    return out


def git(root, *args):
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        raise MetricsError(f"git {args[0]} could not run ({exc})")
    if r.returncode != 0:
        raise MetricsError(f"git {' '.join(args)} failed: {(r.stderr or r.stdout).strip() or 'exit ' + str(r.returncode)}")
    return r.stdout


def trailers_of(root, message):
    """The trailers of a commit message as a list of (key, value) pairs, in order (`git interpret-trailers --parse`)."""
    try:
        r = subprocess.run(["git", "-C", str(root), "interpret-trailers", "--parse", "--no-divider"], input=message,
                           capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        raise MetricsError(f"git interpret-trailers could not run ({exc})")
    if r.returncode != 0:
        raise MetricsError(f"git interpret-trailers failed ({r.stderr.strip()}); check git with: git --version")
    out = []
    for line in r.stdout.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            out.append((key.strip(), value.strip()))
    return out


def refs_of(trailers):
    """The task ids of the `Refs:` trailers (comma-separated, may repeat), in order."""
    refs = []
    for key, value in trailers:
        if key.lower() == "refs":
            refs.extend(t.strip() for t in value.split(",") if t.strip())
    return refs


def head_refs(root):
    """The ids of the `Refs:` trailers of HEAD's commit message (a list, empty when there is none or no commit)."""
    try:
        message = git(root, "log", "-1", "--format=%B")
    except MetricsError:
        return []  # no commit yet
    return refs_of(trailers_of(root, message))


TYPE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9-]*)(\([^)]*\))?!?:")
COUNT_RE = re.compile(r"^[0-9]+$")


def history_commits(root):
    """The commits of the history from HEAD, newest first, without merges: [{"sha", "day" (UTC date text), "subject",
    "trailers"}] for those with a `Refs:` trailer ("refs" holds their ids). No commits yet gives []."""
    git(root, "rev-parse", "--git-dir")  # raises MetricsError outside a repository
    try:
        git(root, "rev-parse", "--verify", "-q", "HEAD")
    except MetricsError:
        return []
    out = git(root, "log", "--no-merges", "--format=%H%x1f%ct%x1f%B%x00")
    commits = []
    for record_text in out.split("\x00"):
        record_text = record_text.strip("\n")
        if not record_text:
            continue
        sha, _, rest = record_text.partition("\x1f")
        stamp, _, message = rest.partition("\x1f")
        if "refs" not in message.lower():
            continue  # cheap filter before running git interpret-trailers
        try:
            day = datetime.datetime.fromtimestamp(int(stamp), datetime.timezone.utc).date().isoformat()
        except (ValueError, OverflowError, OSError):
            continue
        trailers = trailers_of(root, message)
        refs = refs_of(trailers)
        if refs:
            commits.append({"sha": sha, "day": day, "subject": message.strip().split("\n", 1)[0].strip(),
                            "trailers": trailers, "refs": refs})
    return commits


def is_red(subject, wip="WIP: "):
    """Whether a subject starts with the prefix of a commit made in red (`commitWipPrefix`; "" = none), compared
    without its trailing space (`WIP:`)."""
    mark = wip.rstrip()
    return bool(mark) and subject.startswith(mark)


def commit_type(subject, wip="WIP: "):
    """The Conventional Commits type of a subject (lower case, after the `commitWipPrefix`), or None."""
    if is_red(subject, wip):
        subject = subject[len(wip.rstrip()):].lstrip()
    m = TYPE_RE.match(subject)
    return m.group(1).lower() if m else None


def commit_signals(commits, first, last, quality, wip="WIP: "):
    """({id: {"commits", "red", "rework", "findings", "retries"}}, [(sha7, "Key: value") of ignored trailers]) of the
    commits (newest first, all the history) whose day is in first..last. The first commit of an id is the oldest of
    the whole list that names it; it is never rework."""
    oldest = {}
    for c in commits:  # newest first: the last write is the oldest commit
        for ref in c["refs"]:
            oldest[ref] = c["sha"]
    rework_types = {t.lower() for t in quality["reworkTypes"]}
    names = {"findings": quality["findingsTrailer"].lower(), "retries": quality["retriesTrailer"].lower()}
    signals, ignored = {}, []
    for c in commits:
        if not first <= c["day"] <= last:
            continue
        subject = c["subject"]
        red = is_red(subject, wip)
        is_rework = commit_type(subject, wip) in rework_types or subject.startswith('Revert "')
        sums = dict.fromkeys(names, 0)
        for key, value in c["trailers"]:
            for field, name in names.items():
                if key.lower() != name:
                    continue
                if COUNT_RE.match(value):
                    sums[field] += int(value)
                else:
                    ignored.append((c["sha"][:7], f"{key}: {value}"))
        for ref in sorted(set(c["refs"])):
            acc = signals.setdefault(ref, dict.fromkeys(("commits", "red", "rework", "findings", "retries"), 0))
            acc["commits"] += 1
            acc["red"] += 1 if red else 0
            acc["rework"] += 1 if is_rework and oldest[ref] != c["sha"] else 0
            acc["findings"] += sums["findings"]
            acc["retries"] += sums["retries"]
    return signals, sorted(set(ignored))


SIGNAL_KEYS = ("commits", "red", "rework", "findings", "retries")


def render_quality(kind, name, first, last, spend, signals, model_rows, ignored):
    """The Markdown quality report. `spend` is summarize()'s output, `signals` commit_signals()'s, `model_rows` the
    ledger rows (for the ids each model spent on)."""
    span = first if first == last else f"{first} to {last}"
    zero = dict.fromkeys(SIGNAL_KEYS, 0)
    ids = sorted(set(signals) | set(spend["by"]["refs"]) - {"(none)"})
    empty = dict(tokens=0, usd=0.0, unpriced=0)
    lines = [f"# Quality report: {name}", "",
             f"Period: {kind}, {span} (UTC). Sources: the git history from HEAD (commits with a `Refs:` trailer, by "
             "committer date) and the token ledger (`metrics.py quality`). The signals come only from commit messages: "
             "red = subject starts with `WIP:`; rework = commits of a type in `metrics.quality.reworkTypes` and git "
             "reverts, not counting the first commit of the id; findings and retries = the sums of the trailers "
             "`metrics.quality.findingsTrailer` and `retriesTrailer`. Few commits are a weak signal.", "",
             "The deterministic model table (B8, later) waits for four weeks of ledger.", "",
             "## By task id", "",
             "| Id | Tokens | USD | Commits | Red (WIP) | Rework | Findings | Retries |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    by_id = spend["by"]["refs"]
    for ref in sorted(ids, key=lambda r: (-by_id.get(r, empty)["tokens"], r)):
        acc, sig = by_id.get(ref, empty), signals.get(ref, zero)
        lines.append(f"| `{ref}` | {fmt_tokens(acc['tokens'])} | {fmt_usd(acc)} | " +
                     " | ".join(str(sig[k]) for k in SIGNAL_KEYS) + " |")
    model_ids = {}
    for row in model_rows:
        refs = row.get("refs") if isinstance(row.get("refs"), list) else []
        model_ids.setdefault(row["model"], set()).update(r for r in refs if isinstance(r, str))
    lines += ["", "## By model", "",
              "The signals are those of the ids each model spent on; an id counts for every model that spent on it, so "
              "this table does not add up to the one above.", "",
              "| Model | Tokens | USD | Ids | Commits | Red (WIP) | Rework | Findings | Retries |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for model, acc in sorted(spend["by"]["model"].items(), key=lambda kv: (-kv[1]["tokens"], kv[0])):
        mids = model_ids.get(model, set())
        sums = [sum(signals.get(r, zero)[k] for r in mids) for k in SIGNAL_KEYS]
        lines.append(f"| `{model}` | {fmt_tokens(acc['tokens'])} | {fmt_usd(acc)} | {len(mids)} | " +
                     " | ".join(str(n) for n in sums) + " |")
    if ignored:
        lines += ["", "## Ignored trailers", "",
                  "These trailers are not a non-negative integer, so they were not counted; amend the commit message "
                  "or leave them.", ""]
        lines += [f"- `{sha}`: {text}" for sha, text in ignored]
    return "\n".join(lines) + "\n"


def quality_report(root, cfg, kind, day, write=False):
    """(text, path written or None) of the quality report of the `kind` period that holds `day`; text is None when
    the period has no commits with `Refs:` and no ledger rows."""
    settings = config.metrics(cfg)
    name, first, last = period_of(kind, day)
    rows = period_rows(root, settings, first, last)
    global GIT_TIMEOUT
    saved, GIT_TIMEOUT = GIT_TIMEOUT, settings["gitTimeout"]  # metrics.gitTimeout, for the git calls of this report
    try:
        commits = history_commits(root)
    finally:
        GIT_TIMEOUT = saved
    signals, ignored = commit_signals(commits, first, last, settings["quality"], config.commit_wip_prefix(cfg))
    spend = summarize(rows, settings["prices"])
    if not signals and not rows:
        return None, None
    text = render_quality(kind, name, first, last, spend, signals, rows, ignored)
    path = None
    if write:
        path = os.path.join(str(root), *posixpath.normpath(settings["reports"]).split("/"), PERIODS[kind],
                            name + "-quality.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return text, path


def record(root, transcript, cfg):
    """Append the new tokens of `transcript` to the ledger; returns the number of lines written."""
    settings = config.metrics(cfg)
    if not settings["record"]:
        return 0
    ledger = os.path.join(str(root), *posixpath.normpath(settings["ledger"]).split("/"))
    seen = ledger_sums(ledger)
    new = []
    for key, now in sorted(totals(transcript).items()):
        done = seen.get(key, dict.fromkeys(TOKEN_KEYS, 0))
        if any(done[k] > now[k] for k in TOKEN_KEYS):
            continue  # the ledger holds more than the transcript (rotated): leave the key alone
        diff = {k: now[k] - done[k] for k in TOKEN_KEYS}
        if any(diff.values()):
            new.append((key, diff))
    if not new:
        return 0
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    refs = head_refs(root)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = ""
    for (session, agent, model, day), diff in new:
        row = dict(diff, session=session, agent=agent, model=model, date=day, branch=branch, refs=refs, recorded=stamp)
        text += json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
    os.makedirs(os.path.dirname(ledger), exist_ok=True)
    with open(ledger, "a", encoding="utf-8") as f:
        f.write(text)  # one write: the lines of this run go in together
    return len(new)


def day_arg(text):
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a date YYYY-MM-DD") from None
    if len(text) != 10:
        raise argparse.ArgumentTypeError(f"{text!r} is not a date YYYY-MM-DD")
    return text


def run_record(args):
    event = read_event()
    active = event.get("stop_hook_active") is True
    doctor = f"python3 {os.path.join(HERE, 'doctor.py')}"
    try:
        root = config.find_root(args.root)
        cfg = config.load(root)
        if not config.metrics(cfg)["record"]:
            return 0
        transcript = args.transcript or event.get("transcript_path")
        transcript, _ = session_log.find(root, transcript, warn=False)
        if not transcript:
            raise MetricsError("no session transcript found")
        record(cfg["_root"], transcript, cfg)
    except (config.ConfigError, MetricsError, OSError) as exc:
        text = " ".join(str(exc).split()) or type(exc).__name__
        if not active:
            print(json.dumps({"systemMessage": f"metrics: {text}; run {doctor}"}))
    return 0


def run_price(args):
    """Print the price entry a ledger row of MODEL and DATE takes, as JSON; exit 1 when there is none."""
    try:
        cfg = config.load(config.find_root(args.root))
    except config.ConfigError as exc:
        print(f"metrics: {exc}", file=sys.stderr)
        return 2
    day = args.date or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    price = price_of(config.metrics(cfg)["prices"], args.model, day)
    if price is None:
        print(f"metrics: no price for {args.model} on {day}; add it to metrics.prices in .claude/gw.json "
              f"(python3 {os.path.join(HERE, 'config.py')} get metrics shows the key)", file=sys.stderr)
        return 1
    print(json.dumps(price, sort_keys=True))
    return 0


def run_report(args):
    """Print the period report (and write it with --write); exit 0 also when the period has no rows."""
    try:
        cfg = config.load(config.find_root(args.root))
    except config.ConfigError as exc:
        print(f"metrics: {exc}", file=sys.stderr)
        return 2
    day = datetime.date.fromisoformat(args.date) if args.date else datetime.datetime.now(datetime.timezone.utc).date()
    try:
        text, path = report(cfg["_root"], cfg, args.period, day, write=args.write)
    except OSError as exc:
        print(f"metrics: cannot write the report ({exc}); check the metrics.reports folder in .claude/gw.json", file=sys.stderr)
        return 1
    if text is None:
        name = period_of(args.period, day)[0]
        print(f"metrics: no ledger rows in {args.period} {name}; nothing to report (python3 "
              f"{os.path.join(HERE, 'config.py')} get metrics shows the ledger path)", file=sys.stderr)
        return 0
    sys.stdout.write(text)
    if path:
        print(f"metrics: wrote {os.path.relpath(path, str(cfg['_root']))}", file=sys.stderr)
    return 0


def run_compare(args):
    """Print the comparison; exit 0 also when both periods are empty, 2 when both dates are in the same period."""
    try:
        cfg = config.load(config.find_root(args.root))
    except config.ConfigError as exc:
        print(f"metrics: {exc}", file=sys.stderr)
        return 2
    day = datetime.date.fromisoformat(args.date) if args.date else datetime.datetime.now(datetime.timezone.utc).date()
    against = datetime.date.fromisoformat(args.against) if args.against else None
    try:
        text = compare(cfg["_root"], cfg, args.period, day, against)
    except ValueError as exc:
        print(f"metrics: {exc}; give --against a date in another {args.period}, or leave it out to use the one before",
              file=sys.stderr)
        return 2
    if text is None:
        print(f"metrics: no ledger rows in either {args.period}; nothing to compare (python3 "
              f"{os.path.join(HERE, 'config.py')} get metrics shows the ledger path)", file=sys.stderr)
        return 0
    sys.stdout.write(text)
    return 0


def run_quality(args):
    """Print the quality report (and write it with --write); exit 0 also when the period is empty, 2 on a git failure
    or a bad config."""
    try:
        cfg = config.load(config.find_root(args.root))
    except config.ConfigError as exc:
        print(f"metrics: {exc}", file=sys.stderr)
        return 2
    day = datetime.date.fromisoformat(args.date) if args.date else datetime.datetime.now(datetime.timezone.utc).date()
    try:
        text, path = quality_report(cfg["_root"], cfg, args.period, day, write=args.write)
    except MetricsError as exc:
        print(f"metrics: {exc}; quality reads the commit history, so run it inside the git repository "
              f"(git -C {cfg['_root']} log -1 shows the problem)", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"metrics: cannot write the report ({exc}); check the metrics.reports folder in .claude/gw.json", file=sys.stderr)
        return 1
    if text is None:
        name = period_of(args.period, day)[0]
        print(f"metrics: no commits with Refs and no ledger rows in {args.period} {name}; nothing to report (python3 "
              f"{os.path.join(HERE, 'metrics.py')} quality --period {args.period} --date D tries another one)",
              file=sys.stderr)
        return 0
    sys.stdout.write(text)
    if path:
        print(f"metrics: wrote {os.path.relpath(path, str(cfg['_root']))}", file=sys.stderr)
    return 0


def run_alert(args):
    """Print one line per model over its alert threshold; exit 0, also with nothing to say; 2 on a bad config."""
    try:
        cfg = config.load(config.find_root(args.root))
    except config.ConfigError as exc:
        print(f"metrics: {exc}", file=sys.stderr)
        return 2
    day = datetime.date.fromisoformat(args.date) if args.date else datetime.datetime.now(datetime.timezone.utc).date()
    for text in alerts(cfg["_root"], cfg, day):
        print(f"metrics: {text}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="metrics.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="append the new token usage of the session to the ledger")
    rec.add_argument("--transcript", help="main transcript (default: transcript_path of the hook JSON, else the newest)")
    rec.add_argument("--root", help="project root (default: see config.find_root)")
    rec.set_defaults(func=run_record)
    pr = sub.add_parser("price", help="print the price (USD per million tokens) a ledger row of MODEL on DATE takes")
    pr.add_argument("model")
    pr.add_argument("--date", type=day_arg, help="UTC date YYYY-MM-DD (default: today)")
    pr.add_argument("--root", help="project root (default: see config.find_root)")
    pr.set_defaults(func=run_price)
    rp = sub.add_parser("report", help="sum the ledger rows of a period by model, agent, branch and task id")
    rp.add_argument("--period", required=True, choices=sorted(PERIODS))
    rp.add_argument("--date", type=day_arg, help="any UTC date YYYY-MM-DD in the period (default: today)")
    rp.add_argument("--write", action="store_true", help="also save it under metrics.reports/<daily|weekly|...>/")
    rp.add_argument("--root", help="project root (default: see config.find_root)")
    rp.set_defaults(func=run_report)
    cp = sub.add_parser("compare", help="set a period beside the one before it, or beside another of the same kind")
    cp.add_argument("--period", required=True, choices=sorted(PERIODS))
    cp.add_argument("--date", type=day_arg, help="any UTC date YYYY-MM-DD in the period (default: today)")
    cp.add_argument("--against", type=day_arg, help="any UTC date in the period to compare with (default: the one before)")
    cp.add_argument("--root", help="project root (default: see config.find_root)")
    cp.set_defaults(func=run_compare)
    al = sub.add_parser("alert", help="warn about each model whose daily spend passes metrics.alert.factor x its mean")
    al.add_argument("--date", type=day_arg, help="UTC date YYYY-MM-DD to check with the day before (default: today)")
    al.add_argument("--root", help="project root (default: see config.find_root)")
    al.set_defaults(func=run_alert)
    qp = sub.add_parser("quality", help="set quality signals from the commit messages beside the spend per task id")
    qp.add_argument("--period", required=True, choices=sorted(PERIODS))
    qp.add_argument("--date", type=day_arg, help="any UTC date YYYY-MM-DD in the period (default: today)")
    qp.add_argument("--write", action="store_true", help="also save it as <name>-quality.md under metrics.reports/...")
    qp.add_argument("--root", help="project root (default: see config.find_root)")
    qp.set_defaults(func=run_quality)
    args = ap.parse_args(argv)
    if args.command in ("price", "report", "compare", "alert", "quality"):
        return args.func(args)
    try:
        return args.func(args)
    except Exception as exc:  # a hook must never crash the stop
        print(json.dumps({"systemMessage": f"metrics: unexpected {type(exc).__name__}: {exc}; run python3 "
                                           f"{os.path.join(HERE, 'doctor.py')}"}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
