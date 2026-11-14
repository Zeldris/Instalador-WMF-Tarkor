---
name: gw-update
description: Bring a project's copy of Galivelop-workflow up to the workflow repo's current version, showing the template changes before applying what the user confirms. Use after the workflow publishes a new version (run by hand with /gw-update).
disable-model-invocation: true
license: MIT
compatibility: Claude Code or any Agent Skills agent; git and python3 3.8+; the Galivelop-workflow repo cloned or added to the session
metadata:
  version: "0.6.0"
  source: "Galivelop workshop"
---

# gw-update

If `.claude/gw/gw-update.md` exists in the project, read it first: it holds what is specific to the project.

Updates what the workflow owns (scripts, skills, git hooks, settings entries, CI) and reports changes in what the
project fills in (log, `REVIEW.md`, `GLOSSARY.md`, notes). The mechanical part is `apply.py`; this skill adds the
judgement: what changed, what the user wants, what to merge by hand. Reply in the project's `language`.

## 1. Compare versions

`<workflow>` is the clone of `Galivelop-workflow` (a sibling `../Galivelop-workflow`, or attached to the session;
else ask the user). Read it, never edit it. Bring it to the latest
published tag, not to the tip of whatever branch the clone follows (a single-branch clone of an old branch has neither
`main` nor the tags): `git -C <workflow> ls-remote --tags --refs --sort=-v:refname origin` (the first line is the
latest `vX.Y.Z`), then `git -C <workflow> fetch origin tag vX.Y.Z` and `git -C <workflow> checkout vX.Y.Z`. No tags
listed (or `origin` unreachable): stop and tell the user the workflow has no published version to update to; do not
fall back to `pull`.

- Project version: `version` in `.claude/gw.json`.
- Copied headers: `# galivelop-workflow vX.Y.Z` in `.claude/gw/scripts/*`, `.claude/agents/*` and `.githooks/*`.
- Workflow version: `version` in `<workflow>/.claude-plugin/plugin.json`, and its entries in `CHANGELOG.md`.
- Config format: `schemaVersion` in the project's `.claude/gw.json` (absent = 0) against `SCHEMA_VERSION` in
  `<workflow>/scripts/config.py`. Older: `apply.py` migrates it (step 2). Newer: the workflow clone is behind; stop
  and bring it to the latest tag (above).

Done when you can say "project at X, workflow at Y". Equal and no `.gw-new` pending: say so and stop. Project
newer than the workflow: stop and tell the user to update the workflow clone.

## 2. Dry run

```bash
git -C <project> status --short            # a clean tree makes the update easy to review and undo
python3 <workflow>/scripts/apply.py <project> --dry-run
```

It lists what it would create, update or propose, what it would `move` or `remove` to migrate a project installed with
the old names (skills without `gw-`, Spanish script names, `.claude/gw/<old>.md` notes, `docs/traspaso.md`,
`docs/registros/`, `docs/propuestas/`; ask the user; `--keep-paths` keeps the old project paths and writes `keepLegacyPaths: true`, so later runs and `--check` leave them alone), the `merge` of `.claude/gw.json` that migrates
an older `schemaVersion` (its reason lists each migration, `schemaVersion N → M`), files the workflow no longer has,
and template updates, plus the
user's personal notes (`~/.claude/gw/notas/`, see `docs/en/config.md`) it would create (`personal note`) or that differ
from the project's copy. Summarise it for the user with the CHANGELOG entries between X and Y (`### ES` or `### EN` per the user's language).

## 3. Show the template diff for filled files

Log, `REVIEW.md`, `GLOSSARY.md` and the `.claude/gw/*.md` notes are never overwritten, because the project filled
them in. Show what the **template** changed, not what differs from the project's file:

```bash
old="$(mktemp -d)"                                                              # a throwaway folder
git -C <workflow> show v<X>:templates/<language>/<file> > "$old/<file>"      # the template at the old version
git diff --no-index "$old/<file>" <workflow>/templates/<language>/<file>     # old template vs new template
```

If there is no tag `v<X>`, take the commit where `plugin.json` said X: `git -C <workflow> log -S'"version": "<X>"'
--oneline -- .claude-plugin/plugin.json`. Placeholders (`{{key}}`) stay unrendered on both sides, so the diff
shows only the template's own change. Offer each hunk to the user; apply the ones accepted to the project's file by
hand.

**Deal the reading out** (`gw-orchestrate-dealer`): each template diff, each `.gw-new` against the project's file
(step 4), and any diff or `--dry-run` output of more than ~200 lines go to a read-only subagent (the selector's
"light" rung), one per file or per group of small files; the main session never reads them whole. The brief gives
the paths to compare and the versions X and Y. The subagent returns only a table, one row per hunk, with line refs:

| Drift (what the project changed locally) | Upstream (what the workflow changed) | Decision (proposed) |
|---|---|---|

The decision is `take upstream`, `keep project` or `merge: <how>`. The main session decides each merge with the
user from the tables and opens a file only for a row in doubt.

## 4. Apply what the user confirms

1. Workflow-owned files with no local edits update in place:
   `python3 <workflow>/scripts/apply.py <project> --update`. Use `--update` only after the user confirms, because
   it also replaces local edits in workflow-owned files. Auto mode may ask permission to edit `.claude/settings.json`
   and `.githooks/`; tell the user first. The run also writes the migrated `.claude/gw.json` (one write, together with
   any path change); its other keys keep their values.
2. A `<file>.gw-new` (or the old `<file>.gw-nuevo`, still recognized in `0.x`) is a proposal: merge it by hand with the
   user from its subagent's table (step 3), then delete it. `AGENTS.md` and `CLAUDE.md`
   merge block by block, keeping the project's rules and the `galivelop-workflow` marker line.
3. Files the workflow no longer has are reported, never deleted: ask before `git rm`.
4. Personal notes: the missing ones are created by the run above. For each `personal note … differs` line, show the
   user `diff <source> <target>` (the project's copy is never overwritten and gets no `.gw-new`) and merge by hand
   only what they accept. Nothing personal ever goes into the workflow repo; `--no-personal-notes` skips them.
5. Every `WARNING: <file>:<line> uses the old name X; replace it with Y` line is a path or name of the workflow that
   a file of the project still cites under its pre-0.5 name. Show the list to the user and rename each use (or tell
   them which ones you left and why) before closing; `--check` exit 0 does not cover them. `legacyNames: false`
   turns the list off.
6. `apply.py` already set `version` in `.claude/gw.json` (step 4.1); check it says Y once the proposals are reviewed.

## 5. Check and commit

1. `python3 <project>/.claude/gw/scripts/doctor.py` until no `FAIL`; `python3 <workflow>/scripts/apply.py --check
   <project>` exits 0 when nothing is left to merge.
2. A `/code-review` of the update branch leaves out the files that are identical copies of the workflow at Y
   (`.claude/gw/`, `.claude/skills/gw-*`, `.githooks/`; `python3 <project>/.claude/gw/scripts/review-scope.py --workflow <workflow>` lists the rest): reviewed upstream, they
   were 89% of the paths of one update. Review the files the project merged by hand and its own files.
3. Commit with the message `apply.py` suggested and a real `Next:` line (`Siguiente:` in Spanish projects), update
   the log in the same commit, and `git push`; the pre-push runs the check.
4. Open the PR from the update branch to `protectedBranch` (the `pr` skill writes the body, listing the CHANGELOG
   entries between X and Y and what was merged by hand) and give the user its link. Merging stays the user's call.

Done when doctor is green, no `*.gw-new` is left, `version` equals Y and the PR is open.
