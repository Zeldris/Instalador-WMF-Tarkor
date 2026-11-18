#!/usr/bin/env python3
# galivelop-workflow v0.8.0
"""PreToolUse hook on `Read` and `Bash` (B26, E58): warn when a session reads WHOLE a watched file that is larger
than `wholeReadWarnBytes` in .claude/gw.json. It never blocks: it adds `additionalContext` to the call, so the next
steps read less; with no warning it prints nothing (no opinion).

Watched files: the hand-off log (`log`), its archive (`logArchive`), every file directly or deeper under
`recordsDir`, the files and folders (ending in /) of `wholeReadPaths` and the keys of `readPointers`; never the
extensions of `wholeReadSkipExtensions` (images, PDF, notebooks). A Read is "whole" when `tool_input` has no
`offset`, `limit` or `pages` (a null, 0 or empty value counts as absent). A Bash command is "whole" for each file it
gives to `cat`, `tac`, `nl`, `less`, `more`, `bat` (without a line range) or `sed` (without -n, -i or a `q` script),
also through `<`, unless its output goes to a pipe or a file (`cat F | head`, `cat F > out`); `cd` in the same command
moves the folder the paths resolve against (inside `( … )` only until it closes), the value of an option that takes
one (`nl -b a F`) is not a file, and the body of a heredoc (also `<<\\EOF`) is not read as commands. `grep`, `head`, `tail` and `sed -n` read a part and are never warned about. The log is
compared in characters (as `logSize` is), the rest in bytes. A watched file of more than `wholeReadWarnBytes` bytes
(default 20000; 0 turns the hook off) gets a note that names the size and the command that reads less:

  readPointers   its own command ({"<path>": "<command>"}, a folder key ends in /; it wins over the two below)
  hand-off log   python3 .claude/gw/scripts/recover.py --state (the state), or grep -n for a row and Read with
                 offset and limit
  the rest       Read with offset and limit, or grep -n for the heading first

`wholeReadRepeatOnly` (default true) warns only when this session already read the same file whole and it has not
changed since (same size and modification time): the first whole read is often needed, a second one is the content
twice in the context. The reads are kept per session in tempfile.gettempdir()/gw-reads-<session_id>.json (an own
regular file; the other sessions' files not written for `wholeReadStaleDays` days are deleted when one is created).
With no `session_id` in the event a repeat cannot be told, so nothing is warned. false = warn on every whole read.
A lock (gw-reads-<session_id>.lock, fcntl, cleaned like the state) keeps two parallel calls from losing a read, and recover.py --state drops the session's
reads on SessionStart clear|compact (`forget`): the content left the context, so a reread there is not a repeat.

Output format (https://code.claude.com/docs/en/hooks.md, PreToolUse): a JSON object on stdout, exit 0,

  {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "..."}}

Fails open, because it only advises: stdin it cannot read, an event that is not a Read or a Bash call, a command it
cannot split, a path outside the project, a file it cannot stat, a state file it cannot read or write or a config it
cannot read (the defaults apply to the config) print nothing and exit 0. The
project root is config.find_root (the script's own repo, never the current directory first); a relative path is
resolved against the event's `cwd`. Python 3.8+ standard library only.
"""
import contextlib
import glob
import json
import os
import re
import select
import shlex
import stat
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, HERE)
import config  # noqa: E402



def read_event():
    if sys.stdin is None or sys.stdin.isatty():
        return None
    try:
        ready, _, _ = select.select([sys.stdin], [], [], config.hook_stdin_wait())
        if not ready:
            return None
        data = json.loads(sys.stdin.read())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def settings(root):
    """The config as a dict of the hook's keys; the schema defaults when it cannot be read (`log` has none there:
    docs/handoff.md). `skip`: wholeReadSkipExtensions in lower case; `extra`: wholeReadPaths; `pointers`:
    readPointers ({path: command}); `repeat`: wholeReadRepeatOnly; `stale`: wholeReadStaleDays."""
    try:
        cfg = config.load(root)
    except Exception:  # advice only: any problem with the config means the defaults
        cfg = {}
    props = config._schema()["properties"]

    def pick(key, fallback=None):
        value = cfg.get(key)
        if isinstance(value, str) and value:
            return value
        return props[key].get("default", fallback)

    def pick_list(key):
        value = cfg.get(key)
        ok = isinstance(value, list) and all(isinstance(v, str) and v for v in value)
        return list(value) if ok else list(props[key]["default"])

    pointers = cfg.get("readPointers")
    if not (isinstance(pointers, dict) and all(isinstance(k, str) and k and isinstance(v, str) and v
                                               for k, v in pointers.items())):
        pointers = dict(props["readPointers"]["default"])
    repeat = cfg.get("wholeReadRepeatOnly")
    stale = cfg.get("wholeReadStaleDays")
    return {"limit": config.whole_read_warn_bytes(cfg), "log": pick("log", "docs/handoff.md"),
            "archive": pick("logArchive"), "records": pick("recordsDir"),
            "skip": tuple(e.lower() for e in pick_list("wholeReadSkipExtensions")),
            "extra": pick_list("wholeReadPaths"), "pointers": pointers,
            "repeat": repeat if isinstance(repeat, bool) else props["wholeReadRepeatOnly"]["default"],
            "stale": (stale if isinstance(stale, int) and not isinstance(stale, bool) and stale >= 1
                      else props["wholeReadStaleDays"]["default"])}


def is_whole(tool_input):
    return not (tool_input.get("offset") or tool_input.get("limit") or tool_input.get("pages"))


def matches(real, root, rel):
    """True when `real` is the repo-relative file `rel`, or lies under it when `rel` is a folder ending in /."""
    target = os.path.realpath(os.path.join(root, rel))
    return real == target or (rel.endswith("/") and real.startswith(target.rstrip(os.sep) + os.sep))


def kind_of(path, root, log, archive, records, extra=(), pointers=None):
    """('pointer', command) for a key of readPointers, ('log', None) for the hand-off log or its archive,
    ('record', None) for a file under recordsDir or one of `extra` (wholeReadPaths), else (None, None)."""
    real = os.path.realpath(path)
    for rel, command in (pointers or {}).items():
        if matches(real, root, rel):
            return "pointer", command
    for rel in (log, archive):
        if rel and real == os.path.realpath(os.path.join(root, rel)):
            return "log", None
    if records and matches(real, root, records.rstrip("/") + "/"):
        return "record", None
    for rel in extra:
        if matches(real, root, rel):
            return "record", None
    return None, None


def note(kind, rel, size, limit, how="this Read", command=None, repeat=False):
    head = (f"{rel} is {size} bytes (wholeReadWarnBytes {limit} in .claude/gw.json) and {how} takes it whole, "
            f"which costs tokens on every turn it stays in the context. ")
    if repeat:
        head += "This session already read it whole and it has not changed since: its content is in the context. "
    if kind == "pointer":
        return head + f"Instead: `{command}` (readPointers in .claude/gw.json)."
    if kind == "log":
        return head + ("Next time: `python3 .claude/gw/scripts/recover.py --state` for the state, "
                       "or grep -n for the row you need and Read with offset and limit.")
    return head + "Next time: grep -n for the heading you need, then Read with offset and limit."


# --- Bash: which files a command reads whole -------------------------------------------------------------------------

WHOLE = {"cat", "tac", "nl", "less", "more", "bat", "batcat"}
PREFIXES = {"sudo", "env", "command", "exec", "time", "nohup", "builtin"}
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*\\?(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
# Short options that take the next word as their value, so it is not a file (`nl -b a F`, `less -x 4 F`).
OPTION_ARGS = {"nl": set("bdfhilnsvw"), "less": set("bhjkopxyzDPT"), "more": set("n"), "cat": set(),
               "tac": set("s"), "bat": set("lmHp"), "batcat": set("lmHp")}
SED_QUIT = re.compile(r"(^|[0-9$/;{}\s])[qQ]\s*[0-9]*\s*(;|}|$)")


def command_lines(command):
    """The lines of `command` without heredoc bodies, with backslash-newline continuations joined."""
    lines, ends = [], []
    for line in command.split("\n"):
        if ends:
            if line.strip() == ends[0]:
                ends.pop(0)
            continue
        lines.append(line)
        ends.extend(m.group(2) for m in HEREDOC.finditer(line))
    return "\n".join(lines).replace("\\\n", " ").split("\n")


def simple_commands(line):
    """The simple commands of one shell line, in order, as ("cmd", words, inputs, sent, piped) with `words` without
    redirections, `inputs` the files given with `<`, `sent` True when its standard output goes to a file (so it does
    not reach the context) and `piped` True when it goes to the next command, plus ("(",) and (")",) for the
    subshells. Raises ValueError on a line shlex cannot split (an open quote)."""
    lex = shlex.shlex(line, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    out, words, inputs, sent, redirect = [], [], [], False, None

    def close(piped=False):
        out.append(("cmd", words, inputs, sent, piped))

    for token in lex:
        if redirect is not None:
            op, fd = redirect
            if op == "<":
                inputs.append(token)
            elif ">" in op and (op.startswith("&") or fd in ("", "1")) and not (op.endswith("&") and token == "2"):
                sent = True  # stdout to a file (`> out`, `&> out`); `>&2` still shows
            redirect = None
        elif token and set(token) <= set("<>&") and ("<" in token or ">" in token):
            fd = words.pop() if words and words[-1].isdigit() else ""  # `2>` is fd 2, not a file operand
            redirect = (token, fd)
        elif token and set(token) <= set(";&|()"):
            close(token in ("|", "|&"))
            words, inputs, sent = [], [], False
            out.extend((c,) for c in token if c in "()")
        else:
            words.append(token)
    close()
    return out


def sed_files(args):
    """The file operands of a sed call that prints its input whole, or None when it does not: -n/--quiet/--silent,
    -i/--in-place (it edits) or a script that quits early (`q`)."""
    files, scripts, explicit, i = [], [], False, 0
    while i < len(args):
        arg = args[i]
        if arg in ("-l", "--line-length"):
            i += 2
            continue
        if arg in ("-e", "--expression", "-f", "--file"):
            explicit = True
            if arg in ("-e", "--expression") and i + 1 < len(args):
                scripts.append(args[i + 1])
            i += 2
            continue
        if arg.startswith(("--expression=", "--file=")):
            explicit = True
            scripts.append(arg.split("=", 1)[1])
        elif arg in ("--quiet", "--silent") or arg.startswith("--in-place"):
            return None
        elif arg.startswith("-") and not arg.startswith("--") and len(arg) > 1:
            if "n" in arg[1:] or "i" in arg[1:]:
                return None
            if arg.endswith("e") or arg.endswith("f"):
                explicit = True
                if arg.endswith("e") and i + 1 < len(args):
                    scripts.append(args[i + 1])
                i += 2
                continue
        elif not arg.startswith("-"):
            if not explicit and not scripts:
                scripts.append(arg)
            else:
                files.append(arg)
        i += 1
    if any(SED_QUIT.search(s) for s in scripts):
        return None
    return files


def whole_files(name, args):
    """The file operands `name args` reads whole (see the module docstring), or None when it reads a part or nothing
    (then its `<` input is not read whole either)."""
    if name == "sed":
        return sed_files(args)
    if name not in WHOLE:
        return None
    if name in ("bat", "batcat") and any(a.startswith(("-r", "--line-range")) for a in args):
        return None
    files, skip = [], False
    for arg in args:
        if skip:
            skip = False
        elif arg.startswith("-") and len(arg) > 1:
            skip = len(arg) == 2 and arg[1] in OPTION_ARGS.get(name, ())
        else:
            files.append(arg)
    return files


def program_words(words):
    """`words` without leading VAR=value assignments and PREFIXES (sudo, env, …)."""
    while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]) or words[0] in PREFIXES):
        words = words[1:]
    return words


def passes_through(rest):
    """True when the command a pipe feeds (the first of `rest`) shows its input whole (`| less`, `| cat -n`), so what
    went into the pipe still reaches the context; False for a filter (`| head`, `| grep x`) or a file sink."""
    for item in rest:
        if item[0] != "cmd":
            continue
        _, words, inputs, sent, piped = item
        words = program_words(words)
        if not words or sent or inputs:
            return False
        operands = whole_files(os.path.basename(words[0]), words[1:])
        return operands == [] and (not piped or passes_through(rest[rest.index(item) + 1:]))
    return False


def bash_reads(command, cwd):
    """[(path, program)] for each file the Bash `command` reads whole into the context (not into a pipe or a file),
    resolved against `cwd` and the `cd`s before it (a `cd` inside `( … )` ends with it); globs are expanded. Raises
    ValueError when a line cannot be split."""
    found, stack = [], []
    for line in command_lines(command):
        items = simple_commands(line)
        for index, item in enumerate(items):
            if item[0] == "(":
                stack.append(cwd)
                continue
            if item[0] == ")":
                cwd = stack.pop() if stack else cwd
                continue
            _, words, inputs, sent, piped = item
            words = program_words(words)
            if not words:
                continue
            name = os.path.basename(words[0])
            if name == "cd":
                if len(words) > 1 and words[1] != "-":
                    cwd = os.path.join(cwd, os.path.expanduser(words[1]))
                continue
            operands = whole_files(name, words[1:])
            if operands is None or sent or (piped and not passes_through(items[index + 1:])):
                continue
            for operand in operands + inputs:
                path = os.path.join(cwd, os.path.expanduser(operand))
                hits = sorted(glob.glob(path)) if any(c in operand for c in "*?[") else [path]
                found.extend((hit, name) for hit in hits)
    return found


# --- per-session memory of whole reads ------------------------------------------------------------------------------

SESSION = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def state_path(session_id):
    if not isinstance(session_id, str) or not SESSION.match(session_id):
        return None
    return os.path.join(tempfile.gettempdir(), f"gw-reads-{session_id}.json")


def own_regular(path):
    info = os.lstat(path)
    return stat.S_ISREG(info.st_mode) and (not hasattr(os, "getuid") or info.st_uid == os.getuid())


def load_state(path):
    """{realpath: [size, mtime_ns]} of the session's earlier whole reads ({} when there are none)."""
    try:
        if not own_regular(path):
            return {}
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def clean_old(keep, days):
    """Delete other sessions' gw-reads-*.json and their .lock (own regular files) not written for `days` days."""
    folder, cutoff = os.path.dirname(keep), time.time() - days * 86400
    for path in glob.glob(os.path.join(folder, "gw-reads-*.json")) + \
            glob.glob(os.path.join(folder, "gw-reads-*.lock")):
        try:
            if path != keep and own_regular(path) and os.lstat(path).st_mtime < cutoff:
                os.unlink(path)
        except OSError:
            pass


def save_state(path, data, stale):
    if not os.path.lexists(path):
        clean_old(path, stale)
    elif not own_regular(path):
        return
    fd, tmp = tempfile.mkstemp(prefix="gw-reads-tmp-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def forget(session_id):
    """Drop the session's whole reads: after a compaction or /clear their content is no longer in the context, so a
    reread is not a repeat (recover.py --state calls it on SessionStart clear|compact)."""
    path = state_path(session_id)
    try:
        if path and os.path.lexists(path) and own_regular(path):
            os.unlink(path)
    except OSError:
        pass


@contextlib.contextmanager
def locked(path):
    """An exclusive lock on `path` with .lock for .json while the state is read and written, so two Reads in parallel do not lose one
    of them (the last os.replace would win). No lock where fcntl is missing (Windows) or the file cannot be opened."""
    try:
        import fcntl
        handle = open(path[:-len(".json")] + ".lock", "a")
    except (ImportError, OSError):
        yield
        return
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        handle.close()


def check(path, root, conf, state, how):
    """The note for one whole read of `path`, or None. Records the read in `state` (a dict) when it is watched."""
    try:
        info = os.stat(path)
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    size, limit = info.st_size, conf["limit"]
    if limit <= 0 or size <= limit or path.lower().endswith(conf["skip"]):
        return None
    kind, command = kind_of(path, root, conf["log"], conf["archive"], conf["records"], conf["extra"],
                            conf["pointers"])
    if kind is None:
        return None
    real = os.path.realpath(path)
    if conf["log"] and real == os.path.realpath(os.path.join(root, conf["log"])):
        # logSize counts characters: a log of accents that passes logSize must not warn here
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                if len(handle.read()) <= limit:
                    return None
        except OSError:
            return None
    repeat = False
    if conf["repeat"]:
        if state is None:
            return None
        now = [size, info.st_mtime_ns]
        repeat = state.get(real) == now
        state[real] = now
        if not repeat:
            return None
    rel = os.path.relpath(real, os.path.realpath(root))
    return note(kind, rel, size, limit, how, command, repeat)


def main():
    event = read_event()
    if not event or event.get("tool_name") not in ("Read", "Bash"):
        return 0
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) and event.get("cwd") else os.getcwd()
    if event["tool_name"] == "Read":
        target = tool_input.get("file_path")
        if not is_whole(tool_input) or not isinstance(target, str) or not target:
            return 0
        reads = [(target if os.path.isabs(target) else os.path.join(cwd, target), "this Read")]
    else:
        command = tool_input.get("command")
        if not isinstance(command, str) or not command:
            return 0
        reads = [(path, f"this `{name}`") for path, name in bash_reads(command, cwd)]
    if not reads:
        return 0
    try:
        root = str(config.find_root())
    except Exception:
        return 0
    conf = settings(root)
    if conf["limit"] <= 0:
        return 0
    spath = state_path(event.get("session_id")) if conf["repeat"] else None
    notes = []
    with locked(spath) if spath else contextlib.nullcontext():
        state = load_state(spath) if spath else None
        before = dict(state) if state is not None else None
        for path, how in reads:
            text = check(path, root, conf, state, how)
            if text and text not in notes:
                notes.append(text)
        if spath and state != before:
            save_state(spath, state, conf["stale"])
    if notes:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "additionalContext": "\n".join(notes)}}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # advice only: never stop a Read
        sys.exit(0)
