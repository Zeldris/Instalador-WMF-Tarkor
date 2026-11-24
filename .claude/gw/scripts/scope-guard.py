#!/usr/bin/env python3
# galivelop-workflow v0.9.0
"""Frozen scope (C13, `scopeGuard`): a change of requirements is another task.

  scope-guard.py                     PreToolUse hook on Edit, Write, MultiEdit and NotebookEdit (event JSON on stdin)
  scope-guard.py --staged [--root P] the pre-commit backup: the staged files (outside Claude Code too)

Which project, file and task: the same as questions-guard.py (it reuses its helpers): the edited file (symlinks
resolved, a relative path against the event's `cwd`, backslashes as `/`) belongs to the project when its worktree shares
the project's git common dir; that worktree gives the config and the current task (task.py current_task(): the branch
`agent/<id>-...`, else the mark `gw/current-task` of that worktree's git dir). A file outside the project, an event
naming no file it can place (a Windows drive path elsewhere), no current task, no record `<taskRecord.path>/<id>.md` or
a record without a `## Files` section: allowed, silently (there is no scope to compare with).

Always allowed: the record, its folder `<id>/` (the decision log), the records and folders of the ids its `Related:`
lines name (`task.py new <newid> --related <id>` links both), and the files the workflow itself writes, read from the
config (questions file, `log`, `metrics.ledger`, `reviewMark`, `ciLocalLog`). Any other
file must be named in `## Files` (task.py files_of/in_files: exact path, a folder prefix, a simple glob). Outside it, by
`scopeGuard.mode` (config.scope_guard()):
  - `warn` (default): allowed; `additionalContext` once per task and file (mark `gw/scope-warned` in the worktree's git
    dir) saying how to go on, and each time one line in `<git common dir>/gw/deviations.jsonl` (task.py deviations);
  - `block`: denied, with the same two ways on;
  - `auto`: `block` while `modes.questions` is restrictive, else `warn`;
  - `off`: nothing.
Not deviations (B44): a file `apply.py --vendored` gives as an unchanged copy of the workflow (review-scope.py's
caller; needs the workflow repo, `$GW_WORKFLOW`), and a change that only touches the stamped version (stamp.py: the
`galivelop-workflow vX.Y.Z` header, `version:`), so a version stamp commit is quiet without a record of its own.
The two ways on: add the file to `## Files` and explain it in the record's `## Change log`; or, if it is a new
requirement, open a new task linked from this one: task.py new <newid> --related <id>.

Policy when it cannot tell (unlike questions-guard.py, which denies code with a broken gw.json): this guard's default
job is to warn, so a .claude/gw.json it cannot read gives a one-line warning once and lets the edit through (the
questions guard already blocks code edits then, and commit-msg refuses a commit that is not WIP:); git hanging, or a
crash, denies only when the mode it could read is block. Not covered: files written with Bash. Output: nothing or one
JSON object on stdout, exit 0. With --staged: warnings on stderr, exit 1 only in block mode with staged files outside
Files, a staged record whose `## Files` grows without its `## Change log` naming the new paths (P3: going on means
writing it there), or a failure of its own (git hanging); skipped while closing a merge, cherry-pick, revert, rebase,
`git am` or `git merge --squash`. Python 3.8+ standard library only.
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True  # no __pycache__ in the project's .claude/gw/scripts
sys.path.insert(0, HERE)
import config  # noqa: E402
import task  # noqa: E402

_spec = importlib.util.spec_from_file_location("questions_guard", os.path.join(HERE, "questions-guard.py"))
qg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qg)
_rs_spec = importlib.util.spec_from_file_location("review_scope", os.path.join(HERE, "review-scope.py"))
rs = importlib.util.module_from_spec(_rs_spec)  # the one `apply.py --vendored` caller (D82)
_rs_spec.loader.exec_module(rs)
import stamp  # noqa: E402

WARNED = "gw/scope-warned"
NAME = "scope-guard"


def mode_of(cfg):
    """The mode the guard applies (off, warn or block)."""
    return config.scope_guard(cfg)["effective"]


VENDORED_TIMEOUT = 30  # seconds `apply.py --vendored` may take before nothing is skipped

IN_PROGRESS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "REBASE_HEAD", "rebase-merge", "rebase-apply",
               "SQUASH_MSG")  # metrics.IN_PROGRESS, plus `git merge --squash`: the other side's files


def flow_files(cfg):
    """The files the workflow itself writes and commits (from the config, never fixed): the questions file, the log, the
    token ledger that the pre-commit stages (metrics.ledger), the review mark, the local CI record, the roadmap files
    (`roadmapFiles`, D149) and the pending file (`pendingFile`): closing any task touches them."""
    out = {config.questions_path(cfg), cfg.get("log") or config.schema_default("log"), cfg.get("reviewMark"),
           cfg.get("ciLocalLog"), config.pending_file(cfg)}
    for entry in config.roadmap_files(cfg):
        if isinstance(entry, dict):
            out.add(entry.get("path"))
    try:
        out.add(config.metrics(cfg)["ledger"])
    except Exception:  # noqa: BLE001 (a broken metrics key leaves the rest)
        pass
    return {f.strip().strip("/") for f in out if isinstance(f, str) and f.strip()}


def always_allowed(rel, cfg, record_base, task_ids):
    """The records and decision-log folders of the task and of the tasks its `Related:` lines name (a new requirement's
    record, the guard's own way on), and the workflow's own files."""
    for tid in task_ids:
        if rel == f"{record_base}/{tid}.md" or rel.startswith(f"{record_base}/{tid}/"):
            return True
    return rel in flow_files(cfg)


def scope_of(top, cfg, task_id):
    """(base, record rel path, patterns, ids): patterns None when there is no record or no Files section; ids are the
    task and its `Related:` ones."""
    base = config.task_record(cfg)["path"].strip("/")
    rel = f"{base}/{task_id}.md"
    try:
        text = (Path(top) / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return base, rel, None, [task_id]
    return base, rel, task.files_of(text), [task_id] + task.related_of(text)


def how_on(task_id, record, rel, script_cmd):
    return (f"add `{rel}` to `## Files` of {record} and explain it in its `## Change log`; or, if it is a new requirement, "
            f"open a new task linked from this one: {script_cmd} new <newid> --related {task_id}")


def task_cmd(top):
    own = Path(top) / ".claude" / "gw" / "scripts" / "task.py"
    full = own if own.is_file() else Path(HERE) / "task.py"
    rel = os.path.relpath(str(full), str(top))
    return "python3 " + (str(full) if rel.startswith(os.pardir) else rel)


def warn_once(top, key):
    """True the first time `key` is seen in this worktree's git dir (and records it)."""
    saved, qg.WARNED = qg.WARNED, WARNED
    try:
        return qg.warn_once(top, key)
    finally:
        qg.WARNED = saved


def vendored_lookup(top):
    """B44: (files, why): the files the project holds as unchanged copies of the workflow (`apply.py --vendored`, through
    review-scope.py), written by `apply.py` and not by the task. Only the pre-commit uses it: before an edit a copy is
    always unchanged, so the hook cannot tell it from a file the task is about to change. Empty when the workflow repo or
    the answer is not available (a timeout included): then they count as before (the safe side). WHY (D150) is the
    one-line notice naming the fix (`workflowClone` when no clone was found, the by-hand command when apply failed), else None."""
    try:
        workflow = rs.workflow_dir(None, top, config.load(str(top)))
    except rs.ScopeError as exc:  # no (usable) clone: the fix is where it is looked for
        return set(), (f"copies of the workflow were not skipped ({first_sentence(exc)}); set `workflowClone` in "
                       f".claude/gw.json or export GW_WORKFLOW=<clone>")
    except (config.ConfigError, OSError, subprocess.SubprocessError):
        return set(), None
    try:
        return rs.vendored(top, workflow, timeout=VENDORED_TIMEOUT), None
    except rs.ScopeError as exc:  # the clone was found but `apply.py --vendored` failed or timed out: not a clone problem
        return set(), (f"copies of the workflow were not skipped ({first_sentence(exc)}); run it by hand: "
                       f"python3 {Path(workflow) / 'scripts' / 'apply.py'} --vendored {top}")
    except (OSError, subprocess.SubprocessError):
        return set(), None  # a failed lookup only means nothing is skipped (a bug still shows)


def first_sentence(exc):
    """The first sentence of a ScopeError on one line (review-scope.py's commands come after its first `;`)."""
    return " ".join(str(exc).split(";")[0].split())


def vendored_set(top):
    """B44: the unchanged copies of the workflow (see vendored_lookup); empty when they cannot be told."""
    return vendored_lookup(top)[0]


def stamp_only_staged(top, rel):
    """B44: True when the staged change of `rel` only changes the stamped version (`galivelop-workflow vX.Y.Z`, `version:`)."""
    r = subprocess.run(["git", "--literal-pathspecs", "diff", "--cached", "-U0", "--no-renames", "--", rel], cwd=str(top), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        return False
    stamped, other = stamp.stamp_diff(r.stdout, rel)
    return stamped > 0 and other == 0


def stamp_only_edit(event, rel=None):
    """B44: True when an Edit or MultiEdit event only replaces stamped-version lines (of the file REL) with the same lines."""
    inp = event.get("tool_input") or {}
    edits = inp.get("edits") if event.get("tool_name") == "MultiEdit" else [inp]
    if not isinstance(edits, list) or not edits:
        return False
    for e in edits:
        if not isinstance(e, dict) or not isinstance(e.get("old_string"), str) or not isinstance(e.get("new_string"), str):
            return False
        if not stamp.only_stamp(e["old_string"].splitlines(), e["new_string"].splitlines(), rel):
            return False
    return True


STATE = {}  # the edited file's worktree, for the crash handler


def hook():
    event = qg.read_event()
    if event is None or event.get("tool_name") not in qg.TOOLS:
        return 0
    home = qg.home_root(event)
    path = qg.target_path(event)
    if home is None or path is None:
        return 0  # not in a repository, or a file it cannot place: no scope to compare with
    top, rel = qg.place(path, home)
    if top is None:
        return 0  # outside the project
    STATE["top"] = top
    cfg, broken = qg.load(top)
    if broken:
        if rel != ".claude/gw.json" and warn_once(top, "broken-config"):
            qg.emit({"additionalContext": f"{NAME}: .claude/gw.json cannot be read ({broken}), so the task's scope is not "
                                          f"checked; fix it: python3 {os.path.join(HERE, 'config.py')} validate"})
        return 0
    mode = mode_of(cfg)
    if mode == "off":
        return 0
    try:
        task_id, _ = task.current_task(top, cfg)
    except task.GitStuck as exc:
        why = f"{NAME}: git did not answer ({exc}), so it cannot tell the current task; check the repository (git status)"
        if mode == "block":
            qg.emit({"permissionDecision": "deny", "permissionDecisionReason": why})
        elif warn_once(top, "git-stuck"):
            qg.emit({"additionalContext": why})
        return 0
    if not task_id:
        return 0
    base, record, patterns, ids = scope_of(top, cfg, task_id)
    if patterns is None or always_allowed(rel, cfg, base, ids) or task.in_files(rel, patterns):
        return 0
    if config.scope_guard(cfg)["skipStamps"] and stamp_only_edit(event, rel):
        return 0  # B44: a version stamp is not a deviation (a copy of the workflow is: before the edit it is always unchanged)
    way = how_on(task_id, record, rel, task_cmd(top))
    if mode == "block":
        qg.emit({"permissionDecision": "deny", "permissionDecisionReason":
                 f"{NAME} (block mode): `{rel}` is outside the scope of task {task_id} (`## Files` of {record}); {way}."})
        return 0
    task.log_deviation(top, task_id, rel, "warn")
    if warn_once(top, f"{task_id}: {rel}"):
        qg.emit({"additionalContext": f"{NAME}: `{rel}` is outside the scope of task {task_id} (`## Files` of {record}); "
                                      f"{way}. (Shown once per task and file; logged in deviations.jsonl.)"})
    return 0


def unlogged(top, record, cfg):
    """Paths that the staged record adds to `## Files` (against HEAD) without naming them in its `## Change log`: growing
    the scope must say why (P3). Empty for a new record (its first Files is the plan) or one it cannot read."""
    def show(rev):
        r = subprocess.run(["git", "show", f"{rev}:{record}"], cwd=str(top), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
        return r.stdout if r.returncode == 0 else None
    old, new = show("HEAD"), show("")
    if old is None or new is None:
        return []
    before, after = task.files_of(old) or [], task.files_of(new) or []
    log_name = config.task_record(cfg)["sections"]
    log_name = next((n for n in log_name if n.lower() == "change log"), "Change log")
    body = next((b for h, b in task.sections_of(new) if h.lower() == log_name.lower()), "")
    old_body = next((b for h, b in task.sections_of(old) if h.lower() == log_name.lower()), "")
    added_log = body if not old_body else body.replace(old_body, "", 1) if old_body in body else body
    return [f for f in after if f not in before and f.rstrip("/") not in added_log]


def staged(root_arg):
    """The pre-commit backup: staged files outside Files. Exit 1 only in block mode."""
    top = Path(root_arg) if root_arg else config.git_toplevel(os.getcwd())
    if top is None:
        print(f"{NAME}: not inside a git work tree; run it in the project: python3 {__file__} --staged", file=sys.stderr)
        return 1
    cfg, broken = qg.load(top)
    if broken:
        print(f"{NAME}: WARNING: .claude/gw.json cannot be read ({broken}), so the task's scope is not checked; fix it: "
              f"python3 {os.path.join(HERE, 'config.py')} --root {top} validate", file=sys.stderr)
        return 0
    mode = mode_of(cfg)
    if mode == "off":
        return 0
    try:
        return staged_check(top, cfg, mode)
    except task.GitStuck as exc:
        why = f"git did not answer ({exc}), so the task's scope is not checked; check the repository (git status, a " \
              f"stale .git/index.lock) and commit again"
    except Exception as exc:  # noqa: BLE001 (warn mode never blocks a commit on the guard's own failure)
        why = f"it failed ({type(exc).__name__}: {exc}); check it: python3 {os.path.join(HERE, 'scope-guard.py')} --staged"
    if mode == "block":
        print(f"pre-commit: {NAME} (block mode): {why}", file=sys.stderr)
        return 1
    print(f"pre-commit: {NAME}: WARNING: {why}", file=sys.stderr)
    return 0


def staged_check(top, cfg, mode):
    for head in IN_PROGRESS:  # the other side's files are not this task's
        out = qg.git(top, "rev-parse", "--git-path", head)
        if out and (Path(top) / out).exists():
            return 0
    task_id, _ = task.current_task(top, cfg)
    if not task_id:
        return 0
    base, record, patterns, ids = scope_of(top, cfg, task_id)
    if patterns is None:
        return 0
    # The hook's own environment (GIT_INDEX_FILE of `git commit -a` or `git commit <paths>`) says what is staged.
    r = subprocess.run(["git", "diff", "--cached", "--name-only", "--no-renames", "-z"], cwd=str(top),
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError(f"git diff --cached failed: {r.stderr.strip()}")
    names = [p for p in r.stdout.split("\0") if p]
    outside = [p for p in names if not always_allowed(p, cfg, base, ids) and not task.in_files(p, patterns)]
    guard = config.scope_guard(cfg)
    if outside:  # B44: copies of the workflow and version-stamp-only changes are not deviations (a `chore(H..)` stamp commit
        vendored, why = vendored_lookup(top) if guard["skipVendored"] else (set(), None)  # is all of them, so it needs no record either)
        outside = [p for p in outside if p not in vendored and not (guard["skipStamps"] and stamp_only_staged(top, p))]
        if outside and why:  # D150: say that the copies of the workflow were not skipped, and how to fix it
            print(f"{NAME}: {why}", file=sys.stderr)
    grown = unlogged(top, record, cfg) if record in names else []
    if not outside and not grown:
        return 0
    lines = []
    if outside:
        listed = "\n".join(f"  {p}" for p in outside)
        lines.append(f"these staged files are outside the scope of task {task_id} (`## Files` of {record}):\n{listed}\n"
                     f"pre-commit: {how_on(task_id, record, outside[0], task_cmd(top))}")
    if grown:
        listed = "\n".join(f"  {p}" for p in grown)
        lines.append(f"{record} adds to `## Files` without naming them in its `## Change log`:\n{listed}\n"
                     f"pre-commit: write why in `## Change log` (one line naming `{grown[0]}`), then: git add {record}")
    if mode == "block":
        text = "\npre-commit: ".join(lines)
        print(f"pre-commit: {NAME} (block mode): {text}" + (f"\npre-commit: or unstage them: git restore --staged -- "
              f"'{outside[0]}'" if outside else ""), file=sys.stderr)
        return 1
    for p in outside:
        task.log_deviation(top, task_id, p, "commit-warn")
    for p in grown:
        task.log_deviation(top, task_id, p, "files-unlogged")
    print(f"pre-commit: {NAME}: WARNING: " + "\npre-commit: ".join(lines), file=sys.stderr)
    return 0


def main(argv):
    if argv[:1] == ["--staged"]:
        root = argv[2] if argv[1:2] == ["--root"] and len(argv) > 2 else None
        return staged(root)
    return hook()


def crash(exc):
    """A failure of the hook: deny only when the mode of the edited file's worktree (else the session's) is block."""
    why = f"{NAME}.py failed ({type(exc).__name__}: {exc}); check it: python3 {os.path.join(HERE, 'scope-guard.py')}"
    try:
        cfg, broken = qg.load(STATE.get("top") or qg.home_root(None))
        strict = not broken and mode_of(cfg) == "block"
    except Exception:  # noqa: BLE001
        strict = False
    qg.emit({"permissionDecision": "deny", "permissionDecisionReason": why} if strict else {"additionalContext": why})


if __name__ == "__main__":
    if sys.argv[1:2] == ["--staged"]:
        sys.exit(main(sys.argv[1:]))
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # noqa: BLE001
        crash(exc)
        sys.exit(0)
