#!/usr/bin/env python3
# galivelop-workflow v0.6.0
"""PreToolUse hook: with `agentSignatures: false`, block the text an agent publishes on GitHub when it carries a signature (D21).

The commit-msg hook only covers commit messages; this covers the title and body of what goes to GitHub:

  - the GitHub MCP tools of any server whose name has `github` in it (matcher in the settings and github_tool() agree):
    create_pull_request, update_pull_request, merge_pull_request, enable_pr_auto_merge, add_issue_comment,
    update_issue_comment, issue_write, add_reply_to_pull_request_comment, add_comment_to_pending_review,
    pull_request_review_write, push_files and create_or_update_file. Scanned fields: title, body, message (a commit
    message, which commit-msg never sees), commit_title, commit_message, commitHeadline, commitBody; file contents are not;
  - Bash commands `gh pr create|edit|comment|review|merge`, `gh issue create|comment|edit`, `gh release create|edit` and
    `gh api`: the values of --title/-t, --subject, --body/-b, --notes/-n (`--opt value`, `--opt=value` and `-bTEXT`),
    the file of --body-file/-F/--notes-file, and for `gh api` the value of -f/-F/--field/--raw-field key=value (`@file`
    is read). A file `-` is stdin: the whole command (heredoc included) is scanned instead. A command that cannot be
    split into words is scanned whole.

Signatures, as in the commit-msg hook (case-insensitive) and only at the start of a line, column 0: a `Co-Authored-By:`
with noreply@anthropic.com or naming Claude Code/Opus/Sonnet/Haiku/Fable, a `Claude-Session:` line, a line that starts
(after any emoji) with "Generated with/by [Claude Code", and a line that starts with a claude.ai/code/session link;
plus the regexes of `agentSignaturePatterns`, which only add to these (a project cannot remove a built-in one).
Lines inside fenced code blocks (``` or ~~~) and indented lines are quotes, not signatures, and pass.

Without `agentSignatures: false` in .claude/gw.json (absent or true) it does nothing. Output: nothing and exit 0 to
let the tool run; exit 2 with the reason on stderr (in English, ending with the fix) to block it. A tool that is not
one of the above is never blocked, whatever its input. Fails closed where it cannot know: stdin that is not a JSON
object, or an unreadable config or --body-file on an affected call, block with the reason and the fix. The project root
is found by config.find_root (the script's own repo, never the current directory first). Python 3.8+, stdlib only.
"""
import json
import os
import re
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
sys.path.insert(0, HERE)
import config  # noqa: E402

GITHUB_TOOLS = frozenset(("create_pull_request", "update_pull_request", "merge_pull_request", "enable_pr_auto_merge",
                          "add_issue_comment", "update_issue_comment", "issue_write",
                          "add_reply_to_pull_request_comment", "add_comment_to_pending_review",
                          "pull_request_review_write", "push_files", "create_or_update_file"))
TEXT_FIELDS = ("title", "body", "message", "commit_title", "commit_message", "commitHeadline", "commitBody")
GH_COMMAND = re.compile(r"(?:^|[\s;&|(`{])gh\s+(?:pr\s+(?:create|edit|comment|review|merge)"
                        r"|issue\s+(?:create|comment|edit)|release\s+(?:create|edit)|api)\b")
TEXT_OPTIONS = frozenset(("--title", "-t", "--subject", "--body", "-b", "--notes", "-n"))
FILE_OPTIONS = frozenset(("--body-file", "--notes-file", "-F"))  # -F is also gh api's field: see gh_texts
FIELD_OPTIONS = frozenset(("-f", "-F", "--field", "--raw-field"))
SHORT_OPTIONS = ("-t", "-b", "-n", "-F", "-f")  # may carry the value pasted: -bTEXT
# Mirrors templates/githooks/commit-msg (grep -iE there, re.I | re.M here), column 0 only.
SIGNATURES = tuple(re.compile(p, re.I | re.M) for p in (
    r"^co-authored-by:.*noreply@anthropic\.com",
    r"^co-authored-by:[ \t]*claude (code|opus|sonnet|haiku|fable)",
    r"^claude-session:",
    r"^(?:[^\w\s]+[ \t]*)?generated (with|by) \[?claude code",
    r"^<?https?://claude\.ai/code/session",
))
FENCE = re.compile(r"^[ \t]*(```|~~~)")
STDIN_LIMIT = 8 * 1024 * 1024


class Block(Exception):
    pass


def without_fences(text):
    """`text` without the lines of fenced code blocks (the fence lines included)."""
    out, inside = [], False
    for line in text.split("\n"):
        if FENCE.match(line):
            inside = not inside
        elif not inside:
            out.append(line)
    return "\n".join(out)


def extra_patterns(conf):
    """The compiled agentSignaturePatterns of the config. They only ADD to SIGNATURES; an entry that is not a valid
    regex blocks (fail closed) instead of being skipped."""
    given = conf.get("agentSignaturePatterns")
    out = []
    for item in given if isinstance(given, list) else []:
        try:
            out.append(re.compile(item, re.I | re.M))
        except (re.error, TypeError) as exc:
            raise Block(f"agentSignaturePatterns in .claude/gw.json has an entry that is not a valid regex ({item!r}: {exc}), "
                        f"so signatures cannot be checked; fix it: python3 {os.path.join(HERE, 'config.py')} validate")
    return tuple(out)


def find_signature(text, extra=()):
    """The first line of `text` that carries a signature at column 0 outside code blocks, or None. `extra` are the
    patterns the project adds to the built-in ones."""
    text = without_fences(text)
    for pattern in SIGNATURES + tuple(extra):
        m = pattern.search(text)
        if m:
            return text[m.start():].strip().split("\n", 1)[0].strip()[:200]
    return None


def github_tool(name):
    """The bare tool name when `name` is one of the GitHub MCP tools that publish text, else None."""
    if not (name.startswith("mcp__") and "github" in name.split("__")[1]):
        return None
    bare = name.rsplit("__", 1)[-1]
    return bare if bare in GITHUB_TOOLS else None


def read_file(path, cwd):
    full = path if os.path.isabs(path) else os.path.join(cwd, path)
    try:
        with open(full, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError as exc:
        raise Block(f"cannot read the file {path} given to gh ({exc.strerror or exc}), so its signatures cannot be checked; "
                    f"write the body to an existing file, or pass it with --body, and run the command again")


def gh_texts(command, cwd):
    """[(where, text)] to scan in a Bash command that publishes with gh; the whole command when it cannot be split
    or when a body comes from stdin (`--body-file -`, heredoc included)."""
    if not GH_COMMAND.search(command):
        return []
    try:
        words = shlex.split(command)
    except ValueError:
        return [("the command", command)]
    texts = []
    for i, word in enumerate(words):
        if not word.startswith("-") or word == "-":
            continue
        option, value = word, None
        if word.startswith("--") and "=" in word:
            option, value = word.split("=", 1)
        elif not word.startswith("--") and len(word) > 2 and word[:2] in SHORT_OPTIONS:
            option, value = word[:2], word[2:]
        if option not in TEXT_OPTIONS | FILE_OPTIONS | FIELD_OPTIONS:
            continue
        if value is None:
            value = words[i + 1] if i + 1 < len(words) else ""
        if option in FIELD_OPTIONS and "=" in value:  # gh api key=value; -F/--field read @file
            key, _, value = value.partition("=")
            if value.startswith("@") and option in ("-F", "--field"):
                texts.append((f"{option} {key}", None if value == "@-" else read_file(value[1:], cwd)))
            else:
                texts.append((f"{option} {key}", value))
        elif option in FILE_OPTIONS:
            texts.append((option, None if value == "-" else read_file(value, cwd)))
        elif option in TEXT_OPTIONS:
            texts.append((option, value))
    if any(t is None for _, t in texts):  # stdin: the body is in the command (heredoc) or in a pipe we cannot see
        texts = [(w, t) for w, t in texts if t is not None] + [("command (its body comes from stdin)", command)]
    return texts


def texts_of(event):
    """[(where, text)] of what the tool call would publish; [] for a tool that is not affected."""
    name = event.get("tool_name")
    if not isinstance(name, str):
        return []
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    if name == "Bash":
        command = tool_input.get("command")
        cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else os.getcwd()
        return gh_texts(command, cwd) if isinstance(command, str) else []
    if github_tool(name) is None:
        return []
    return [(field, tool_input[field]) for field in TEXT_FIELDS if isinstance(tool_input.get(field), str)]


def decide(event):
    texts = texts_of(event)
    if not texts:
        return
    try:
        conf = config.load(config.find_root())
    except config.ConfigError as exc:
        raise Block(f"cannot read .claude/gw.json ({exc}), so agentSignatures cannot be checked; fix it: "
                    f"python3 {os.path.join(HERE, 'config.py')} validate")
    if conf.get("agentSignatures", True) is not False:
        return
    extra = extra_patterns(conf)
    for where, text in texts:
        line = find_signature(text, extra)
        if line:
            raise Block(f"the {where} carries an agent signature, which this project forbids "
                        f"(agentSignatures: false in .claude/gw.json): {line}\n"
                        f"Remove that line (the footer or link of the session) from the text and run the call again; "
                        f"if the project does accept signatures: set \"agentSignatures\": true in .claude/gw.json")


def main():
    try:
        raw = sys.stdin.read(STDIN_LIMIT) if sys.stdin is not None and not sys.stdin.isatty() else ""
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError("not an object")
    except (OSError, ValueError) as exc:
        print(f"agent-signatures: the hook event on stdin cannot be read ({exc}), so the tool call is blocked; "
              f"run the call again, and if it keeps failing check the hook: python3 {os.path.abspath(__file__)} < event.json",
              file=sys.stderr)
        return 2
    try:
        decide(event)
    except Block as exc:
        print(f"agent-signatures: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
