#!/usr/bin/env python3
# galivelop-workflow v0.9.0
"""The commit message rules of the commit-msg hook that need more than grep (D11, D12, D15).

  python3 commit-message.py [--root PATH] MSGFILE

Reads the message the way git will keep it (comment lines and what follows the --verbose scissors line are dropped)
and applies, from .claude/gw.json (read through config.py):

  commitFormat "conventional"  the first line is `type(scope)!: text` (scope and ! optional; types feat, fix, hotfix,
                               docs, style, refactor, perf, test, build, ci, chore, revert, or the commitTypes list).
                               A leading `WIP: ` (commitWipPrefix; "" = none) and the lines
                               git writes itself (`fixup! `, `squash! `, `amend! `, `Revert "`, `Reapply "`, `Merge `) pass.
  commitRefs true              the trailer block (git interpret-trailers --parse) has at least one `Refs:` line, with
                               one or several ids separated by commas (`Refs: D11, D12`; the line may repeat), and each
                               id opens an entry (table row or list item, the `entry` expression of handoff.py) with
                               the shape of `taskId` in one of `refsSources` (empty: `plan` plus `log`). The STAGED
                               version of each file is read, so a commit that adds the id can cite it.
  commitNext true              the trailer block has a non-empty next-step trailer, named after `languages.docs.primary`: `Siguiente:` (es)
                               or `Next:` (en; NEXT_TRAILERS). WIP: commits need it too; `fixup! `, `squash! `,
                               `amend! `, `Revert "` and `Reapply "` lines are exempt, and so is a
                               merge/revert/cherry-pick/rebase in progress (merge-branch.sh requires it itself).
                               With commitRefs or commitNext, a `Findings:` or `Retries:` line outside that block is refused
                               (D97: change-size.py and metrics.py read only the last paragraph).
                               Escape for a legitimate message without it: GW_NO_NEXT=1 git commit ...
  agentSignatures false        an `Agent:` trailer (the subagent's skill, e.g. `Agent: gw-orchestrate-dealer`) must
                               not name a model or provider: the value is split at anything that is not a letter or digit
                               and a piece fails if it is claude, anthropic, opus, sonnet, haiku, fable, gpt,
                               chatgpt, openai, gemini, llama, mistral, qwen or deepseek, or matches gpt<digit>..., o<digits>
                               or <digits>o, plus the pieces of agentModelNames and the regexes of agentModelShapes, which only add to
                               these (Claudette passes, haiku-writer and 4o do not). Without that, any
                               `Agent:` value passes. Trailers are read with --no-divider (a `---` line is body).

  taskRecord.enabled true      (C11) a commit whose type is in taskRecord.requiredFor (feat, fix, hotfix) and that changes code
                               (what `is-code.sh --list` calls code, on the staged files; the files under taskRecord.path
                               do not count) needs, for AT LEAST ONE id of its `Refs:` (the others are context), a contract
                               `<path>/<id>.md` that exists (in the index, which holds HEAD's too, so it need not be edited)
                               with the headings of taskRecord.sections, and a new file `<path>/<id>/*.md` ADDED by the
                               commit (a decision log entry: header with the id and non-empty logSections; form only,
                               task.py); every entry the commit adds must be well formed. Exempt: other types, WIP:, merges, rebases and the review-mark commit.
                               The commit of an entry is resolved on reading (task.py resolve), not written by a hook.

On an exploration branch (C12: the current branch starts with the `spikeBranch` prefix, default `spike/`; "" = off)
commitRefs and taskRecord are not asked; format, agent signatures and the next-step trailer still are (a spike is
relayed like any other work). The hook adds a `Spike: <branch>` trailer at the start of the trailer block when the
message has none, also in a merge, so the commit stays recognisable on any branch it reaches (config.py spike-check).

A warning, never a refusal (E60): with commitRefs or commitNext, a message that names review fixes (a word or phrase
of metrics.quality.findingsWords, whole words, any case; [] = off) without a `Findings:` trailer gets one line on
stderr asking for it (metrics.py quality and the block review of change-size.py count from that trailer).

A warning, never a refusal (D108): when the commit closes a phase or version and the session passed its compaction
budget, one line on stderr asks for /clear (a long context is almost all the spend; the log is enough to resume).
"Closes a phase or version", in a commit that is not WIP: (a) in the first `roadmapFiles` file, a `## ` section whose
heading has a backticked version (`## `0.6` ...`, its `###` included) has every task row (a table row whose status,
the last cell, starts with its `done` word or an `open` one) with a status that starts with `done` in the STAGED
version, and not at HEAD; or (b) the value of the log's state table row «Fase en curso» / «Phase in progress» /
«Current phase» differs between HEAD and the staged log; or (c, D176, `clearOnTaskClose`, default true) a task row of
that file is open at HEAD and done in the staged version. Closing a single row counts only through (c). The budget and the
compactions are recover.py's (budget_overrun: `Compaction budget: N` in the log, the newest transcript of the repo).
Any missing piece (roadmap, recover.py, transcript, budget line) means no warning.

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

# The types and the WIP prefix are the commitTypes and commitWipPrefix keys (defaults: these); read in types_of, wip_of.
TYPES = ("feat", "fix", "hotfix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert")
WIP_PREFIX = "WIP: "
GIT_LINES = ("fixup! ", "squash! ", "amend! ", 'Revert "', 'Reapply "', "Merge ")
# As of 2026-11-02, from the D15 rule in docs/design/D-git.md (models and providers; the list goes stale: extend it).
# An Agent value is split into pieces at anything that is not a letter or digit; a piece in this set, or one that
# matches MODEL_SHAPES, names a model.
MODEL_NAMES = frozenset(("claude", "anthropic", "opus", "sonnet", "haiku", "fable", "gpt", "chatgpt", "openai",
                         "gemini", "llama", "mistral", "qwen", "deepseek"))
MODEL_SHAPES = re.compile(r"gpt\d.*|o\d+|\d+o")
# The next-step trailer per config `languages.docs.primary` (the word the templates/<lang>/AGENTS.md use); other languages: English.
NEXT_TRAILERS = {"es": "Siguiente", "en": "Next"}
MERGE_STATES = ("MERGE_HEAD", "REVERT_HEAD", "CHERRY_PICK_HEAD")
# The subject reviewed.sh writes for the review-mark commit (by `languages.docs.primary`; SHA-1 or SHA-256 object names): it has no
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


def types_of(config):
    """The accepted Conventional Commits types (commitTypes); the built-in ones when the key is not a list."""
    given = config.get("commitTypes")
    return tuple(given) if isinstance(given, list) and given else TYPES


def wip_of(config):
    """The prefix of a commit made in red (commitWipPrefix); "" means no exemption."""
    given = config.get("commitWipPrefix")
    return given if isinstance(given, str) else WIP_PREFIX


def without_wip(subject, wip):
    return subject[len(wip):] if wip and subject.startswith(wip) else subject


def model_rules(config):
    """(names, shapes): the built-in ones plus what agentModelNames and agentModelShapes add. A project can only add:
    the built-in entries are always there, whatever the config says."""
    names, shapes = set(MODEL_NAMES), [MODEL_SHAPES]
    for key, target in (("agentModelNames", names), ("agentModelShapes", shapes)):
        given = config.get(key)
        for item in given if isinstance(given, list) else []:
            if not isinstance(item, str) or not item:
                raise Reject(f"{key} in .claude/gw.json has an entry that is not a non-empty string ({item!r}); "
                             f"fix it: python3 {HERE / 'config.py'} validate")
            if key == "agentModelNames":
                target.add("-".join(t for t in re.split(r"[^a-z0-9]+", item.lower()) if t))
            else:
                try:
                    target.append(re.compile(item, re.I))
                except re.error as exc:
                    raise Reject(f"agentModelShapes in .claude/gw.json has an invalid regex {item!r} ({exc}); "
                                 f"fix it: python3 {HERE / 'config.py'} validate")
    return names, shapes


def names_a_model(value, rules=None):
    names, shapes = rules or (MODEL_NAMES, [MODEL_SHAPES])
    pieces = [t for t in re.split(r"[^a-z0-9]+", value.lower()) if t]
    joined = "-" + "-".join(pieces) + "-"
    # a configured name is split the same way, so `my-model` matches the pieces my, model in a row
    return (any(any(sh.fullmatch(t) for sh in shapes) for t in pieces)
            or any(n and (n in pieces or f"-{n}-" in joined) for n in names))


def check_agent(found, msgfile, rules=None):
    for key, value in found:
        if key.lower() == "agent" and names_a_model(value, rules):
            raise Reject(f"the Agent trailer names a model or provider, which this project forbids "
                         f"(agentSignatures: false in .claude/gw.json): {key}: {value}\n"
                         f"commit-msg: name the skill or role instead (Agent: gw-orchestrate-dealer) and commit "
                         f"again: git commit -e -F {msgfile}")


def check_next(config, message, found, msgfile):
    wip = wip_of(config)
    word = NEXT_TRAILERS.get(gwconfig.languages(config)["docs"]["primary"], NEXT_TRAILERS["en"])
    subject = next((line for line in message.splitlines() if line.strip()), "")
    rest = without_wip(subject, wip)
    # "Merge " is not exempt here: a real merge is skipped by its MERGE_HEAD, and a plain commit titled "Merge ..." is not one.
    if not subject or rest.startswith(tuple(l for l in GIT_LINES if l != "Merge ")):
        return
    if any(key.lower() == word.lower() and value for key, value in found):
        return
    raise Reject(f"the message has no `{word}:` trailer with the next concrete step (commitNext: true in .claude/gw.json)\n"
                 f"commit-msg: end the message with a paragraph of trailers with a `{word}: <next step>` line "
                 f"and commit again: git commit -e -F {msgfile}; for a message that legitimately has none: "
                 f"GW_NO_NEXT=1 git commit -e -F {msgfile}")


def check_measured(config, message, found, msgfile):
    """The trailers metrics.quality.findingsTrailer and retriesTrailer (`Findings:`, `Retries:`) count only in the
    trailer block (change-size.py, metrics.py): a line of that shape that git does not read as a trailer is lost
    silently, so it is refused."""
    quality = gwconfig.metrics(config)["quality"]
    for word in (quality["findingsTrailer"], quality["retriesTrailer"]):
        key = word.lower()
        lines = [l for l in message.splitlines() if re.match(rf"{re.escape(key)}[ \t]*:[ \t]*\d+[ \t]*$", l, re.IGNORECASE)]
        kept = [k for k, _ in found if k.lower() == key]
        if len(lines) > len(kept):
            raise Reject(f"a `{word}:` line is outside the trailer block, where change-size.py and metrics.py "
                         f"do not read it (it would be lost silently)\n"
                         f"commit-msg: move the `{word}: <n>` line to the last paragraph, next to `Refs:`, and commit "
                         f"again: git commit -e -F {msgfile}")


NEGATION = re.compile(r"(?<!\w)(?:sin|ningún|ninguno|no|without|zero|0)\s+$", re.IGNORECASE)  # "sin hallazgos"


def findings_warning(config, message, found):
    """E60: the warning line when the message speaks of review fixes (a word or phrase of
    metrics.quality.findingsWords, whole words, any case) and the trailer block has no findingsTrailer, or None. Without
    it metrics.py quality misses the fixes and the next block review starts from the wrong commit."""
    quality = gwconfig.metrics(config)["quality"]
    word = quality["findingsTrailer"]
    if any(k.lower() == word.lower() for k, _ in found):
        return None
    paragraphs = re.split(r"\n[ \t]*\n", message.strip())
    text = "\n\n".join(paragraphs[:-1] if found and len(paragraphs) > 1 else paragraphs)  # not the trailers (Siguiente:)
    for phrase in quality["findingsWords"]:
        pattern = r"(?<!\w)" + r"\s+".join(re.escape(p) for p in phrase.split()) + r"(?!\w)"
        if any(not NEGATION.search(text[:m.start()]) for m in re.finditer(pattern, text, re.IGNORECASE)):
            return (f"commit-msg: WARNING: the message speaks of review fixes (\"{phrase}\") and has no `{word}:` "
                    f"trailer, so metrics.py quality misses them and the next block review starts too early; if it "
                    f"closes a review, add `{word}: <accepted findings>` next to `Refs:`: git commit --amend")
    return None


def check_format(config, message, msgfile):
    types, wip = types_of(config), wip_of(config)
    subject = next((line for line in message.splitlines() if line.strip()), "")
    if not subject:
        return  # git itself refuses an empty message
    rest = without_wip(subject, wip)
    conventional = re.compile(rf"(?:{'|'.join(re.escape(t) for t in types)})(?:\([^()\s][^()]*\))?!?: \S")
    if rest.startswith(GIT_LINES) or conventional.match(rest):
        return
    raise Reject(f"the first line is not in the conventional form (commitFormat: conventional in .claude/gw.json): "
                 f"{subject!r}\ncommit-msg: write `type(scope)!: text` with type one of {', '.join(types)} "
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


def staged_changes(root):
    """[(status, path)] of the staged files (renames as a delete plus an add)."""
    r = git(root, "-c", "core.quotepath=false", "diff", "--cached", "--no-renames", "--name-status", "-z")
    if r.returncode != 0:
        raise Reject(f"git diff --cached failed ({r.stderr.strip()[:200]}); check the repository: git status")
    items = r.stdout.split("\0")
    return [(items[i], items[i + 1]) for i in range(0, len(items) - 1, 2)]


def code_paths(root, paths):
    """The paths among `paths` that are code, by is-code.sh (the one classification: --list reads the config of HEAD, so a
    commit cannot widen `content` and pass its own code as content)."""
    if not paths:
        return []
    script = HERE / "is-code.sh"
    if not script.is_file():
        raise Reject(f"{script} is missing; reinstall the workflow scripts: /gw-update")
    try:
        r = subprocess.run(["bash", str(script), "--list", *paths], cwd=str(root), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except OSError as exc:
        raise Reject(f"cannot run bash ({exc}); check that bash is installed: bash --version")
    if r.returncode != 0:
        raise Reject(f"is-code.sh could not classify the staged files ({r.stderr.strip()[:300]}); fix the cause above "
                     f"and commit again (a repository without a first commit needs one: git commit --allow-empty -m 'chore: start')")
    return [l for l in r.stdout.splitlines() if l]


def check_task_record(root, config, message, found, msgfile):
    """C11: see the header (taskRecord). Raises Reject; returns when the commit is exempt or complete."""
    record = gwconfig.task_record(config)
    subject = next((line for line in message.splitlines() if line.strip()), "")
    wip = wip_of(config)
    if (wip and subject.startswith(wip)) or subject.startswith(GIT_LINES):
        return
    m = re.match(r"([a-z]+)(?:\([^()\s][^()]*\))?!?: ", subject)
    if not m or m.group(1) not in record["requiredFor"]:
        return
    base = record["path"]
    changes = staged_changes(root)
    if not code_paths(root, [path for _, path in changes if not path.startswith(base + "/")]):
        return
    ids = []
    for key, value in found:
        if key.lower() == "refs":
            ids += [t for t in re.split(r"[,\s]+", value) if t]
    edit = f"git commit -e -F {msgfile}"
    cmd = f"python3 {HERE / 'task.py'}"
    if not ids:
        raise Reject(f"a {m.group(1)} commit that changes code has no Refs trailer, so its task record cannot be found "
                     f"(taskRecord.enabled in .claude/gw.json)\ncommit-msg: add `Refs: <task id>` and commit again: {edit}")
    try:
        import task
    except ImportError as exc:
        raise Reject(f"cannot import task.py ({exc}); reinstall the workflow scripts: /gw-update")
    added = {path for st, path in changes if st == "A"}
    problems, complete = [], False
    for task_id in ids:
        contract = f"{base}/{task_id}.md"
        r = git(root, "show", f":{contract}")  # the index also holds what HEAD has: the contract need not be edited
        if r.returncode != 0:
            problems.append(f"{task_id}: {contract} does not exist; create it with `{cmd} new {task_id}`, fill it in and stage it")
            continue
        errors = task.contract_errors(r.stdout, config)
        if errors:
            problems.append(f"{task_id}: the staged {contract} is not a task record: {errors[0]}")
            continue
        entries = sorted(p for p in added if p.startswith(f"{base}/{task_id}/") and p.endswith(".md"))
        for path in entries:  # every entry a commit adds is kept for ever: each one must be well formed
            bad = task.entry_errors(show_staged(root, path), task_id, config)
            if bad:
                raise Reject(f"the new entry {path} is not a decision log entry: {bad[0]}\ncommit-msg: fix it, stage it "
                             f"and commit again: git add {path} && {edit}")
        if not entries:
            problems.append(f"{task_id}: the commit adds no decision log entry in {base}/{task_id}/; create one with "
                            f"`{cmd} log {task_id} --agent <skill|session>`, fill it in and stage it (git commit --amend "
                            f"is no exception: add a new entry saying what the amend changed)")
            continue
        complete = True
    if not complete:
        raise Reject(f"this {m.group(1)} commit changes code, so at least one id of its Refs ({', '.join(ids)}) needs its task "
                     f"record and a new decision log entry (the other ids are context) (taskRecord.enabled in "
                     f".claude/gw.json)\n" + "\n".join(f"commit-msg: {p}" for p in problems) +
                     f"\ncommit-msg: then commit again: git add {base} && {edit}")


def show_staged(root, path):
    r = git(root, "show", f":{path}")
    if r.returncode != 0:
        raise Reject(f"cannot read the staged {path} ({r.stderr.strip()[:200]}); stage it again: git add {path}")
    return r.stdout


def staged_or_head(root, rev, path):
    r = git(root, "show", f"{rev}:{path}")
    return r.stdout if r.returncode == 0 else ""


# The log's state-table cell whose change marks a phase change (D108), by its first cell, lowercased.
PHASE_KEYS = ("fase en curso", "phase in progress", "current phase")
VERSION_HEADING = re.compile(r"^## .*`\d+\.\d+(?:\.\d+)?`")


def phase_cell(text):
    """The value of the log's «Fase en curso»/«Phase in progress» row in its state section, or None."""
    import handoff
    import roadmap
    m = handoff.STATE_HEADING.search(text)
    section = text[m.end():].split("\n## ", 1)[0] if m else text
    for line in section.splitlines():
        spans = roadmap.cells(line)
        if spans and len(spans) >= 2 and line[spans[0][0]:spans[0][1]].strip(" *`").lower() in PHASE_KEYS:
            return line[spans[1][0]:spans[1][1]].strip()
    return None


def version_sections(text, done, open_words):
    """{`## ` heading with a backticked version: whether every task row under it (its `###` included) is done}. A task
    row is a table row whose last cell starts with the `done` word or an `open` one (roadmap.py's statuses)."""
    import roadmap
    words = (done,) + tuple(w.lower() for w in open_words)
    rows, heading = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line.strip() if VERSION_HEADING.match(line) else None
            continue
        spans = roadmap.cells(line) if heading else None
        status = roadmap.status_of(line).lower() if spans and len(spans) >= 2 else ""
        if status.startswith(words):
            rows.setdefault(heading, []).append(status.startswith(done))
    return {h: all(v) for h, v in rows.items()}


def task_rows(text, done, open_words, task_id):
    """{id (first cell): whether the row is done} for every table row whose last cell starts with the `done` word or an
    `open` one (D176; the rows version_sections groups by section)."""
    import roadmap
    words = (done,) + tuple(w.lower() for w in open_words)
    rows = {}
    for line in text.splitlines():
        spans = roadmap.cells(line)
        if spans and len(spans) >= 3:
            status = roadmap.status_of(line).lower()
            key = line[spans[0][0]:spans[0][1]].strip(" *`~")
            if status.startswith(words) and task_id.fullmatch(key):
                rows[key] = status.startswith(done)
    return rows


def closing(root, config, message):
    """What this commit closes (see the header): a roadmap version section, a task row (clearOnTaskClose) or the log's
    phase; None otherwise."""
    wip = wip_of(config)
    subject = next((line for line in message.splitlines() if line.strip()), "")
    if wip and subject.startswith(wip):
        return None
    files = gwconfig.roadmap_files(config)
    if files and files[0].get("done"):
        path, done, words = files[0]["path"], files[0]["done"].lower(), files[0].get("open") or []
        before = version_sections(staged_or_head(root, "HEAD", path), done, words)
        after = version_sections(staged_or_head(root, "", path), done, words)
        closed = [h for h, ok in after.items() if ok and before.get(h) is False]
        if closed:
            return f"the roadmap section {closed[0][3:]}"
        if config.get("clearOnTaskClose", True):  # D176: a single task row turned done counts too
            import handoff
            tid = re.compile(gwconfig.non_capturing(handoff.task_id_pattern(config)))
            rows_before = task_rows(staged_or_head(root, "HEAD", path), done, words, tid)
            rows_after = task_rows(staged_or_head(root, "", path), done, words, tid)
            rows = [t for t, ok in rows_after.items() if ok and rows_before.get(t) is False]
            if rows:
                return f"the roadmap task {rows[0]}"
    log = config.get("log")
    if log:
        old, new = phase_cell(staged_or_head(root, "HEAD", log)), phase_cell(staged_or_head(root, "", log))
        if old is not None and new is not None and old != new:
            return "a phase (the log's phase row changed)"
    return None


def clear_warning(root, config, message):
    """The D108 warning line, or None. Never raises: it is only a warning."""
    try:
        what = closing(root, config, message)
        if not what:
            return None
        import recover
        branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        over = recover.budget_overrun(Path(root), branch)
        if not over:
            return None
        return (f"commit-msg: WARNING: this commit closes {what} and the session passed its compaction budget "
                f"({over[0]} > {over[1]}): push and ask the user for /clear (a long context is almost all the spend; "
                f"the log is enough to resume)")
    except Exception:
        return None


def spike_branch(root, config):
    """C12: the current branch when it is an exploration branch (spikeBranch), else "" (detached HEAD, feature off)."""
    prefix = gwconfig.spike_prefix(config)
    if not prefix:
        return ""
    r = git(root, "symbolic-ref", "--short", "-q", "HEAD")
    name = r.stdout.strip() if r.returncode == 0 else ""
    return name if gwconfig.is_spike_branch(name, prefix) else ""


def mark_spike(root, path, branch):
    """C12: adds `Spike: <branch>` at the start of the trailer block unless one is there, so the pre-push and
    merge-branch.sh can tell this commit from a working branch's wherever it travels (merge, cherry-pick, rebase,
    squash message). Fails closed: without the mark the commit could reach a working branch unnoticed."""
    r = git(root, "interpret-trailers", "--in-place", "--no-divider", "--where", "start", "--if-exists", "doNothing",
            "--trailer", f"Spike: {branch}", str(path))
    if r.returncode != 0:
        raise Reject(f"cannot add the `Spike: {branch}` trailer ({r.stderr.strip()[:200]}); add it to the last "
                     f"paragraph by hand and commit again: git commit -e -F {path}")


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
    tasks = bool(gwconfig.task_record(config)["enabled"])
    state = git_paths_exist(root, ("rebase-merge", "rebase-apply") + MERGE_STATES)
    if state["rebase-merge"] or state["rebase-apply"]:
        return
    spike = spike_branch(root, config)
    if spike:
        refs = tasks = False  # C12: an exploration branch needs no Refs nor task record; the rest still applies
        mark_spike(root, path, spike)
    if not (fmt or refs or agent or nxt or tasks):
        return
    merging = any(state[name] for name in MERGE_STATES)
    if not (agent or not merging):
        return
    message = clean_message(root, text)
    subject = next((line for line in message.splitlines() if line.strip()), "")
    if REVIEW_MARK.fullmatch(subject):
        fmt = refs = tasks = False
    if not merging and fmt:
        check_format(config, message, msgfile)
    found = []
    if agent or (not merging and (refs or nxt or tasks)):
        found = trailers(root, message, msgfile)
    if agent:
        check_agent(found, msgfile, model_rules(config))
    if not merging and (refs or nxt):
        check_measured(config, message, found, msgfile)
    if not merging and refs:
        check_refs(root, config, found, msgfile)
    if not merging and nxt:
        check_next(config, message, found, msgfile)
    if not merging and tasks:
        check_task_record(root, config, message, found, msgfile)
    if not merging and (refs or nxt):
        warning = findings_warning(config, message, found)
        if warning:
            print(warning, file=sys.stderr)
    if not merging:
        warning = clear_warning(root, config, message)
        if warning:
            print(warning, file=sys.stderr)


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
