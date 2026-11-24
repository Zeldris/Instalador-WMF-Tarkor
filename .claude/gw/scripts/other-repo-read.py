#!/usr/bin/env python3
# galivelop-workflow v0.9.0
"""PreToolUse hook on `Read`, `Grep`, `Glob` and `Bash` (E74): warn when the MAIN session reads a path that is outside
the project and inside another git repository. The rule is that another repo is read through a subagent that returns
a summary with paths (skill gw-orchestrate-dealer), not in the main context; this hook makes it a mechanical notice.
It never blocks: it adds `additionalContext` to the call; with nothing to say it prints nothing.

The main session is an event without `agent_id` (Claude Code adds it inside a subagent, which is what the rule asks
for, so a subagent is never warned). Paths: `file_path` of Read, `path` of Grep and Glob; for Bash, every word of the
command (split like a shell, operators apart) that resolves to an existing path, which includes the value of `git -C`
and of `cd`. A relative path resolves against the event's `cwd`. A path is "another repo" when its real path is not
under the project root and one of its ancestors (or itself) has a `.git`, folder or file (worktrees, submodules).
One warning per call, with every path and the root of its repo, the rule and how to turn it off: `otherRepoReadWarn`
(boolean, default true) in .claude/gw.json; false = no warning.

Output format (https://code.claude.com/docs/en/hooks.md, PreToolUse): a JSON object on stdout, exit 0,

  {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "..."}}

Fails open, because it only advises: stdin it cannot read, a tool it does not watch, a command it cannot split or a
config it cannot read (the default, true, applies) print nothing (or, for the config, warn) and exit 0. The project
root is config.find_root (the script's own repo, never the current directory first). Python 3.8+ standard library
only.
"""
import json
import os
import re
import select
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, HERE)
import config  # noqa: E402

KEY = "otherRepoReadWarn"
TOOLS = ("Read", "Grep", "Glob", "Bash")


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


def enabled(root):
    """The `otherRepoReadWarn` key: the schema default (true) when the config or the value cannot be read."""
    try:
        value = config.load(root).get(KEY)
    except Exception:  # advice only: any problem with the config means the default
        value = None
    if isinstance(value, bool):
        return value
    return config._schema()["properties"][KEY]["default"]


def resolve(path, cwd):
    path = os.path.expanduser(path)
    return os.path.realpath(path if os.path.isabs(path) else os.path.join(cwd, path))


def repo_root(real):
    """The nearest ancestor of `real` (itself included) that holds a `.git`, folder or file; None when there is none."""
    here = real
    while True:
        if os.path.lexists(os.path.join(here, ".git")):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent


def inside(real, root):
    return real == root or real.startswith(root.rstrip(os.sep) + os.sep)


def words(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return list(lexer)


def fixed_part(text):
    """The folder part of `text` before its first wildcard (`*?[{`); `text` itself with no wildcard."""
    cuts = [i for i in (text.find(c) for c in "*?[{") if i >= 0]
    if not cuts:
        return text
    head = text[:min(cuts)]
    return head.rsplit("/", 1)[0] if "/" in head else ""


def word_paths(word):
    """The paths a Bash word may name: the word without a glued short option (`-C/x`), and its part before a wildcard."""
    if re.match(r"^-[A-Za-z][/~]", word):
        word = word[2:]
    out = [word]
    cut = fixed_part(word)
    if cut and cut != word:
        out.append(cut)
    return out


def candidates(event, cwd):
    """The paths the call reads, as (path, must_exist) pairs."""
    tool, tool_input = event["tool_name"], event["tool_input"]
    if tool == "Read":
        value = tool_input.get("file_path")
    elif tool in ("Grep", "Glob"):
        value = tool_input.get("path")
        found = [(value, False)] if isinstance(value, str) and value else []
        text = tool_input.get("pattern" if tool == "Glob" else "glob")
        if isinstance(text, str) and (os.path.isabs(text) or text.startswith("~")):
            found.append((fixed_part(text) or "/", False))
        if not found or not value:
            found.append((cwd, True))
        return found
    else:
        command = tool_input.get("command")
        if not isinstance(command, str) or not command:
            return []
        try:
            return [(p, True) for w in words(command) for p in word_paths(w)] + [(cwd, True)]
        except ValueError:
            return []
    return [(value, False)] if isinstance(value, str) and value else []


def same_project(repo, root):
    """True when `repo` is a checkout (a linked worktree) of the project's own repository, as config.find_root compares."""
    mine, theirs = config.git_common_dir(root), config.git_common_dir(repo)
    return mine is not None and theirs is not None and os.path.realpath(str(mine)) == os.path.realpath(str(theirs))


def other_repos(event, root, cwd):
    """[(real path, repo root)] of the paths outside `root` and inside another repo, without repeats."""
    found = []
    for path, must_exist in candidates(event, cwd):
        for text in (path, path.split("=", 1)[1] if path.startswith("--") and "=" in path else None):
            if not text:
                continue
            real = resolve(text, cwd)
            if inside(real, root) or (must_exist and not os.path.exists(real)):
                continue
            repo = repo_root(real)
            if repo and same_project(repo, root):
                continue
            if repo and not any(real == r for r, _ in found):
                found.append((real, repo))
    return found


def note(found):
    lines = ["Reading another repository from the main session pulls its content into this context. The rule: "
             "another repo is read through a subagent that returns a summary with paths (skill "
             "gw-orchestrate-dealer), not here."]
    lines += [f"  {real}  (repo root: {repo})" for real, repo in found]
    lines.append(f"Turn this notice off with \"{KEY}\": false in .claude/gw.json.")
    return "\n".join(lines)


def main():
    event = read_event()
    if not event or event.get("tool_name") not in TOOLS or event.get("agent_id"):
        return 0
    if not isinstance(event.get("tool_input"), dict):
        return 0
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) and event.get("cwd") else os.getcwd()
    try:
        root = os.path.realpath(str(config.find_root()))
    except Exception:
        return 0
    found = other_repos(event, root, cwd)
    if not found or not enabled(root):
        return 0
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": note(found)}}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # advice only: never stop a call
        sys.exit(0)
