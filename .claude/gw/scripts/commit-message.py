#!/usr/bin/env python3
# galivelop-workflow v0.5.0
"""The commit message rules of the commit-msg hook that need more than grep (D11, D12, D15).

  python3 commit-message.py [--root PATH] MSGFILE

Reads the message the way git will keep it (comment lines and what follows the --verbose scissors line are dropped)
and applies, from .claude/gw.json (read through config.py):

  commitFormat "conventional"  the first line is `type(scope)!: text` (scope and ! optional; types feat, fix, docs,
                               style, refactor, perf, test, build, ci, chore, revert). A leading `WIP: ` and the lines
                               git writes itself (`fixup! `, `squash! `, `amend! `, `Revert "`, `Reapply "`, `Merge `) pass.
  commitRefs true              the trailer block (git interpret-trailers --parse) has at least one `Refs:` line, with
                               one or several ids separated by commas (`Refs: D11, D12`; the line may repeat), and each
                               id opens an entry (table row or list item, the `entry` expression of handoff.py) with
                               the shape of `taskId` in one of `refsSources` (empty: `plan` plus `log`). The STAGED
                               version of each file is read, so a commit that adds the id can cite it.
  commitNext true              the trailer block has a non-empty next-step trailer, named after `language`: `Siguiente:` (es)
                               or `Next:` (en; NEXT_TRAILERS). WIP: commits need it too; `fixup! `, `squash! `,
                               `amend! `, `Revert "` and `Reapply "` lines are exempt, and so is a
                               merge/revert/cherry-pick/rebase in progress (merge-branch.sh requires it itself).
                               Escape for a legitimate message without it: GW_NO_NEXT=1 git commit ...
  agentSignatures false        an `Agent:` trailer (the subagent's skill, e.g. `Agent: gw-orchestrate-dealer`) must
                               not name a model or provider: the value is split at anything that is not a letter or digit
                               and a piece fails if it is claude, anthropic, opus, sonnet, haiku, fable, gpt,
                               chatgpt, openai, gemini, llama, mistral, qwen or deepseek, or matches gpt<digit>..., o<digits>
                               or <digits>o (Claudette passes, haiku-writer and 4o do not). Without that, any
                               `Agent:` value passes. Trailers are read with --no-divider (a `---` line is body).

The review-mark commit of reviewed.sh (subject exactly `Revisado: <sha>` or `Reviewed: <sha>`) is exempt from
format and `Refs:`. Format and `Refs:` are not checked while a merge, revert or cherry-pick is being concluded
(MERGE_HEAD, REVERT_HEAD, CHERRY_PICK_HEAD) nor during a rebase; `Agent:` is checked in merges too, not in a rebase
(old messages are replayed).
Exit 0 ok, 1 rejected or failed closed (config unreadable, git failing): each message names what failed and ends with
the command that fixes it. Python 3.8+, stdlib only.
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config as gwconfig  # noqa: E402

TYPES = ("feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert")
CONVENTIONAL = re.compile(rf"(?:{'|'.join(TYPES)})(?:\([^()\s][^()]*\))?!?: \S")
GIT_LINES = ("fixup! ", "squash! ", "amend! ", 'Revert "', 'Reapply "', "Merge ")
# As of 2026-11-02, from the D15 rule in docs/design/D-git.md (models and providers; the list goes stale: extend it).
# An Agent value is split into pieces at anything that is not a letter or digit; a piece in this set, or one that
# matches MODEL_SHAPES, names a model.
MODEL_NAMES = frozenset(("claude", "anthropic", "opus", "sonnet", "haiku", "fable", "gpt", "chatgpt", "openai",
                         "gemini", "llama", "mistral", "qwen", "deepseek"))
MODEL_SHAPES = re.compile(r"gpt\d.*|o\d+|\d+o")
# The next-step trailer per config `language` (the word the templates/<lang>/AGENTS.md use); other languages: English.
NEXT_TRAILERS = {"es": "Siguiente", "en": "Next"}
MERGE_STATES = ("MERGE_HEAD", "REVERT_HEAD", "CHERRY_PICK_HEAD")
# The subject reviewed.sh writes for the review-mark commit (by `language`; SHA-1 or SHA-256 object names): it has no
# task of its own, so format and Refs are not asked of it (the next-step trailer is, and reviewed.sh writes it).
REVIEW_MARK = re.compile(r"(?:Revisado|Reviewed): [0-9a-f]{40}(?:[0-9a-f]{24})?")


class Reject(Exception):
    pass


def git(root, *args):
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        raise Reject(f"cannot run git ({exc}); check that git is installed: git --version")


def git_paths_exist(root, names):
    """{name: whether that path inside .git exists}, with one git call."""
    args = []
    for name in names:
        args += ["--git-path", name]
    r = git(root, "rev-parse", *args)
    lines = r.stdout.splitlines()
    if r.returncode != 0 or len(lines) != len(names):
        raise Reject(f"git rev-parse failed ({r.stderr.strip()[:200]}); check the repository: git status")
    return {n: (Path(l) if Path(l).is_absolute() else Path(root) / l).exists() for n, l in zip(names, lines)}


def clean_message(root, text):
    """The message without comment lines and without the scissors line and what follows it (as git strips it)."""
    r = git(root, "config", "core.commentString")
    if r.returncode != 0:
        r = git(root, "config", "core.commentChar")
    cc = r.stdout.strip() if r.returncode == 0 else ""
    if cc in ("", "auto"):
        cc = "#"
    out = []
    for line in text.splitlines():
        if line.startswith(cc):
            if re.search(r" -+ >8 -+$", line):
                break
            continue
        out.append(line)
    return "\n".join(out).strip("\n")


def trailers(root, message, msgfile):
    """[(key, value)] of the message's trailer block, as git reads it."""
    try:
        r = subprocess.run(["git", "-C", str(root), "interpret-trailers", "--parse", "--no-divider"], input=message + "\n",
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        raise Reject(f"cannot run git ({exc}); check that git is installed: git --version")
    if r.returncode != 0:
        raise Reject(f"git interpret-trailers failed ({r.stderr.strip()[:200]}); check git: git --version")
    found = []
    for line in r.stdout.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            found.append((key.strip(), value.strip()))
    return found


def names_a_model(value):
    return any(t in MODEL_NAMES or MODEL_SHAPES.fullmatch(t) for t in re.split(r"[^a-z0-9]+", value.lower()) if t)


def check_agent(found, msgfile):
    for key, value in found:
        if key.lower() == "agent" and names_a_model(value):
            raise Reject(f"the Agent trailer names a model or provider, which this project forbids "
                         f"(agentSignatures: false in .claude/gw.json): {key}: {value}\n"
                         f"commit-msg: name the skill or role instead (Agent: gw-orchestrate-dealer) and commit "
                         f"again: git commit -e -F {msgfile}")


def check_next(config, message, found, msgfile):
    word = NEXT_TRAILERS.get(config.get("language"), NEXT_TRAILERS["en"])
    subject = next((line for line in message.splitlines() if line.strip()), "")
    rest = subject[5:] if subject.startswith("WIP: ") else subject
    # "Merge " is not exempt here: a real merge is skipped by its MERGE_HEAD, and a plain commit titled "Merge ..." is not one.
    if not subject or rest.startswith(tuple(l for l in GIT_LINES if l != "Merge ")):
        return
    if any(key.lower() == word.lower() and value for key, value in found):
        return
    raise Reject(f"the message has no `{word}:` trailer with the next concrete step (commitNext: true in .claude/gw.json)\n"
                 f"commit-msg: end the message with a paragraph of trailers with a `{word}: <next step>` line "
                 f"and commit again: git commit -e -F {msgfile}; for a message that legitimately has none: "
                 f"GW_NO_NEXT=1 git commit -e -F {msgfile}")


def check_format(message, msgfile):
    subject = next((line for line in message.splitlines() if line.strip()), "")
    if not subject:
        return  # git itself refuses an empty message
    rest = subject[5:] if subject.startswith("WIP: ") else subject
    if rest.startswith(GIT_LINES) or CONVENTIONAL.match(rest):
        return
    raise Reject(f"the first line is not in the conventional form (commitFormat: conventional in .claude/gw.json): "
                 f"{subject!r}\ncommit-msg: write `type(scope)!: text` with type one of {', '.join(TYPES)} "
                 f"(scope and ! optional, a space after the colon) and commit again: git commit -e -F {msgfile}")


def source_files(root, sources):
    """[(path, staged text)] of the files in `sources` (a folder: its tracked .md files), read from the index."""
    found = {}
    for source in sources:
        r = git(root, "ls-files", "-z", "--", source)
        if r.returncode != 0:
            raise Reject(f"git ls-files failed ({r.stderr.strip()[:200]}); check the repository: git status")
        for path in filter(None, r.stdout.split("\0")):
            if path.endswith(".md") or path == source:
                found[path] = None
    for path in sorted(found):
        r = git(root, "show", f":{path}")
        if r.returncode != 0:
            raise Reject(f"cannot read the staged {path} ({r.stderr.strip()[:200]}); stage it again: git add {path}")
        found[path] = r.stdout
    return found


def valid_ids(root, config, id_pattern):
    import handoff
    sources = list(config.get("refsSources") or [])
    if not sources:
        sources = list(config.get("plan") or []) + [config["log"]]
    entry = handoff.entry_regex(f"(?:{id_pattern})")
    ids = set()
    files = source_files(root, sources)
    for text in files.values():
        for line in text.splitlines():
            m = entry.match(line)
            if m:
                ids.add(m.group("id"))
    return ids, sources, sorted(files)


def check_refs(root, config, found, msgfile):
    try:
        import handoff
    except ImportError as exc:
        raise Reject(f"cannot import handoff.py ({exc}); reinstall the workflow scripts: /gw-update")
    pattern = handoff.task_id_pattern(config)
    try:
        re.compile(pattern)
        pattern = gwconfig.non_capturing(pattern)
    except (re.error, gwconfig.ConfigError) as exc:
        raise Reject(f"taskId in .claude/gw.json is not usable ({exc}); fix it: python3 {HERE / 'config.py'} validate")
    given = []
    for key, value in found:
        if key.lower() == "refs":
            given += [t for t in re.split(r"[,\s]+", value) if t]
    edit = f"git commit -e -F {msgfile}"
    if not given:
        raise Reject(f"the message has no Refs trailer (commitRefs: true in .claude/gw.json)\n"
                     f"commit-msg: end the message with a paragraph of trailers, one per line, that has "
                     f"`Refs: <task id>` (`Refs: D11, D12` for several), and commit again: {edit}")
    ids, sources, files = valid_ids(root, config, pattern)
    bad = [t for t in given if not re.fullmatch(pattern, t) or t not in ids]
    if bad:
        where = ", ".join(files) if files else f"nothing tracked in {', '.join(sources)}"
        raise Reject(f"Refs names an id that no entry opens: {', '.join(bad)} (read from the staged {where})\n"
                     f"commit-msg: use an id of a table row or list item there, or add the entry, stage it "
                     f"(git add) and commit again: {edit}")


def run(root, msgfile):
    try:
        config = gwconfig.load(root)
    except gwconfig.ConfigError as exc:
        raise Reject(f"cannot read .claude/gw.json ({exc}); fix it: python3 {HERE / 'config.py'} validate")
    path = Path(msgfile)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise Reject(f"cannot read the commit message file '{msgfile}' ({exc}); commit again: git commit")
    root = config["_root"]
    fmt = config.get("commitFormat", "free") == "conventional"
    refs = bool(config.get("commitRefs", False))
    agent = config.get("agentSignatures", True) is False
    nxt = bool(config.get("commitNext", False)) and os.environ.get("GW_NO_NEXT") != "1"
    if not (fmt or refs or agent or nxt):
        return
    state = git_paths_exist(root, ("rebase-merge", "rebase-apply") + MERGE_STATES)
    if state["rebase-merge"] or state["rebase-apply"]:
        return
    merging = any(state[name] for name in MERGE_STATES)
    if not (agent or not merging):
        return
    message = clean_message(root, text)
    subject = next((line for line in message.splitlines() if line.strip()), "")
    if REVIEW_MARK.fullmatch(subject):
        fmt = refs = False
    if not merging and fmt:
        check_format(message, msgfile)
    found = []
    if agent or (not merging and (refs or nxt)):
        found = trailers(root, message, msgfile)
    if agent:
        check_agent(found, msgfile)
    if not merging and refs:
        check_refs(root, config, found, msgfile)
    if not merging and nxt:
        check_next(config, message, found, msgfile)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="project path (default: see config.py)")
    parser.add_argument("msgfile", help="the commit message file git gives the commit-msg hook")
    args = parser.parse_args(argv)
    try:
        run(args.root, args.msgfile)
    except Reject as exc:
        print(f"commit-msg: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
