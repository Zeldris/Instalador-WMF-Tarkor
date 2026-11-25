---
name: gw-init
description: Apply Galivelop-workflow to the current project by following the workflow repo's apply guide (new or existing project). Use when starting the workflow in a repo (run by hand with /gw-init).
disable-model-invocation: true
license: MIT
compatibility: Claude Code or any Agent Skills agent; git, bash and python3 3.8+; the Galivelop-workflow repo cloned or added to the session
metadata:
  version: "0.9.0"
  source: "Galivelop workshop"
---

# gw-init

If `.claude/gw/gw-init.md` exists in the project, read it first: it holds what is specific to the project.

A thin wrapper: the procedure lives in the workflow repo's guide, `docs/en/apply.md` (Spanish: `docs/es/aplicar.md`).
Follow it step by step. This skill only fixes where to find things and what to confirm.

**Read the workflow with a subagent** (`gw-orchestrate-dealer`, light model): it reads the guide and the project's build
files and returns the step-1 decision table, each candidate value with its source path, and the conflicts with the
project (existing `CLAUDE.md`, hook managers, a red check). The main session decides from that summary and never
reads the workflow's guides or scripts whole.
Reply to the user in the language they use; the project's docs language (`languages.docs.primary`) is decided in step 3.

## 1. Find the workflow repo

`<workflow>` is the clone of `Galivelop-workflow` that holds `scripts/apply.py`. Look in this order:

1. A sibling of the project: `../Galivelop-workflow`.
2. A repo already attached to the session (check `ls` of the session's working folders).
3. Otherwise ask the user to clone it next to the project or add it to the session, and wait. Read it, never edit it.

When cloning it, take the latest published tag, not the default branch (which may not be `main` and may be an old
version): `git ls-remote --tags --refs --sort=-v:refname <url>` shows the tags (the first line is the latest), then
`git clone --branch vX.Y.Z <url>`. Whatever the origin (a new clone, a sibling clone that already exists or a repo
added with `add_repo`), compare `git -C <workflow> describe --tags` with the latest tag and, if it is behind, run
`git -C <workflow> fetch --tags` and `git -C <workflow> checkout vX.Y.Z`.

Done when `python3 <workflow>/scripts/apply.py --help` runs.

## 2. Check the preconditions

The project is a git repo (`git init` if new), `git status` is clean or the user knows what is unpushed, and the
session was opened with the project as its working folder. If it was not, tell the user to reopen it from the
project: `cd <project> && claude`.

## 3. Decide what needs judgement

Follow section 1 of the guide: `languages.docs.primary`, `log`, `install`, `check`, protected branch, `direct` or `pr`, `content`
regexes, the agent signatures (`agentSignatures`), the own skills prefix (`projectSkillPrefix`), and the optional skills `gw-opt-ai` and `gw-scout-updates` (only
if the user asks).

- Infer `install` and `check` from `package.json`, `pyproject.toml`, `Cargo.toml`, `pom.xml`, `go.mod` or
  `Makefile`, and run the `check` command once.
- Ask whether the project accepts agent signatures (`Co-Authored-By` of Claude, session links). If not, add
  `--agent-signatures false`: the `commit-msg` hook then rejects them and `apply.py` writes the "No Claude signatures"
  rule into the project's `CLAUDE.md`, which overrides the environment's attribution reminder.
- Ask which prefix the project gives its own skills (e.g. `gvg-`; never `gw-`, the workflow's). If it has or will
  have its own skills, add `--project-skill-prefix <prefix>`: `doctor.py` then warns of an own skill without it.
- Offer a licence (an offer, never imposed; skip it if the project already has a `LICENSE` or the user declines): the
  dual licence of this workflow, MIT for the code and CC BY-NC-SA 4.0 for the content, with a third-party note. Ask for
  the copyright year and holder; the files are copied in step 4, after `--init`.
- Mention that the project can give people or roles their own config through profiles (`profile.py`, the `profiles` block;
  convenience, not access control): nothing to set now; if the user wants one, `python3 .claude/gw/scripts/profile.py new <name>`
  then `assign <email> --profile <name>`, and the config reference (`docs/*/config.md`) has the rest.
- Ask the user whenever a value is a guess. Offer numbered candidates; one question per unknown.

Done when every fact has an answer the user confirmed.

## 4. Apply

1. Dry run first, then the same command without `--dry-run`:

   ```bash
   python3 <workflow>/scripts/apply.py <project> --dry-run --init --language <es|en> --log <path> \
     --install "<cmd>" --check-command "<cmd>" --protected-branch <branch> \
     --push-to-protected <direct|pr> --content '<regex>'
   ```

   `--init` also writes a marked per-stack block into `.gitignore` (Node, Python, Rust, Go): the stacks are detected
   from the project's root files, or fixed with `--stack <stack>` (repeatable; `gitignoreStacks` in
   `.claude/gw.json`, `docs/en/config.md`). Tell the user which stacks were written.
   Repeat `--install`, `--check-command` and `--content` once per value. Add `--with gw-opt-ai` or
   `--with gw-scout-updates` when chosen. Existing projects: read "Existing projects" in the guide first (hook
   managers, existing `CLAUDE.md`, red check, existing log).
2. If the licence was accepted, copy from `<workflow>/templates/licenses/`: `LICENSE-code.txt` to `LICENSE`,
   `LICENSE-content.md` and `THIRD-PARTY.md` under their own names, never over a file that already exists (if one
   does, tell the user and leave it). Fill `<year>` and `<holder>`, list the project's third-party material in
   `THIRD-PARTY.md` (name, source, licence) or delete its placeholder row when there is none, and mention the
   licences in the README's licence section.
3. The run also installs the light subagent type `.claude/agents/gw-worker.md` (the dealer's briefs name it with `subagent_type: gw-worker`); tell the user it exists. Auto mode may ask permission to edit `.claude/settings.json`, `.claude/gw/scripts/`, `.claude/agents/` and `.githooks/`. Tell the user before running, and
   after a refused call run `git status` and `git diff` before repeating it.
4. Review every `*.gw-new` with the user (guide, step 3). Merge `AGENTS.md` and `CLAUDE.md` blocks by hand; keep
   the `galivelop-workflow` marker line. Delete each `.gw-new` once merged.
   Coming from an earlier or hand-made copy, expect many: merge one at a time, the workflow's version whole and the
   project's own part in `.claude/gw/<skill>.md` (guide, "Migrating from an earlier copy").
   The run also carries the user's personal notes from `~/.claude/gw/notas/` (if any) to `.claude/gw/`; a project
   copy that differs is left as is and reported (`diff <source> <target>`); `--no-personal-notes` skips them.
5. Fill the `_(…)_` gaps of the log with branch, phase and a concrete next step.

Done when no `*.gw-new` is left and the log has a next-step line.

## 5. Check, commit, push

1. `python3 <project>/.claude/gw/scripts/doctor.py`; fix and rerun until no `FAIL` is left. Explain each `WARN` to
   the user (`docs/en/troubleshooting.md`).
2. Commit with the message `apply.py` suggested, replacing its last line with the real `Next:` (`Siguiente:` in
   Spanish projects), then `bash .claude/gw/scripts/push.sh <branch>` (it retries on network failures and counts
   as pushed only what `git ls-remote` confirms); the new pre-push runs the check on the pushed commit.
3. Report: what was created, what the user must decide next, and that nothing went to the protected branch.
4. Warn the user: a `.claude/settings.json` created mid-session is not loaded until the next session, so the
   `PreToolUse` hook (the PR guard) is not active in this one. Until they open a new session from the project, check
   the review mark by hand before any PR: `bash .claude/gw/scripts/reviewed.sh`.

Done when the push went through and `doctor.py` exits 0.
