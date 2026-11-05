#!/usr/bin/env python3
# galivelop-workflow v0.5.0
"""PreToolUse hook: ask the user before Claude edits the workflow's own configuration.

The files that wire the workflow (.claude/settings.json, .claude/settings.local.json, .claude/gw.json, everything under .githooks/ and under
.claude/gw/scripts/) change only with the user's OK; AGENTS.md says so, and this hook makes the rule checkable. It
never denies: it returns `ask`, so the user decides in the permission prompt.

Output format (https://code.claude.com/docs/en/hooks.md, PreToolUse "ask" decision): a JSON object on stdout, exit 0,

  {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                          "permissionDecisionReason": "..."}}

`permissionDecisionReason` is what the user sees in the prompt. No output at all means "no opinion" (the normal
permission flow goes on).

What it looks at, in the event on stdin (`tool_name`, `tool_input`, `cwd`):

  Edit, Write, MultiEdit      tool_input.file_path (NotebookEdit: notebook_path). Absolute or relative (against the
                              event's `cwd`), with `./`, `..` and symlinks resolved; a path outside the project is
                              none of its business.
  Bash                        tool_input.command, split into simple commands (`;`, `&&`, `||`, `|`, `&`, newlines,
                              `bash -c '...'` and `eval` recursively). It asks when a command names a protected path AND
                              writes to it: a redirection (`>`, `>>`, `>|`) to it, `tee`, `sed -i`, `perl -i`, `cp`,
                              `mv`, `rm`, `install`, `ln`, `chmod`, `chown`, `truncate`, `touch`, `dd`, `rsync`,
                              `find -delete`, `git checkout|restore|rm|mv|clean`. A folder that holds protected files
                              (`.claude`, `.claude/gw`) counts when `rm`/`mv`/`unlink`/`shred`/`rmdir` name it, when
                              it is the destination of `cp`/`mv`/`install`/`ln`/`rsync` (the last argument, or `-t`),
                              and when a `git` write names it; so does `.` (the whole project) for `git checkout -- .`
                              and `git restore .`, which overwrite every protected file with the committed one.
                              Wrappers are looked through with their options and the values of those
                              (`sudo -u me`, `sudo -uroot`, `env -u X`, `nice -n 5`, `timeout -s KILL 5`,
                              `xargs -I{}`), and a redirection before the command (`> f cmd`). A plain read (`cat`,
                              `grep`, `git diff`, `cp .claude/gw.json /tmp/`, `python3 .claude/gw/scripts/x.py`) is
                              allowed: of `cp`/`install`/`ln`/`rsync` only the destination counts as written (the
                              value of an option such as `rsync --exclude .claude` is not a destination), while `mv`
                              also writes its sources, and so does `rsync --remove-source-files`. `dd` writes what
                              `of=` names (`if=` only reads). `git restore --staged` (without `--worktree`),
                              `git rm --cached` and `git clean -n` leave the worktree alone and are allowed. Not seen, on
                              purpose (a hook cannot parse a shell): a path built at run time, and code that opens the
                              file inside `python3 -c`. A `cd` to a literal folder is followed; `rm -r .claude` counts.

Also covered (D33): the same paths inside an agent worktree (`.claude/worktrees/<name>/...`); `find ... -exec|-execdir|
-ok rm|mv|...` on them; `tar -x -C DIR` and `unzip -d DIR` into a protected folder (or from inside one). The file read by
`touch -r`, `touch|chmod|chown|chgrp --reference` is not written.

The git calls that rewrite the working tree without naming a path (`merge`, `pull`, `checkout|switch <branch>`,
`reset --hard|--merge|--keep`, `stash pop|apply`, `rebase`, `cherry-pick`, `revert`, `apply`) ask only when they would
change a protected path: the guard runs `git diff --name-only` (or `git log`, `git status`) from the repository
the call targets (`-C` followed), with a timeout, and names the path. `pull` looks at the upstream as last fetched
(`HEAD...@{u}`; the guard does not fetch). If it cannot tell (a reference that does not exist, `--continue`/`--abort`,
a patch from stdin, `-C` into another repository, `--git-dir`/`--work-tree`/`-c core.worktree`, a git error or timeout)
`git apply` reads the patch itself; no option of the user's reaches the git the guard runs. `stash` and `clean -f`
ask when `git status` shows a protected path they would touch. A `git` alias is expanded one level (`-c alias.X=...` or
the config); `!` aliases and chains ask. It asks, with that as the reason: "the working tree (git ...; cannot tell which files it changes: ...)".

Project root: config.find_root (the script's own repo when it holds .claude/gw.json, else the project the hook runs
in); it does not read or validate the config. Fails closed: stdin it cannot read, an event without the tool name or
the target, or a root it cannot find -> `ask`, with that as the reason. Python 3.8+ standard library only.
"""
import json
import fnmatch
import os
import re
import select
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, HERE)
import config  # noqa: E402

STDIN_WAIT = 3.0
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
TARGET_KEYS = ("file_path", "notebook_path", "path")
EXACT = (".claude/settings.json", ".claude/settings.local.json", ".claude/gw.json")
TREES = (".githooks", ".claude/gw/scripts")
WORKTREE = re.compile(r"\.claude/worktrees/[^/]+/(.+)$")  # an agent's worktree holds its own copy of every protected path
ANCESTORS = (".claude", ".claude/gw")  # removing or moving one takes protected files with it
WRITERS = {"tee", "cp", "mv", "rm", "install", "ln", "chmod", "chown", "chgrp", "truncate", "touch", "dd", "rsync",
           "unlink", "shred", "rmdir", "patch"}
DESTRUCTIVE = {"rm", "mv", "unlink", "shred", "rmdir"}  # these also count when they name an ancestor folder
COPIERS = {"cp", "mv", "install", "ln", "rsync"}  # these also count when their destination is an ancestor folder
READ_SOURCES = {"cp", "install", "ln", "rsync"}  # of these only the destination is written (`mv` removes its sources)
# Options of each copier that take a value in the next word (the value is not the destination: `--exclude .claude`).
COPIER_VALUE = {
    "rsync": {"-e", "-f", "--rsh", "--filter", "--exclude", "--include", "--exclude-from", "--include-from",
              "--files-from", "--log-file", "--chmod", "--rsync-path", "--partial-dir", "--backup-dir", "--suffix",
              "--compare-dest", "--copy-dest", "--link-dest", "--temp-dir", "-T", "--max-size", "--min-size"},
    "cp": {"-S", "--suffix"},
    "mv": {"-S", "--suffix"},
    "ln": {"-S", "--suffix"},
    "install": {"-S", "--suffix", "-m", "--mode", "-o", "--owner", "-g", "--group"},
}
IN_PLACE = {"sed", "gsed", "perl", "ruby"}
GIT_WRITES = {"checkout", "restore", "rm", "mv", "clean"}
GIT_NOT_WRITES = {  # (git subcommand, long flag, short letter): with this flag the call writes no file of the worktree
    ("rm", "--cached", None), ("clean", "--dry-run", "n"),
}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
# Commands that run another one, and the options of each that take a value in the next word (`sudo -u me`, `env -u X`,
# `nice -n 5`, `timeout -s KILL 5`): the same list as PREFIX_OPTIONS in review-before-main.sh, plus `doas`.
WRAPPER_OPTIONS = {
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "nice": {"-n", "--adjustment"},
    "time": {"-f", "--format", "-o", "--output"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "stdbuf": {"-i", "--input", "-o", "--output", "-e", "--error"},
    "sudo": {"-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt", "-C", "-D", "--chdir", "-R", "-r",
             "-t", "-T", "-U"},
    "doas": {"-u", "-C"},
    "exec": {"-a"}, "command": set(), "nohup": set(), "builtin": set(),
}
XARGS_VALUE = {"-I", "-L", "-n", "-P", "-s", "-d", "-E", "-a", "--delimiter", "--max-args", "--max-procs",
               "--arg-file", "--replace", "--max-lines", "--eof", "--max-chars"}
RULE = ("these files change only with the user's OK (the workflow's rule). If the user approves, go ahead; to "
        "regenerate the applied copy from the workflow, run: python3 scripts/apply.py . (in a project, /gw-update)")


def read_event():
    """(event, problem): the hook's JSON object from stdin, or (None, why it cannot be used)."""
    if sys.stdin is None or sys.stdin.isatty():
        return None, "nothing arrived on stdin"
    try:
        ready, _, _ = select.select([sys.stdin], [], [], STDIN_WAIT)
        if not ready:
            return None, "stdin stayed empty"
        text = sys.stdin.read()
    except (OSError, ValueError) as exc:
        return None, f"stdin could not be read ({exc})"
    try:
        data = json.loads(text)
    except ValueError:
        return None, "stdin is not valid JSON"
    if not isinstance(data, dict):
        return None, "stdin is not a JSON object"
    return data, None


def ask(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                             "permissionDecisionReason": reason}}))


def classify(token, base, root):
    """The project-relative, normalised path `token` names and its kind: ('protected' | 'ancestor' | 'root' | None). `base`
    is the folder relative paths are read from; `root` the real project root."""
    if not token or token.startswith("~"):
        return None, None
    token = re.sub(r"^(\$\{CLAUDE_PROJECT_DIR\}|\$CLAUDE_PROJECT_DIR)(?=/|$)", root, token)
    other = re.match(r"^(\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$[A-Za-z_][A-Za-z0-9_]*)/(.+)$", token)
    if other:  # any other variable may or may not be the project: ask only when what follows it is protected
        rel, kind = classify(other.group(2), root, root)
        if kind in ("protected", "ancestor"):
            return f"{token} (a path built from {other.group(1)}, which may be the project)", kind
        return None, None
    try:
        path = os.path.realpath(token if os.path.isabs(token) else os.path.join(base, token))
        rel = os.path.relpath(path, root)
    except (OSError, ValueError):
        return None, None
    if rel == ".." or rel.startswith("../") or rel.startswith(".." + os.sep):
        return None, None  # outside the project
    rel = rel.replace(os.sep, "/")
    low = rel.lower()  # a case-insensitive disk (macOS, Windows) must not be a way round
    inner = WORKTREE.match(low)
    if inner:
        low = inner.group(1)
    if low in EXACT or any(low == t or low.startswith(t + "/") for t in TREES):
        return rel, "protected"
    if low in ANCESTORS:
        return rel, "ancestor"
    if rel == ".":
        return rel, "root"  # the project folder itself: only a pathspec that covers every protected file cares
    return rel, None


def tokenize(command):
    """Shell words of `command`; operators (`;`, `&&`, `>>`, ...) come out as words of their own."""
    text = command.replace("\\\n", " ").replace("\n", " ; ")
    lex = shlex.shlex(text, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        return list(lex)
    except ValueError:  # an unclosed quote: still look at the words, cut crudely
        return [w.strip("'\"") for w in re.split(r"\s+|(?<=[;&|<>])|(?=[;&|<>])", text) if w and w.strip("'\"")]


def is_redirect(word):
    return "<" in word or ">" in word


def is_separator(word):
    return bool(word) and all(c in "();|&" for c in word)


def segments(words):
    out, cur = [], []
    for w in words:
        if is_separator(w):
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(w)
    if cur:
        out.append(cur)
    return out


def is_redirect_operator(word):
    """`>`, `>>`, `>&`, `>|`, `<`, `&>`: a redirection whose target is the next word."""
    return is_redirect(word) and bool(re.fullmatch(r"[0-9]*(&>>?|[<>]+[&|]?)", word))


def fd_before_redirect(words, i):
    """True for the `2` of `2>file`: the file descriptor the shell reads as part of the redirection."""
    return words[i].isdigit() and i + 1 < len(words) and is_redirect(words[i + 1])


def takes_next(opt, takes_value):
    """True when option word `opt` leaves its value to the next word: `-u`, or a group of short flags whose LAST letter
    takes one (`sudo -Eu root`). A value-taking letter that is not last has its value attached (`-uroot`, `-n5`)."""
    if opt in takes_value:
        return True
    if len(opt) > 2 and opt[1] != "-":
        for k, letter in enumerate(opt[1:]):
            if "-" + letter in takes_value:
                return k == len(opt) - 2
    return False


def skip_options(words, i, takes_value):
    """The index after the options at words[i:] (`takes_value` says which ones also consume the next word)."""
    while i < len(words) and words[i].startswith("-") and words[i] != "-":
        opt = words[i]
        i += 2 if takes_next(opt, takes_value) else 1
        if opt == "--":
            break
    return i


def command_word(words):
    """(index, word) of the command a simple command runs: after redirections, variable assignments, wrappers
    (`sudo`, `env`, `timeout`, `xargs`, ...) and the options of each, values included."""
    i = 0
    while i < len(words):
        w = words[i]
        if is_redirect(w):
            i += 2 if is_redirect_operator(w) else 1  # `> file cmd`: the file is not the command
            continue
        if fd_before_redirect(words, i) or re.match(r"[A-Za-z_][A-Za-z0-9_]*=", w):
            i += 1
            continue
        name = os.path.basename(w)
        if name == "xargs":
            i = skip_options(words, i + 1, XARGS_VALUE)
        elif name in WRAPPER_OPTIONS:
            i = skip_options(words, i + 1, WRAPPER_OPTIONS[name])
            if name == "timeout" and i < len(words):
                i += 1  # the duration
        else:
            return i, name
    return None, None


def destination(seg, i, cmd):
    """Index of the word a copier (`cp`, `mv`, `install`, `ln`, `rsync`) writes into: the `-t`/`--target-directory`
    value, else the last word that is not an option, an option's value or a redirection. None when there is no clear one."""
    values = COPIER_VALUE.get(cmd, set())
    last = None
    j = i + 1
    while j < len(seg):
        w = seg[j]
        if (w in ("-t", "--target-directory") or takes_next(w, {"-t"})) and j + 1 < len(seg):
            return j + 1
        if w.startswith("--target-directory="):
            return -j - 1  # the value is inside the word itself (see bash_hits)
        if w.startswith("-") and w != "-":
            j += 2 if takes_next(w, values) else 1  # an option and, maybe, its value
            continue
        if not (is_redirect(w) or fd_before_redirect(seg, j) or is_redirect_operator(seg[j - 1])):
            last = j
        j += 1
    return last


def git_write_call(args, k):
    """False for the `git` calls that name a path but leave the worktree alone: `restore --staged` (index only,
    unless `--worktree`/`-W` too), `rm --cached`, `clean -n`/`--dry-run`. `k` is the index of the subcommand in `args`."""
    sub, rest = args[k], []
    for w in args[k + 1:]:
        if w == "--":
            break
        rest.append(w)
    shorts = "".join(w[1:] for w in rest if re.fullmatch(r"-[A-Za-z]+", w))

    def has(long_flag, letter):
        return long_flag in rest or (letter is not None and letter in shorts)

    if sub == "restore":
        return not has("--staged", "S") or has("--worktree", "W")
    return not any(sub == s and has(flag, letter) for s, flag, letter in GIT_NOT_WRITES)


GIT_TIMEOUT = 10.0
# Options of each subcommand that take a value in the next word (their value is not a commit).
def safe_ref(x):
    """A reference or path that goes to git: never something that git could read as an option."""
    if x.startswith("-") and x != "-":
        raise Unknown(f"`{x}` looks like an option, not a reference")
    return x


TREE_VALUE = {
    "merge": {"-m", "-F", "-s", "-X", "--file", "--strategy", "--strategy-option", "--into-name", "--message"},
    "pull": {"-s", "-X", "--strategy", "--strategy-option", "--upload-pack", "--depth", "--deepen", "--shallow-since",
             "-j", "--jobs", "-o", "--server-option", "--shallow-exclude", "--negotiation-tip"},
    "checkout": {"-b", "-B", "--orphan", "--conflict", "--pathspec-from-file", "-U", "--unified", "--inter-hunk-context"},
    "switch": {"-c", "-C", "--create", "--force-create", "--conflict"},
    "reset": {"--pathspec-from-file"},
    "stash": {"-m", "--message"},
    "rebase": {"-s", "-X", "-x", "-C", "--exec", "--strategy", "--strategy-option", "--onto", "--whitespace"},
    "cherry-pick": {"-m", "--mainline", "-X", "-s", "--strategy", "--strategy-option"},
    "revert": {"-m", "--mainline", "-X", "-s", "--strategy", "--strategy-option"},
    "apply": {"-p", "-C", "--directory", "--include", "--exclude", "--whitespace"},
    "clean": {"-e", "--exclude"},
}
# `git` calls that rewrite the working tree and whose files are not worked out here: the guard asks, with the reason.
TREE_UNKNOWN = {
    "am": "`git am` applies patches from a mailbox, which is not read here",
    "bisect": "`git bisect` checks out the commits it tests",
    "checkout-index": "`git checkout-index` writes files from the index",
}
TREE_VALUE.update({sub: set() for sub in TREE_UNKNOWN})
TREE_VALUE["read-tree"] = {"--prefix", "--index-output", "--exclude-per-directory"}
TREE_SUBCOMMANDS = set(TREE_VALUE)  # `git` calls that rewrite the working tree without naming a path
DIFF = ("diff", "--name-only", "--no-renames", "--no-ext-diff", "-z")
LOG = ("log", "-m", "--name-only", "--no-renames", "--format=", "-z")


class Unknown(Exception):
    """The files a `git` call would change cannot be worked out: the guard asks (it fails closed)."""


GLOBAL_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--super-prefix", "--attr-source"}
BUILTINS = set("""add am annotate apply archive bisect blame branch bundle cat-file check-attr check-ignore checkout
checkout-index cherry cherry-pick clean clone commit commit-tree config count-objects describe diff diff-files diff-index
diff-tree difftool fetch fetch-pack for-each-ref format-patch fsck gc grep hash-object help init log ls-files ls-remote
ls-tree maintenance merge merge-base merge-file merge-tree mergetool mktag mv name-rev notes pack-refs prune pull push
range-diff read-tree rebase reflog remote repack replace request-pull reset restore rev-list rev-parse revert rm
send-email shortlog show show-branch show-ref sparse-checkout stash status submodule switch symbolic-ref tag unpack-file
update-index update-ref var verify-commit verify-tag version whatchanged worktree write-tree""".split())


def git_subcommand(args):
    """Index in `args` of the `git` subcommand: the first word that is not a global option or its value (`-C DIR`,
    `-c k=v`, `--git-dir DIR`, `--work-tree DIR`, ...; the `--x=v` form is one word). None when there is none."""
    n = 0
    while n < len(args):
        w = args[n]
        if not w.startswith("-"):
            return n
        n += 2 if w in GLOBAL_VALUE else 1
    return None


def git_run(cwd, *argv, ok=(0,)):
    """stdout of a read-only `git` run with arguments the guard built from validated references and paths, never from
    the user's options. Returns (code, stdout) when `ok` allows codes other than 0."""
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
                            *argv], cwd=cwd, capture_output=True, text=True, timeout=GIT_TIMEOUT,
                           stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        raise Unknown(f"`git {argv[0]}` took more than {GIT_TIMEOUT:.0f}s")
    except OSError as exc:
        raise Unknown(f"git could not run ({exc})")
    if r.returncode not in ok:
        why = (r.stderr.strip().splitlines() or ["failed"])[-1]
        raise Unknown(f"`git {' '.join(argv[:2])}` failed: {why}")
    return r.stdout if ok == (0,) else (r.returncode, r.stdout)


def git_cwd(pre, base):
    """(folder, aliases) of a `git` call: `base` moved by each `-C DIR` among the words before the subcommand, and the
    `-c alias.X=V` it defines. Raises Unknown when git is pointed somewhere else (`--git-dir`, `--work-tree`,
    `-c core.worktree`)."""
    cwd, aliases, n = base, {}, 0
    while n < len(pre):
        w = pre[n]
        name, sep, attached = w.partition("=")
        value = pre[n + 1] if name in GLOBAL_VALUE and not sep and n + 1 < len(pre) else attached
        step = 2 if name in GLOBAL_VALUE and not sep else 1
        if name in ("--git-dir", "--work-tree"):
            raise Unknown(f"`{name}` points git somewhere else")
        if w == "-C":
            if re.search(r"[$~`*?\[]", value):
                raise Unknown(f"`-C {value}` is a path built at run time")
            cwd = os.path.realpath(value if os.path.isabs(value) else os.path.join(cwd, value))
        elif w == "-c" or name == "--config-env":
            key, _, val = value.partition("=")
            key = key.lower()
            if key.startswith(("core.worktree", "core.gitdir")):
                raise Unknown(f"`{w} {value}` moves the working tree")
            if key.startswith("alias."):
                if name == "--config-env":
                    raise Unknown("an alias defined from the environment cannot be read")
                aliases[key[6:]] = val
        n += step
    return cwd, aliases


def arg_indexes(seg, i):
    """Indexes in `seg` of the arguments of the command at `i`: not redirections, not their targets or descriptors."""
    return [j for j, w in enumerate(seg) if j != i and not is_redirect(w) and not fd_before_redirect(seg, j)
            and not (j > 0 and is_redirect_operator(seg[j - 1]))]


def expand_git_alias(seg, i, base):
    """(seg, problem): `seg` with a `git` alias replaced by what it stands for (one level), or the reason it cannot be
    followed (a `!` shell alias, a chain of aliases, a config it cannot read). A builtin name is never an alias."""
    arg_at = arg_indexes(seg, i)
    args = [seg[j] for j in arg_at]
    k = git_subcommand(args)
    if k is None or args[k] in BUILTINS:
        return seg, None
    try:
        cwd, aliases = git_cwd(args[:k], base)
        name = args[k]
        value = aliases.get(name.lower())
        if value is None:
            code, out = git_run(cwd, "config", "--get", f"alias.{name}", ok=(0, 1))
            value = out.strip() if code == 0 else None
        if value is None:
            return seg, None  # not an alias: an external `git-<name>` command
        if value.startswith("!"):
            raise Unknown(f"the alias `{name}` runs a shell command")
        try:
            words = shlex.split(value)
        except ValueError:
            raise Unknown(f"the alias `{name}` cannot be read")
        new = args[:k] + words + args[k + 1:]
        k2 = git_subcommand(new)
        if k2 is None or new[k2] not in BUILTINS:
            raise Unknown(f"the alias `{name}` expands to another alias or to nothing it can read")
        return seg[:arg_at[k]] + words + seg[arg_at[k] + 1:], None
    except (Unknown, OSError) as exc:
        return seg, f"the working tree (git {args[k]}; cannot tell which files it changes: {exc})"


def git_top(cwd, root):
    top = os.path.realpath(git_run(cwd, "rev-parse", "--show-toplevel").strip())
    if os.path.commonpath([top, root]) not in (top, root):
        raise Unknown(f"{top} is another repository than the project")
    return top


def split_words(rest, valued):
    """(positional words before `--`, whether `--` is there, the options): `valued` options also consume the next word."""
    pos, opts, dd, n = [], [], False, 0
    while n < len(rest):
        w = rest[n]
        if w == "--":
            dd = True
            break
        if w.startswith("-") and w != "-":
            opts.append(w)
            n += 2 if w in valued else 1
            continue
        pos.append(w)
        n += 1
    return pos, dd, opts


def is_commit(cwd, name):
    try:
        git_run(cwd, "rev-parse", "--verify", "-q", name + "^{commit}")
        return True
    except Unknown:
        return False


def tree_specs(sub, rest, cwd):
    """[argv, ...] of the `git` queries that list the files `git <sub> <rest>` would change ([] when it changes none).
    Raises Unknown when the call names nothing to compute from (`merge --abort`, `rebase --continue`)."""
    pos, dd, opts = split_words(rest, TREE_VALUE[sub])
    flags = "".join(w[1:] for w in opts if re.fullmatch(r"-[A-Za-z]+", w))
    force = "--force" in opts or "--discard-changes" in opts or "f" in flags
    if sub == "merge":
        if not pos:
            if "--abort" in opts:
                return [DIFF + ("HEAD", "--")]  # puts the tree back to HEAD
            if "--continue" in opts or "--quit" in opts:
                return []
            raise Unknown("`git merge` names no commit (--abort, --continue, --quit)")
        return [DIFF + (f"HEAD...{safe_ref(x)}", "--") for x in pos]
    if sub == "pull":  # it fetches first: what it merges is not known until then (the remote ref here may be stale)
        raise Unknown("`git pull` merges what it fetches, which is not known beforehand; "
                      "run `git fetch` and then `git merge <upstream>`")
    if sub in TREE_UNKNOWN:
        raise Unknown(TREE_UNKNOWN[sub])
    if sub == "read-tree" and not any(w == "-u" or re.fullmatch(r"-[A-Za-z]*u[A-Za-z]*", w) for w in opts):
        return []  # without -u it changes the index only
    if sub == "read-tree":
        raise Unknown("`git read-tree -u` writes the files of the trees it reads")
    if sub in ("checkout", "switch"):
        if sub == "checkout" and dd:
            return []  # `git checkout <tree-ish> -- <paths>` writes the paths, which the path rules look at
        target = None
        for w in pos:
            if sub == "switch" or w == "-" or not os.path.exists(os.path.join(cwd, w)) or is_commit(cwd, w):
                target = w  # a name that is both a folder here and a branch is the branch
                break
        if target is None:
            return [DIFF + ("HEAD", "--")] if force else []
        return [DIFF + ("@{-1}" if target == "-" else target, "--")]
    if sub == "reset":
        if not any(w in ("--hard", "--merge", "--keep") for w in opts):
            return []
        return [DIFF + (pos[0] if pos else "HEAD", "--")]
    if sub == "stash":
        if not pos or pos[0] in ("push", "save"):  # puts the changed files back to HEAD
            everything = "--all" in opts or "a" in flags
            untracked = everything or "--include-untracked" in opts or "u" in flags
            return [("status", "--porcelain", "-z", "--untracked-files=" + ("all" if untracked else "no"))
                    + (("--ignored",) if everything else ())]
        if pos[0] == "branch":
            raise Unknown("`git stash branch` checks out the commit the stash was made on and applies it")
        if pos[0] not in ("pop", "apply"):
            return []
        ref = safe_ref(pos[1]) if len(pos) > 1 else "0"
        ref = f"stash@{{{ref}}}" if ref.isdigit() else ref
        return [("stash", "show", "--name-only", "--include-untracked", "-z", ref)]  # git 2.32+; older: it asks
    if sub == "rebase":
        onto = [safe_ref(rest[n + 1]) for n, w in enumerate(rest[:-1]) if w == "--onto"] + \
               [safe_ref(w.split("=", 1)[1]) for w in rest if w.startswith("--onto=")]
        if not pos and not onto:
            raise Unknown("`git rebase` names no commit (--continue, --abort, --skip)")
        # the tree of HEAD against the target: also what the rebase drops (`-i`, `--onto`), not only what comes in
        specs = [DIFF + ("HEAD", safe_ref(x), "--") for x in onto + pos[:1]]
        if len(pos) > 1:
            specs.append(DIFF + (safe_ref(pos[1]), "--"))  # `git rebase <upstream> <branch>` checks the branch out
        return specs
    if sub in ("cherry-pick", "revert"):
        if not pos:
            raise Unknown(f"`git {sub}` names no commit (--continue, --abort, --skip, --quit)")
        return [LOG + (() if ".." in x else ("-1",)) + (safe_ref(x), "--") for x in pos]
    if sub == "clean":
        if "--dry-run" in opts or "n" in flags or not ("--force" in opts or "f" in flags):
            return []
        ignored = "x" in flags or "X" in flags
        return [("status", "--porcelain", "-z", "--untracked-files=all", "@untracked") + (("--ignored",) if ignored else ())]
    if any(w in ("--check", "--stat", "--numstat", "--summary") for w in opts) or (
            "--cached" in opts and "--index" not in opts):
        return []  # a dry run, or the index only
    if not pos or "-" in pos:  # apply
        raise Unknown("`git apply` reads its patch from stdin")
    strip, directory = 1, ""
    for n, w in enumerate(rest):
        if w == "-p" and n + 1 < len(rest) and rest[n + 1].isdigit():
            strip = int(rest[n + 1])
        elif re.fullmatch(r"-p\d+", w):
            strip = int(w[2:])
        elif w == "--directory" and n + 1 < len(rest):
            directory = rest[n + 1]
        elif w.startswith("--directory="):
            directory = w.split("=", 1)[1]
    return [("@patch", pos, strip, directory)]


def patch_paths(text, strip, directory):
    """The paths a patch names (`diff --git`, `---`, `+++`, `rename`, `copy`), read here: git is never run on it."""
    names = []

    def add(path, prefixed):
        path = path.split("\t")[0].strip()
        if path == "/dev/null" or not path:
            return
        if path.startswith('"'):
            raise Unknown("the patch has a quoted path it cannot read")
        if prefixed and strip:
            path = "/".join(path.split("/")[strip:])
        names.append(directory.rstrip("/") + "/" + path if directory else path)

    for line in text.splitlines():
        if line.startswith("diff --git "):
            m = re.fullmatch(r"diff --git (\S+) (\S+)", line)
            if not m:
                raise Unknown("the patch has a path with spaces or quotes it cannot read")
            add(m.group(1), True)
            add(m.group(2), True)
        elif line.startswith(("--- ", "+++ ")):
            add(line[4:], True)
        elif line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
            add(line.split(" ", 2)[2], False)
    return names


def status_paths(out, untracked_only=False):
    """Paths in `git status --porcelain -z`: `XY path`, and for a rename or copy the original path after it. Only the
    untracked and ignored ones (`??`, `!!`) when `untracked_only`: that is all `git clean` removes."""
    names, parts, n = [], out.split("\0"), 0
    while n < len(parts):
        entry = parts[n]
        n += 1
        if len(entry) > 3 and entry[2] == " ":
            if not untracked_only or entry[:2] in ("??", "!!"):
                names.append(entry[3:])
            if entry[0] in "RC" and n < len(parts):
                names.append(parts[n])
                n += 1
    return names


def git_tree_write(args, k, base, root):
    """The protected paths (or the reason it cannot tell) of a `git` call that rewrites the working tree without naming
    a path: `merge`, `pull`, `checkout|switch <branch>`, `reset --hard|--merge|--keep`, `stash pop|apply`, `rebase`,
    `cherry-pick`, `revert`, `apply`. It asks `git diff`/`git log` which files the call would change and keeps the
    protected ones; if it cannot tell, it keeps the doubt."""
    sub = args[k]
    if sub not in TREE_SUBCOMMANDS:
        return []
    try:
        cwd, _ = git_cwd(args[:k], base)
        specs = tree_specs(sub, args[k + 1:], cwd)
        if not specs:
            return []
        top = git_top(cwd, root)
        found = []
        for argv in specs:
            if argv[0] == "@patch":
                if cwd != top:
                    raise Unknown("`git apply` runs below the repository top")
                names = []
                for patch in argv[1]:
                    try:
                        with open(os.path.join(cwd, patch), "rb") as handle:
                            data = handle.read(8_000_001)
                    except OSError as exc:
                        raise Unknown(f"the patch {patch} cannot be read ({exc.strerror})")
                    if len(data) > 8_000_000:
                        raise Unknown(f"the patch {patch} is too big to read")
                    names += patch_paths(data.decode("utf-8", "replace"), argv[2], argv[3])
            elif argv[0] == "status":
                only = "@untracked" in argv
                names = status_paths(git_run(top, *[w for w in argv if w != "@untracked"]), only)
            else:
                names = [x for x in git_run(top, *argv).split("\0") if x]
            for name in names:
                rel, kind = classify(os.path.join(top, name), top, root)
                if kind in ("protected", "ancestor") and rel not in found and (kind == "protected" or argv[0] == "status"):
                    found.append(rel)
        return found
    except (Unknown, ValueError, OSError) as exc:
        return [f"the working tree (git {' '.join(args[k:k + 3])}; cannot tell which files it changes: {exc})"]


def extract_hits(cmd, args, base, root):
    """Protected folders a `tar` extraction (`-C DIR`) or `unzip -d DIR` writes into (the cwd when neither is given)."""
    if cmd == "tar":
        old = next((w for w in args if not w.startswith("-")), "")
        long_ok = any(w in ("--extract", "--get") for w in args)
        short_ok = any(re.fullmatch(r"-[A-Za-z]*x[A-Za-z]*", w) for w in args) or (
            args and args[0] == old and "x" in old and not old.startswith("-"))
        if not (long_ok or short_ok):
            return []
        targets = []
        for n, w in enumerate(args):
            if w in ("-C", "--directory") and n + 1 < len(args):
                targets.append(args[n + 1])
            elif w.startswith("--directory="):
                targets.append(w.split("=", 1)[1])
            elif w.startswith("-C") and not w.startswith("--") and len(w) > 2:
                targets.append(w[2:])
    else:  # unzip
        if any(re.fullmatch(r"-[A-Za-z]*[lptvZ][A-Za-z]*", w) and "d" not in w[1:] for w in args):
            return []  # list, pipe, test: nothing is written
        targets = [args[n + 1] for n, w in enumerate(args) if w == "-d" and n + 1 < len(args)]
        targets += [w[2:] for w in args if w.startswith("-d") and len(w) > 2]
    hits = []
    for t in targets or ["."]:
        rel, kind = classify(t, base, root)
        if kind in ("protected", "ancestor"):
            hits.append(rel)
    return hits


def in_place_flag(words):
    return any(w == "--in-place" or w.startswith("--in-place=") or re.match(r"-[A-Za-z]*i", w) and not w.startswith("--")
               for w in words)


GIT_ENV = r"\bGIT_(DIR|WORK_TREE|INDEX_FILE|COMMON_DIR|CONFIG\w*)="


FIND_TESTS = {"-name", "-iname"}  # the only tests a filtered `find` may use to be read here
FIND_HARMLESS = {"-type", "-maxdepth", "-mindepth", "-print", "-print0", "-delete", "-depth", "-xdev", "-mount"}


def find_may_reach(args, root):
    """Whether a writing `find` started at the project folder can touch a protected file: True unless its only tests
    are -name/-iname patterns (and harmless options) that match no protected file name now on disk."""
    patterns, n = [], 0
    while n < len(args):
        w = args[n]
        if w in FIND_TESTS and n + 1 < len(args):
            patterns.append((args[n + 1], w == "-iname"))
            n += 2
            continue
        if w in ("-type", "-maxdepth", "-mindepth") and n + 1 < len(args):
            n += 2
            continue
        if w.startswith("-") and w not in FIND_HARMLESS:
            return True  # -o, -not, -path, -regex, -exec...: not read here
        if w in ("!", "(", ")", ","):
            return True
        n += 1  # a start folder
    if not patterns:
        return True
    names = {os.path.basename(t) for t in EXACT}
    for tree in TREES:
        for _, dirs, files in os.walk(os.path.join(root, tree)):
            names.update(files)
            names.update(dirs)
    for pattern, fold in patterns:
        for name in names:
            if fnmatch.fnmatchcase(name.lower(), pattern.lower()) if fold else fnmatch.fnmatchcase(name, pattern):
                return True
    return False


def bash_hits(command, base, root, depth=0, redirected=False):
    """[rel, ...]: the protected paths `command` writes to."""
    hits = []
    redirected = redirected or bool(re.search(GIT_ENV, command))  # set anywhere before: it reaches every git below
    for seg in segments(tokenize(command)):
        i, cmd = command_word(seg)
        problem = None
        if cmd == "git":
            seg, problem = expand_git_alias(seg, i, base)
            sub = next((w for w in seg[i + 1:] if w in TREE_SUBCOMMANDS), None)
            if redirected and sub:
                problem = problem or (f"the working tree (git {sub}; cannot tell which files it changes: GIT_DIR, "
                                      "GIT_WORK_TREE, GIT_INDEX_FILE, GIT_CONFIG* or GIT_COMMON_DIR is set in this command)")
            if re.search(GIT_ENV, " ".join(seg[:i])):
                problem = "the working tree (git; cannot tell which files it changes: GIT_DIR, GIT_WORK_TREE or GIT_CONFIG_* points git somewhere else)"
        if problem:
            hits.append(problem)
        arg_at = arg_indexes(seg, i)  # `2>/dev/null` is no argument
        args = [seg[j] for j in arg_at]
        git_sub = None  # index in `seg` of the `git` subcommand
        if cmd in ("cd", "pushd"):  # later commands read their relative paths from there
            target = next((w for w in args if not w.startswith("-")), None)
            if target and not re.search(r"[$~`*?\[]", target):
                base = os.path.realpath(target if os.path.isabs(target) else os.path.join(base, target))
            continue
        if cmd in SHELLS | {"eval"} and depth < 3:
            for j, w in enumerate(seg):
                if j > (i or 0) and (cmd == "eval" or seg[j - 1] == "-c" or re.match(r"-[a-z]*c$", seg[j - 1])):
                    hits += bash_hits(w, base, root, depth + 1, redirected)
        dest = destination(seg, i, cmd) if cmd in COPIERS and i is not None else None
        if dest is not None and dest < 0:  # `--target-directory=X`
            rel, kind = classify(seg[-dest - 1].split("=", 1)[1], base, root)
            dest = None
            if kind in ("protected", "ancestor"):
                hits.append(rel)
        writes = git_write = find_write = False
        seg_base = base  # a `git -C DIR` reads its paths from DIR
        git_sub = -1
        if cmd in WRITERS:
            writes = True
        elif cmd in IN_PLACE and in_place_flag(args):
            writes = True
        elif cmd == "git":
            k = git_subcommand(args)
            writes = git_write = k is not None and args[k] in GIT_WRITES and git_write_call(args, k)
            if k is not None:
                git_sub = arg_at[k]
                try:
                    seg_base = git_cwd(args[:k], base)[0]
                except Unknown:
                    pass
        elif cmd == "find":
            writes = "-delete" in args or any(
                w in ("-exec", "-execdir", "-ok", "-okdir") and n + 1 < len(args)
                and (os.path.basename(args[n + 1]) in WRITERS or os.path.basename(args[n + 1]) in IN_PLACE | {"git"})
                for n, w in enumerate(args))
            find_write = writes  # its start folder counts even when it only holds protected files (`find .claude -delete`)
        elif cmd in ("tar", "unzip"):
            hits += extract_hits(cmd, args, base, root)
        tree = []
        if cmd == "git":
            k = git_subcommand(args)
            tree = git_tree_write(args, k, base, root) if k is not None else []
        reference = set()  # the file `touch -r`, `chmod --reference` and `chown --reference` read is not written
        for j, w in enumerate(seg):
            if cmd == "touch" and takes_next(w, {"-r", "--reference", "-d", "--date", "-t"}) and j + 1 < len(seg):
                reference.add(j + 1)
            elif cmd in ("chmod", "chown", "chgrp") and w == "--reference" and j + 1 < len(seg):
                reference.add(j + 1)
        removes_sources = cmd == "rsync" and any(w.startswith("--remove-source") for w in args)
        for j, w in enumerate(seg):
            if is_redirect(w) or j == i or j in reference or fd_before_redirect(seg, j):
                continue
            if cmd == "git" and (j <= git_sub or w.startswith("-")):
                continue  # the global options with their values and the subcommand are not paths the call writes
            if cmd == "dd" and w.startswith("of="):
                w = w[3:]  # `dd of=FILE` writes FILE; `if=FILE` only reads it
            rel, kind = classify(w, seg_base if cmd == "git" else base, root)
            if kind is None:
                continue
            to_file = j > 0 and ">" in seg[j - 1]  # `>`, `>>`, `>|`, `&>`: the word after it is written
            written = writes and (cmd not in READ_SOURCES or j == dest or removes_sources)  # a copy only reads its sources
            if kind == "protected" and (to_file or written):
                hits.append(rel)
            elif kind == "ancestor" and (to_file or cmd in DESTRUCTIVE or j == dest or git_write or find_write):
                hits.append(rel)
            elif kind == "root" and (git_write or (find_write and find_may_reach(args, root))):  # `git checkout -- .`, `git restore .`: the pathspec covers it all
                hits.append(rel)
        hits += tree
    return hits


def decide(event, root):
    """The reason to ask, or None to say nothing."""
    tool = event.get("tool_name")
    tool_input = event.get("tool_input")
    if not isinstance(tool, str) or not tool:
        return "the hook event has no tool_name, so config-guard.py cannot tell what is about to run"
    if not isinstance(tool_input, dict):
        return f"the {tool} call has no tool_input, so config-guard.py cannot tell what it touches"
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) and os.path.isabs(event.get("cwd", "")) else root
    base = os.path.realpath(cwd)
    if tool == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str):
            return "the Bash call has no command string, so config-guard.py cannot tell what it writes"
        hits = bash_hits(command, base, root)
        if hits:
            return f"this command writes to {hits[0]}: {RULE}"
        return None
    if tool in EDIT_TOOLS:
        target = next((tool_input[k] for k in TARGET_KEYS if isinstance(tool_input.get(k), str) and tool_input[k]), None)
        if target is None:
            return f"the {tool} call names no file_path, so config-guard.py cannot tell which file it edits"
        rel, kind = classify(target, base, root)
        if kind == "protected":
            return f"{tool} would change {rel}: {RULE}"
    return None


def main():
    event, problem = read_event()
    if event is None:
        ask(f"config-guard.py could not use the hook event ({problem}), so it cannot tell whether the workflow's "
            f"configuration is being edited; confirm the call is safe")
        return 0
    try:
        root = os.path.realpath(str(config.find_root()))
    except config.ConfigError as exc:
        ask(f"config-guard.py cannot find the project root ({str(exc).strip()}), so it cannot tell whether the "
            f"workflow's configuration is being edited; confirm the call is safe")
        return 0
    reason = decide(event, root)
    if reason:
        ask(reason)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # fail closed: a guard that crashed must not look like a green light
        ask(f"config-guard.py failed ({type(exc).__name__}: {exc}), so it cannot tell whether the workflow's "
            f"configuration is being edited; confirm the call is safe")
        sys.exit(0)
