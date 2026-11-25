#!/usr/bin/env python3
# galivelop-workflow v0.9.0
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
import contextlib
import glob
import json
import os
import re
import sys
import time

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


def text_chars(entry):
    """Characters of the text a transcript line carries into the context (message content), 0 if none."""
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return len(content)
    total = 0
    for part in content if isinstance(content, list) else []:
        if isinstance(part, dict):
            for key in ("text", "content"):
                value = part.get(key)
                total += len(value) if isinstance(value, str) else len(json.dumps(value)) if value else 0
    return total


def startups(path):
    """One segment per stretch between boundaries (file start, compact_boundary, compaction summary), in order:
    {"start": timestamp or "", "first_usage": tokens of its first measured assistant turn or None, "model": id or
    None, "carried": characters of the conversation before that turn (compaction summary, first prompt), which a
    /clear drops}."""
    segments = [{"start": "", "first_usage": None, "model": None, "carried": 0}]
    for entry in entries(path):
        if is_boundary(entry):
            segments.append({"start": str(entry.get("timestamp") or ""), "first_usage": None, "model": None,
                             "carried": text_chars(entry) if entry.get("isCompactSummary") else 0})
            continue
        seg = segments[-1]
        if seg["first_usage"] is None:
            used = usage_of(entry)
            if used is not None:
                seg["first_usage"] = used
                seg["model"] = entry["message"].get("model")
                if not seg["start"]:
                    seg["start"] = str(entry.get("timestamp") or "")
            elif not entry.get("isSidechain"):
                seg["carried"] += text_chars(entry)
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
    if (cfg or {}).get("pendingFile") and cap > 0 and len(log_text) > cap:  # `archive` works on pendingFile
        log_fix = f"over logSize ({len(log_text)} > {cap} chars): shorten the log by hand (`archive` does not touch it)"
    elif (cfg or {}).get("pendingFile"):
        log_fix = "shorten it by hand and keep cells ≤ 800 chars (`archive` works on pendingFile, not on the log)"
    elif cap > 0 and len(log_text) > cap:
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


SYSTEM = "rest of the system (system prompt, tools, MCP)"
SYSTEM_ADVICE = ("the largest part of the startup is the system (system prompt, tools, MCP), which /clear does not "
                 "shrink: push what there is and disable the connectors/MCP servers you do not use (/context shows "
                 "them) instead of asking for /clear")


CARRIED = "conversation carried over (compaction summary, first prompt)"


def culprits(root, cfg, measured, hook_chars, carried_chars=0):
    """The breakdown, the conversation carried over and the rest of the system, largest first: [(label, tokens,
    fix)]."""
    parts = breakdown(root, cfg, hook_chars)
    if carried_chars:
        parts.append((CARRIED, int(carried_chars / chars_per_token(cfg)),
                      "a /clear drops it: push what there is and ask the user for /clear"))
    rest = max(0, measured - sum(t for _, t, _ in parts))
    parts.append((SYSTEM, rest, "fewer MCP servers/tools: /context shows them; disable the unused ones"))
    parts.sort(key=lambda p: -p[1])
    return parts


def culprit_lines(root, cfg, measured, hook_chars, carried_chars=0, parts=None):
    """One line per culprit; `parts` is a list culprits() already made (B41: measured once)."""
    if parts is None:
        parts = culprits(root, cfg, measured, hook_chars, carried_chars)
    return [f"  {label}: ~{fmt(t)} tokens ({round(100 * t / measured) if measured else 0} %) — fix: {fix}"
            for label, t, fix in parts]


class Measure:
    """One reading of the transcript for recover.py --state (B41): the startups are read once and the culprits of
    the last one computed once, however many warnings use them. Build it after hook_chars is final."""

    def __init__(self, root, cfg, path, hook_chars=0):
        self.root, self.cfg, self.path, self.hook_chars = root, cfg, path, hook_chars
        self.segs = [s for s in startups(path) if s["first_usage"] is not None] if path else []
        self.last = self.segs[-1] if self.segs else None
        self._culprits = None

    def culprits(self):
        """culprits() of the last measured startup, computed on the first call. None without one."""
        if self._culprits is None and self.last:
            self._culprits = culprits(self.root, self.cfg, self.last["first_usage"], self.hook_chars,
                                      self.last.get("carried", 0))
        return self._culprits


def last_startup(path):
    """The last startup with a measured turn, or None."""
    return Measure(None, None, path).last


def startup_pct(seg, cfg):
    cutoff = cutoff_for(seg["model"], cfg)
    return round(100 * seg["first_usage"] / cutoff) if cutoff else 0


def system_weighs_most(root, cfg, seg, hook_chars=0, parts=None):
    """D122, the one rule: the startup `seg` is big (at least contextGuard.warn % of the cutoff), the system (prompt,
    tools, MCP) is its largest culprit, so a /clear does not shrink it, and contextGuard.systemAdvice is on. `parts`:
    the culprits of `seg` if already computed, or a callable that computes them, called only past the guards (B41)."""
    guard = config.context_guard(cfg or {})
    if not guard["systemAdvice"] or startup_pct(seg, cfg) < guard["warn"]:
        return False
    if parts is None:
        parts = culprits(root, cfg, seg["first_usage"], hook_chars, seg.get("carried", 0))
    elif callable(parts):
        parts = parts()
    return parts[0][0] == SYSTEM


def system_is_largest(root, cfg, path, hook_chars=0, measure=None):
    """system_weighs_most for the last measured startup of the transcript (or of `measure`, a Measure already made,
    which then stands for root, cfg, path and hook_chars). False when unknown. Never raises."""
    try:
        m = measure or Measure(root, cfg, path, hook_chars)
        return bool(m.last) and system_weighs_most(m.root, m.cfg, m.last, m.hook_chars, parts=m.culprits)
    except Exception:  # fail open: unknown means the usual advice
        return False


def report(root, cfg, path, source, hook_chars=0, measure=None):
    """Lines for recover.py --state about the startup context (`measure`: a Measure already made, which then stands
    for root, cfg, path and hook_chars). Never raises."""
    unknown = "- Startup context: unknown (no measured turn yet after the last compaction or /clear)"
    try:
        m = measure or Measure(root, cfg, path, hook_chars)
        root, cfg, hook_chars, segs = m.root, m.cfg, m.hook_chars, m.segs
        guard = config.context_guard(cfg or {})
        if not segs:
            return [unknown]
        # At SessionStart the current startup has no assistant turn yet, so the last measured one is the stretch
        # that just ended.
        last = m.last
        cutoff = cutoff_for(last["model"], cfg)
        pct = startup_pct(last, cfg)
        lines = [f"- Startup context of the last stretch: {fmt(last['first_usage'])} tokens = {pct} % of the "
                 f"compaction cutoff {fmt(cutoff)} (model {last['model']})"]
        eff = pct  # D156: what the user can reduce; the system (prompt, tools, MCP) is not theirs to trim
        if system_weighs_most(root, cfg, last, hook_chars, parts=m.culprits):
            sys_tokens = next(t for label, t, _ in m.culprits() if label == SYSTEM)
            eff = startup_pct(dict(last, first_usage=max(0, last["first_usage"] - sys_tokens)), cfg)
            if eff < guard["warn"]:
                lines.append(f"- Note: startup context is {pct} % of the cutoff, but {fmt(sys_tokens)} tokens of it are "
                             f"the system (prompt, tools, MCP) and the part you control is {eff} % (below warn "
                             f"{guard['warn']} %): nothing to trim here; {SYSTEM_ADVICE}")
        if eff >= guard["warn"]:
            lines.append(f"- Warning: startup context above {guard['warn']} %: the culprits, largest first:")
            lines += culprit_lines(root, cfg, last["first_usage"], hook_chars, parts=m.culprits())
        if eff >= guard["alarm"]:
            lines.append(f"- ALARM: startup context above {guard['alarm']} %")

        def over(seg):
            c = cutoff_for(seg["model"], cfg)
            return bool(c) and 100 * seg["first_usage"] / c >= guard["alarm"]

        if (source == "compact" and over(last)) or (len(segs) >= 2 and over(segs[-1]) and over(segs[-2])):
            fix = (SYSTEM_ADVICE if system_weighs_most(root, cfg, last, hook_chars, parts=m.culprits)
                   else "push what there is and ask the user for /clear")
            lines.append(f"- ALARM: compaction loop: the previous stretch already started at {pct} % of the cutoff and "
                         f"compacted again. Stop: {fix}; the log's compaction budget applies (see above).")
        return lines
    except Exception:  # fail open: a guard must not cost the whole state
        return [unknown]


def tail_entries(path, tail_bytes):
    """The JSON objects of the transcript's last `tail_bytes` bytes (a line the cut splits is dropped), in order."""
    with open(path, "rb") as fh:
        size = fh.seek(0, os.SEEK_END)
        start = max(0, size - tail_bytes)
        fh.seek(max(0, start - 1))  # one byte before: tells whether the tail begins at a line start
        data = fh.read(size - max(0, start - 1))
    lines = data.split(b"\n")
    if start > 0:
        lines = lines[1:]  # data[0] is the byte before the tail: "\n" (empty first piece) or a cut line
    out = []
    for raw in lines:
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


def current_context(path, tail_bytes=None):
    """(tokens, model) of the last measured assistant turn of the current stretch (after the last boundary), or None:
    no such turn yet, or a transcript that cannot be read. With `tail_bytes`, only that tail is read."""
    found = None
    try:
        for entry in (tail_entries(path, tail_bytes) if tail_bytes else entries(path)):
            if is_boundary(entry):
                found = None
                continue
            used = usage_of(entry)
            if used is not None:
                found = (used, entry["message"].get("model"))
    except (OSError, TypeError, ValueError, OverflowError, MemoryError):
        return None
    return found


def window_known(root, model):
    """B31: True when the compaction cutoff of `model` is not a guess: the model id says 1M (`[1m]`/`-1m`), or the
    project's .claude/gw.json writes contextGuard.cutoff or contextGuard.window itself. The transcript's model id
    lacks `[1m]` even in a 1M session (seen 2026-11-17), so the default 200,000 window could warn far too early."""
    name = str(model or "").lower()
    return "[1m]" in name or "-1m" in name or bool({"cutoff", "window"} & config.given_keys(root, "contextGuard"))


WARNED_LOCK_TRIES = 10  # B31: non-blocking tries for the marker's lock, WARNED_LOCK_WAIT seconds apart; then no lock
WARNED_LOCK_WAIT = 0.05


def read_warned(state):
    """B31: {absolute transcript path: compactions counted when it warned} from the state file, one JSON object per
    line ({"transcript": ..., "counted": ...}), oldest first. Missing or unreadable file: {}; a bad line (not that
    JSON, the previous one-line "path|count" format included): skipped, at worst that stretch warns again. Never
    raises."""
    warned = {}
    try:
        with open(state, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except (OSError, ValueError):
        return warned
    for line in lines:
        try:
            item = json.loads(line)
            key, counted = item["transcript"], item["counted"]
            if isinstance(key, str) and key and type(counted) is int:
                warned.pop(key, None)  # the last line for a transcript wins and moves to the end
                warned[key] = counted
        except Exception:  # any odd line is just skipped
            continue
    return warned


@contextlib.contextmanager
def warned_lock(state):
    """An exclusive flock on `<state>.lock` while the block runs, so concurrent Stop hooks do not lose each other's
    entries. Not taken (no fcntl, the lock file cannot be opened, still busy after WARNED_LOCK_TRIES tries): the block
    runs without it, as before, never waiting longer. Never raises by itself."""
    fd = None
    try:
        import fcntl
        fd = os.open(f"{state}.lock", os.O_RDWR | os.O_CREAT, 0o644)
        for attempt in range(WARNED_LOCK_TRIES):
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if attempt + 1 < WARNED_LOCK_TRIES:
                    time.sleep(WARNED_LOCK_WAIT)
    except Exception:
        pass
    try:
        yield
    finally:
        if fd is not None:
            try:
                os.close(fd)  # closing the file releases the lock
            except OSError:
                pass


def write_warned(state, key, counted, keep_max):
    """Under warned_lock, read the state file again, set key -> counted (moved last), keep the `keep_max` newest
    (contextGuard.warnedMax) and write it atomically: a temporary file in the same directory, then os.replace, so a
    reader sees the old file or the new one, never half; the temporary file never stays behind. Never raises."""
    tmp = f"{state}.{os.getpid()}.tmp"
    try:
        with warned_lock(state):
            warned = read_warned(state)
            warned.pop(key, None)
            warned[key] = counted
            keep = list(warned.items())[-keep_max:]
            with open(tmp, "w", encoding="utf-8") as fh:
                for name, value in keep:
                    fh.write(json.dumps({"transcript": name, "counted": value}) + "\n")
            os.replace(tmp, state)
    except Exception:  # unwritable: that stretch warns again
        pass
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def near_cutoff(root, cfg, branch, transcript, state=None):
    """B31: (stretch, message) when the context of the current stretch reaches contextGuard.nearRatio of the
    compaction cutoff and the task's compaction budget is already spent (compactions since the task started >= the
    log's budget, recover.budget_count); else None. The message, for the agent, proposes closing the step (log, commit
    and push, recommend /clear to the user) or, when the system weighs most (D122), says /clear will not lower it.
    Cheap checks first: nearRatio 0 (off), the transcript's last `stopTranscriptBytes` bytes (0 = off), a window
    that is not known (window_known), a context below the ratio; only then the log's budget and the whole transcript.
    `state` (a file, read_warned): the stretch warned last for each transcript, so sessions sharing it do not
    overwrite each other's; the same stretch gives None, a new one is written there (unwritable: it warns again). `stretch` = transcript and compactions since the task started. Never raises; any failure: None."""
    try:
        cfg = cfg or {}
        guard = config.context_guard(cfg)
        ratio = guard["nearRatio"]
        tail = cfg.get("stopTranscriptBytes", config.schema_default("stopTranscriptBytes"))
        if not ratio or not tail or not transcript or not os.path.isfile(str(transcript)):
            return None
        transcript = str(transcript)
        now = current_context(transcript, tail)
        if now is None:
            return None
        tokens, model = now
        cutoff = cutoff_for(model, cfg)
        if not cutoff or tokens < ratio * cutoff or not window_known(root, model):
            return None
        import recover
        spent = recover.budget_count(root, branch, transcript)
        if spent is None or spent[0] < spent[1]:
            return None
        counted, budget = spent
        key = os.path.abspath(transcript)
        stretch = f"{key}|{counted}"
        warned = read_warned(state) if state else {}
        if warned.get(key) == counted:
            return None
        if counted == budget:
            where = f"the task's compaction budget is already spent ({counted} of {budget}): the next compaction passes it"
        else:
            where = f"the task's compaction budget is already passed ({counted} compactions, budget {budget})"
        if system_is_largest(root, cfg, transcript):
            advice = f"close the step now (update the log, commit and push); {SYSTEM_ADVICE}"
        else:
            advice = "close the step now: update the log, commit and push, then recommend /clear to the user"
        message = (f"Context at {round(100 * tokens / cutoff)} % of the compaction cutoff ({fmt(tokens)} of "
                   f"{fmt(cutoff)} tokens) and {where}; {advice}.")
        if state:
            write_warned(state, key, counted, guard["warnedMax"])
        return stretch, message
    except Exception:  # a warning must never cost the stop
        return None


def near_cutoff_once(root, cfg, branch, transcript, state):
    """near_cutoff's message the first time in a stretch (remembered per transcript in the file `state`,
    read_warned; before-stop.py: <git dir>/gw-context-warn), else None. Never raises."""
    found = near_cutoff(root, cfg, branch, transcript, state)
    return found[1] if found else None


def closed_tasks(root, cfg, since):
    """E66: ids of the roadmap rows (first `roadmapFiles` file) that a first-parent, non-merge commit of HEAD made
    since `since` (an ISO timestamp, or "" for any) turned from an open status to its done word, oldest first. []
    without roadmapFiles, git or the file. Never raises."""
    try:
        import subprocess
        import roadmap
        files = config.roadmap_files(cfg or {})
        if not files or not files[0].get("done"):
            return []
        path, done = files[0]["path"], files[0]["done"].lower()
        words = tuple(w.lower() for w in files[0].get("open") or [])

        def git(*args):
            r = subprocess.run(["git", "-C", str(root)] + list(args), capture_output=True, text=True, timeout=10)
            return r.stdout if r.returncode == 0 else None

        def statuses(text):
            out = {}
            for line in (text or "").splitlines():
                spans = roadmap.cells(line)
                if spans and len(spans) >= 3:
                    out[line[spans[0][0]:spans[0][1]].strip()] = roadmap.status_of(line).lower()
            return out

        start = None
        if since:
            import datetime
            start = datetime.datetime.fromisoformat(since.replace("Z", "+00:00")).timestamp()
        listed = git("log", "--first-parent", "--no-merges", "--reverse", "--format=%H %ct", "HEAD", "--", path)
        found = []
        for line in (listed or "").splitlines():
            sha, _, stamp = line.partition(" ")
            if start is not None and int(stamp) < start:
                continue
            before, after = statuses(git("show", f"{sha}^:{path}")), statuses(git("show", f"{sha}:{path}"))
            for task, status in after.items():
                old = before.get(task, "")
                if status.startswith(done) and words and old.startswith(words) and task not in found:
                    found.append(task)
        return found
    except Exception:  # only a warning: never raises
        return []


def clear_after_task(root, cfg, transcript, tail_bytes=None):
    """E66: (closed task ids, message, stretch start) when a task was closed in the current stretch (closed_tasks
    since the stretch started) and the conversation the stretch added since its startup, which a /clear drops, reaches
    contextGuard.clearAfterTask of the compaction cutoff; else None. The message asks to answer the next "next" with
    a one-line request for /clear. Cheap checks first: the key (0 = off), the transcript's tail (`tail_bytes`), the
    context against the threshold, a window that is not known (window_known); only then the whole transcript and
    git. The stretch start (its ISO timestamp, "" for the first stretch) tells one stretch from the next. Never
    raises."""
    try:
        cfg = cfg or {}
        ratio = config.context_guard(cfg)["clearAfterTask"]
        if not ratio or not transcript or not os.path.isfile(str(transcript)):
            return None
        transcript = str(transcript)
        now = current_context(transcript, tail_bytes)
        if now is None:
            return None
        tokens, model = now
        cutoff = cutoff_for(model, cfg)
        if not cutoff or tokens < ratio * cutoff or not window_known(root, model):
            return None
        seg = Measure(root, cfg, transcript).last
        if not seg:
            return None
        grown = tokens - seg["first_usage"]
        if grown < ratio * cutoff:
            return None
        tasks = closed_tasks(root, cfg, seg["start"])
        if not tasks:
            return None
        message = (f"Task {', '.join(tasks)} closed in this stretch and the conversation since its start weighs "
                   f"{fmt(grown)} tokens ({round(100 * grown / cutoff)} % of the compaction cutoff {fmt(cutoff)}; "
                   f"contextGuard.clearAfterTask {ratio}): with the log up to date and everything pushed, do not chain "
                   f"the next task; ask the user for /clear in one line (a long context is almost all the spend; "
                   f"the log is enough to resume), and answer a \"next\" after a close the same way.")
        return tasks, message, seg["start"]
    except Exception:  # a warning must never cost the stop
        return None


def clear_after_task_once(root, cfg, transcript, state, tail_bytes=None):
    """clear_after_task's message once per closed task of each stretch (the number of closed tasks warned last is
    remembered in the file `state` under transcript|stretch start, so a compaction restarts the count, read_warned;
    before-stop.py: <git dir>/gw-clear-warn), else None. Never raises."""
    found = clear_after_task(root, cfg, transcript, tail_bytes)
    if not found:
        return None
    try:
        key = f"{os.path.abspath(str(transcript))}|{found[2]}"
        if read_warned(state).get(key, 0) >= len(found[0]):
            return None
        write_warned(state, key, len(found[0]), config.context_guard(cfg or {})["warnedMax"])
    except Exception:
        return None
    return found[1]


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
