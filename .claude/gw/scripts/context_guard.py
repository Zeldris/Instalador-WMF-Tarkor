#!/usr/bin/env python3
# galivelop-workflow v0.6.0
"""Startup-context and compaction-loop guard (B21). Imported by recover.py --state; also a CLI for hand use.

After a /clear or a compaction the session starts again with the log state, AGENTS.md/CLAUDE.md, hook output, skills
and tools already in the context. If that startup is big, the next compaction comes sooner, and a startup that
is already over the threshold compacts again and again (a loop). This reads the transcript (never the model): the
usage of the first assistant turn after each boundary (input + cache_read + cache_creation tokens) is compared with
the compaction cutoff (`contextGuard.cutoff` in .claude/gw.json; 0 = the model's window x `autocompactShare`), not
with the window. Above `contextGuard.warn` percent the notice warns and names the culprit with a deterministic
estimate (log, AGENTS.md/CLAUDE.md and what they include, hook output, skills, rest of the system) and the command
that fixes it; above `alarm` percent it alarms; a compaction whose previous stretch already started over `alarm`
(or two consecutive stretches over it) is a loop: stop, push, ask for /clear.

  python3 context_guard.py [--session PATH] [--root R] [--source compact|clear|startup]

Prints the report lines. Exit 0 always, except a config error (exit 2, message on stderr). Fails open: an unreadable
transcript or file gives "unknown" lines, never an exception out of report(). Python 3.8+ standard library only.
"""
import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, HERE)
import config  # noqa: E402
import session_log  # noqa: E402

INCLUDE = re.compile(r"^\s*@(\S+)\s*$")


def entries(path):
    """The transcript's JSON objects; bad lines are skipped."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                yield entry


def usage_of(entry):
    """input + cache_creation + cache_read tokens of an assistant transcript line, else None (not an assistant turn
    with usage, a synthetic model, or a sidechain/subagent turn)."""
    if entry.get("type") != "assistant" or entry.get("isSidechain"):
        return None
    message = entry.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
        return None
    if str(message.get("model") or "").startswith("<"):
        return None
    usage = message["usage"]
    total = 0
    for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        value = usage.get(key) or 0
        total += value if isinstance(value, int) and not isinstance(value, bool) else 0
    return total


def is_boundary(entry):
    return (entry.get("subtype") == "compact_boundary" or entry.get("type") == "compact_boundary"
            or bool(entry.get("isCompactSummary")))


def startups(path):
    """One segment per stretch between boundaries (file start, compact_boundary, compaction summary), in order:
    {"start": timestamp or "", "first_usage": tokens of its first measured assistant turn or None, "model": id or
    None}."""
    segments = [{"start": "", "first_usage": None, "model": None}]
    for entry in entries(path):
        if is_boundary(entry):
            segments.append({"start": str(entry.get("timestamp") or ""), "first_usage": None, "model": None})
            continue
        seg = segments[-1]
        if seg["first_usage"] is None:
            used = usage_of(entry)
            if used is not None:
                seg["first_usage"] = used
                seg["model"] = entry["message"].get("model")
                if not seg["start"]:
                    seg["start"] = str(entry.get("timestamp") or "")
    return segments


def cutoff_for(model, cfg):
    """Compaction cutoff in tokens: contextGuard.cutoff when set, else window x autocompactShare."""
    guard = config.context_guard(cfg or {})
    if guard["cutoff"] > 0:
        return int(guard["cutoff"])
    name = str(model or "").lower()
    window = guard["bigWindow"] if "[1m]" in name or "-1m" in name else guard["window"]
    return int(window * guard["autocompactShare"])


def chars_per_token(cfg=None):
    """contextGuard.charsPerToken (default 3.5, the rule of skills/gw-opt-tokens/scripts/measure.py)."""
    return config.context_guard(cfg or {})["charsPerToken"]


def estimate_tokens(text, per_token=None):
    return int(len(text) / (per_token or chars_per_token()))


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def instruction_text(root):
    """AGENTS.md and CLAUDE.md at the root plus the files their `@path` lines include (each file once)."""
    seen, texts, todo = set(), [], [os.path.join(str(root), "AGENTS.md"), os.path.join(str(root), "CLAUDE.md")]
    while todo:
        path = os.path.normpath(todo.pop(0))
        if path in seen or not os.path.isfile(path):
            continue
        seen.add(path)
        text = read_text(path)
        texts.append(text)
        for line in text.splitlines():
            m = INCLUDE.match(line)
            if m:
                todo.append(os.path.join(os.path.dirname(path), os.path.expanduser(m.group(1))))
    return "\n".join(texts)


def skills_text(root):
    """The `name:` and `description:` frontmatter lines of every project and user skill."""
    bases = [os.path.join(str(root), ".claude", "skills"), os.path.join(os.path.expanduser("~"), ".claude", "skills")]
    parts = []
    for base in bases:
        for skill in sorted(glob.glob(os.path.join(glob.escape(base), "*", "SKILL.md"))):
            head = read_text(skill).split("\n---", 1)[0]
            parts += [l for l in head.splitlines() if l.startswith(("name:", "description:"))]
    return "\n".join(parts)


def breakdown(root, cfg, hook_chars=0):
    """Deterministic estimate of what the startup holds: [(label, tokens, fix)] in a fixed order."""
    log = (cfg or {}).get("log") or config.schema_default("log")
    log_text = read_text(os.path.join(str(root), log))
    archive = f"python3 {os.path.join(HERE, 'handoff.py')} archive"
    cap = config.log_size(cfg or {})
    if cap > 0 and len(log_text) > cap:
        log_fix = f"over logSize ({len(log_text)} > {cap} chars): {archive}"
    else:
        log_fix = f"shorten it: archive the items of published versions ({archive}) and keep cells ≤ 800 chars"
    per = chars_per_token(cfg)
    return [
        ("log", estimate_tokens(log_text, per), log_fix),
        ("AGENTS.md/CLAUDE.md", estimate_tokens(instruction_text(root), per),
         f"python3 {os.path.join(HERE, 'doctor.py')}: instructionLines"),
        ("hook output", int(hook_chars / chars_per_token(cfg)), "recover.outputCap in .claude/gw.json / trim the log state"),
        ("skills", estimate_tokens(skills_text(root), per), "fewer or shorter skill descriptions"),
    ]


def fmt(n):
    return f"{int(n):,}"


def culprit_lines(root, cfg, measured, hook_chars):
    parts = breakdown(root, cfg, hook_chars)
    rest = max(0, measured - sum(t for _, t, _ in parts))
    parts.append(("rest of the system (system prompt, tools, MCP)", rest,
                  "fewer MCP servers/tools: /context shows them; disable the unused ones"))
    parts.sort(key=lambda p: -p[1])
    return [f"  {label}: ~{fmt(t)} tokens ({round(100 * t / measured) if measured else 0} %) — fix: {fix}"
            for label, t, fix in parts]


def report(root, cfg, path, source, hook_chars=0):
    """Lines for recover.py --state about the startup context. Never raises."""
    unknown = "- Startup context: unknown (no measured turn yet after the last compaction or /clear)"
    try:
        guard = config.context_guard(cfg or {})
        segs = [s for s in startups(path) if s["first_usage"] is not None] if path else []
        if not segs:
            return [unknown]
        # At SessionStart the current startup has no assistant turn yet, so the last measured one is the stretch
        # that just ended.
        last = segs[-1]
        cutoff = cutoff_for(last["model"], cfg)
        pct = round(100 * last["first_usage"] / cutoff) if cutoff else 0
        lines = [f"- Startup context of the last stretch: {fmt(last['first_usage'])} tokens = {pct} % of the "
                 f"compaction cutoff {fmt(cutoff)} (model {last['model']})"]
        if pct >= guard["warn"]:
            lines.append(f"- Warning: startup context above {guard['warn']} %: the culprits, largest first:")
            lines += culprit_lines(root, cfg, last["first_usage"], hook_chars)
        if pct >= guard["alarm"]:
            lines.append(f"- ALARM: startup context above {guard['alarm']} %")

        def over(seg):
            c = cutoff_for(seg["model"], cfg)
            return bool(c) and 100 * seg["first_usage"] / c >= guard["alarm"]

        if (source == "compact" and over(last)) or (len(segs) >= 2 and over(segs[-1]) and over(segs[-2])):
            lines.append(f"- ALARM: compaction loop: the previous stretch already started at {pct} % of the cutoff and "
                         "compacted again. Stop: push what there is and ask the user for /clear; the log's compaction "
                         "budget applies (see above).")
        return lines
    except Exception:  # fail open: a guard must not cost the whole state
        return [unknown]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", metavar="PATH", help="transcript to read (default: the newest for the repo)")
    parser.add_argument("--root", help="repo path (default: the git top level, as config.py finds it)")
    parser.add_argument("--source", choices=("compact", "clear", "startup"), default="startup")
    args = parser.parse_args(argv)
    try:
        root = config.find_root(args.root)
        cfg = config.load(root)
    except config.ConfigError as exc:
        print(f"context_guard.py: {exc}", file=sys.stderr)
        return 2
    path, _ = session_log.find(root, args.session, warn=False)
    print("\n".join(report(root, cfg, path, args.source)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
