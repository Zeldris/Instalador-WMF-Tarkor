---
name: gw-orchestrate-dealer
description: Run the main session as an orchestrator that deals work out to clean-context subagents, so it can work for hours without /clear. Use for any task of more than one step (a plan task, a batch of fixes, a whole phase), when bringing material from another repo, and when the session context passes ~150k tokens.
license: MIT
compatibility: Claude Code or any Agent Skills agent with subagents; git; reads .claude/gw.json
metadata:
  version: "0.9.0"
  source: "Galivelop workshop; generalised from the Tarkor, installer and portal gw-orchestrate-dealer"
---

# gw-orchestrate-dealer

If `.claude/gw/gw-orchestrate-dealer.md` exists in the project, read it first: it holds what is specific to the project.

The main session is the **orchestrator**: it holds the plan, the decisions and the thread with the user, and deals each
chunk of work to a subagent that starts with an empty context. Every deal is an automatic `/clear`: the main session
receives a short summary and grows slowly. Reply to the user in the project's docs language (`languages.docs.primary`). Its own model is that of its own work (plan, decide, review: usually Sonnet `medium`), weighed with `metrics.py quality`; Opus only for design or a non-obvious cause (`gw-selector`).

Config values used below come from `.claude/gw.json`: `check`, `log` (handover file), `protectedBranch`,
`languages.docs.primary`. Read it once at the start.

## Who does what

| Orchestrator (main session) | Subagent |
|---|---|
| Talk to the user, ask, present | Read code, long docs, logs, screenshots, other repos |
| Split the task and write each brief | Implement, debug, run the tests |
| Decide (design, what to fix, what to log) | Run a batch of manual or end-to-end checks |
| Review what returns: `git log`, `git diff --stat`; the whole diff only when in doubt | Commit and push its work, log update in the same commit |
| `/code-review`, `/gw-opt-tokens`, `/retro`, PR and merge | none |

A read of more than ~200 lines, or a long output, in the main session is a chunk that was not dealt out.

## Steps

1. **Split.** With the `gw-selector` already applied, cut the task into chunks one subagent can close in one go: a fix,
   a module, a screen, a command. Each chunk gets a **done criterion** that can be checked (a green test, a green
   CI job, a pushed commit), a list of what blocks it and the files it touches. Each chunk carries its task id; if the
   commit hook checks ids against a roadmap, commit the missing rows before dealing (a subagent cannot add them). The **frontier** (one wave) is the chunks
   nothing pending blocks: they go out together (see Rules), but two chunks of one wave never share a file: the second
   waits for the first. With more than ~5 chunks, a cheap-model subagent may review the split before launch (missing
   blockers, shared files, criteria that cannot be checked). Cap a subagent at ~30 tool calls (one or two proposal rows); at the cap it saves its state in `log` and the
   next one resumes from it. A subagent's context grows with every call: chunks of 44-55 calls averaged 100-116k;
   splitting them costs one more ~50k startup but far less than the drag. A one-file fix whose place the reviewer gave is
   not a chunk: the main session makes it, with its tests (a subagent pays ~50k to start and rediscovers what it knows).
2. **Deal.** One subagent per chunk with the Agent tool, in the foreground when the next chunk depends on it. Model and
   effort follow the `gw-selector` ladder: `sonnet` to implement, `opus` to debug something non-obvious, skipping
   any model in `models.disabled` (`subagent-cap.py` denies it). Every call passes the rung as both `model` and
   `effort` (`sonnet low` → `model: sonnet`, `effort: low`), retries and reviewers included; never leave them to the
   session or to global variables. Where `.claude/agents/gw-worker.md` exists, every chunk uses
   `subagent_type: gw-worker` with its rung as `model` and `effort` (the call's win over the definition's
   `sonnet low`), and every reviewer `subagent_type: gw-reviewer` (`.claude/agents/gw-reviewer.md`: `/code-review`
   without MCP tools); a chunk that needs skills, web or MCP tools stays `general-purpose`. Both start at ~13-20k instead of the ~65-68k of `general-purpose` (retros 2026-11-11 and
   `0.7.0`, 181 `opus` calls of `general-purpose` in one version). `subagent-cap.py` reminds it. With `sonnet` in `models.disabled`, the call's `model` names the next rung (the definition's `sonnet` is denied). Fixes from a
   review go to `sonnet` too: the reviewer already closed the plan (where and what to change). The brief carries
   **pointers, not copies**: where the material is (the log row, the plan task, a doc, a commit, a file and
   function), never the pasted text. Template:

   ```text
   You work in this repository on branch <branch>. In a fresh, clean worktree, first check its base:
   `git merge-base --is-ancestor {head} HEAD`; if it fails (the worktree was born elsewhere, e.g. on `origin/main`),
   `git reset --hard {head}` before anything else. Your scratch files (dumps, logs, drafts, findings) go in
   `{scratch}/<id>-<topic>/`: create it, and never read or write another agent's folder. Read your state with
   `python3 .claude/gw/scripts/recover.py --state`; if it reports no row for your branch or the log has no
   per-branch rows, read the next step of {log} and the pending file (`pendingFile`, else the log's Pending). If you touch code, read REVIEW.md and
   AGENTS.md. Follow the project's commit and push rules. On the working branch you push each stable point and
   commit with the log update in the same commit; in a worktree (`agent/<id>-<topic>`) you commit but never push and
   never touch the log (the main session does both). Leave nothing uncommitted when you reply: every change is in
   your last commit. If a push is rejected, `git fetch` and `git merge` (never rebase), then push again.
   At ~25 tool calls, commit (`WIP:` if red), push, and reply with what is left under MISSING.
   Final push and other long waits: in the background with a `timeout` of 5400000 ms (a full check takes over 10
   minutes, the foreground cap), waited for with its notice or `Monitor` (ToolSearch first), never a `sleep`. Wait for the background push with `Monitor` until it ends, never by ending your turn, and reply once, with nothing of yours running, only after `git ls-remote` confirms the push. To stop a process
   you started, `TaskStop` with its id (load it with ToolSearch); `kill` and `pkill` are denied to subagents.
   Push with its output to a file outside the tree (`git push … > "$(git rev-parse --git-dir)/push.log" 2>&1`); if it
   fails, read the pre-push reason in that file before retrying.
   Task: <what, in one or two sentences>.
   Files: <paths you touch>. Create: <exact names of what is new>. A path not listed here: stop and return it
   under QUESTIONS.
   Done when: <checkable criterion>. Run before pushing: `bash .claude/gw/scripts/check.sh` (runs {check} and records
   the green so the push does not repeat it). Before each commit, shellcheck of the `.sh` files you touched and the tests of what you touched:
   `python3 .claude/gw/scripts/tests-for.py --diff {head} --run` (from `testMap`, shellcheck first; `--why` says which rule brought each test; if empty, pick them yourself).
   Tests live in: <where the tests of each layer you touch live, e.g. `tests/test_ui_browser.py` for the UI>.
   For guard code or scripts: first list the edge cases (git states, platforms, empty or odd input) and write a
   test for each before calling the chunk done; the review afterwards is the safety net, not the first pass. Each new test: prove it red without the fix with `bash .claude/gw/scripts/red-without-fix.sh`.
   Do not: <what belongs to another chunk or needs a user decision>.
   If you change a function or a field, grep every user of it and adjust them, or list them under MISSING.
   A red test is pre-existing only if it fails the same on `origin/{protectedBranch}` (both outputs under EVIDENCE).
   Your branch is named `agent/<id>-<topic>` (`<id>` = the task id, e.g. `agent/D11-commit-format`); if isolation
   created another name, rename it first: `git branch -m agent/<id>-<topic>`.
   Applying a document from another repo: each point's literal text and path go to a scratchpad file; reply its path.
   If the bug is a pattern (a wrong check, a missing quote, a case left out), grep its other occurrences, also in the
   siblings of the files you touch (twin, other language, copy), and fix them too, or list them under MISSING.
   If you touch processes, paths or permissions, write it for every platform the project supports.
   If something needs a user decision, stop and return it as a question (never ask the user yourself). Never merge into {protectedBranch}.
   Write your reply and commit message in {language}. Reply in at most 15 lines:
   DONE: <per point of the task: whole or partial, and what is left> · COMMIT: <sha> · EVIDENCE: <command and summarised result> · MISSING: … · QUESTIONS: …
   If the chunk cannot be tested, reply NOT_TESTABLE: <reason> + the command that checks it another way, in place of
   EVIDENCE. Every number you report you counted yourself.
   Add FOUND: (one line per finding) and TOOLS: (failures of the project's scripts, hooks or CI) only if you have any.
   ```

   `{check}`, `{log}`, `{protectedBranch}` and `{language}` are filled from the config before sending; `{head}` is
   the main session's `git rev-parse HEAD` when dealing (an `isolation` worktree starts from `worktree.baseRef`, often
   `origin/main`, not from it), and `{scratch}` the session's scratchpad folder (outside the tree). Add a line
   for each project rule a fresh agent could miss.
3. **Review what returns.** Run `git status -sb` (uncommitted or unpushed work: the subagent is told to commit it, not
   fixed inline), fetch and check the commit (`git fetch`, `git log -1 --stat`) and that the done criterion holds (a
   red called pre-existing counts once you see it fail the same on the protected branch); one whose final commit is
   already pushed but has not returned is stopped with `TaskStop`, and so is one whose report you accepted (else it resends it). If it does not close, the retry climbs one rung
   (its commit carries `Retries: <n>` for `metrics.py quality`); two failures, stop and tell the user. Chunks that
   depended on it are marked "cancelled: blocked by X" and listed to the user. For every subagent branch built in a
   worktree, **before merging it**, a subagent reviewer runs a short `/code-review` of its diff and returns only the
   findings; nothing merges until they are fixed. The reviewer's brief carries `git diff --stat` and asks it to compare the
   diff with the **contract**: the doc that describes it and the real callers outside the branch (grep on the working
   branch), not the diff alone. Per-branch reviews miss cross-branch breaks (a script vs. its backend, a doc vs. its code,
   two branches editing one rule). Findings come as `path:line | severity | anchor | problem. fix.` (anchor: a rule, a
   `docs/tasks/<id>.md` criterion, a plan line or a demonstrated failure; none: «Observations», no severity). It also asks
   it to flag data that expire (versions, prices, quotas, limits of an outside service) written without date and source, and
   to write its findings to a file outside the tree (scratchpad, or `"$(git rev-parse --git-dir)/review.md"`) as well as
   replying: a compaction or handover loses them, and fix briefs and minor ones for `log` come from that file. The fixes go
   back to **the subagent that wrote the chunk** (SendMessage to its id): it still holds the context, and a fresh subagent
   per round pays the startup and the rediscovery again. After the merge (`merge-branch.sh` removes the worktree) they go to
   a new subagent with the findings file's path. Log what comes back: `FOUND` and `TOOLS` into `log` (or the project's records). `QUESTIONS` go to the user as
   they are, with the answer you recommend.
4. **Close the wave.** After merging the whole wave, one reviewer subagent compares the merged result with the task
   and returns `MISSING_ITEMS`: what the task asks for and no chunk covers. Each item becomes a chunk or a question.
5. **Continue.** Next chunk. One line to the user per chunk closed; the detail lives in `log`. When something long
   starts (a push with its check, a background subagent), one line to the user with what runs and roughly how long it
   takes; then wait for its notification.

## Rules

- **Code from a subagent gets its own review:** every chunk that changes code (always the hooks, push/merge guards
  and the scripts they call; also code a subagent commits on the working branch, not only worktree branches)
  passes a short `/code-review` by a reviewer subagent as soon as the chunk returns, before the next chunk starts
  (commit it first, as `WIP:` if needed). The reviewer compares the diff with the contract (step 3); its fixes land
  before moving on. If the whole-branch review follows right away and is decided, the last block skips its own.
- **Before the PR, only what matters:** fix what is serious or medium, and what the fix itself breaks; log the minor
  findings in the pending file (`pendingFile`, else `log`), not reviewed again in this PR (`/code-review --max-findings
  all` lists them), or every fix brings new findings and the PR never ends. Its fixes are dealt too (next rule); only a
  one-file fix whose place the reviewer gave stays in the main session.
- **A big phase 1 review is dealt too (E86):** a trivial diff (`review-scope.py --trivial` exits 0) never splits.
  Count the changed lines of the files it lists (`git diff --shortstat <base> -- <files>`); above `python3 scripts/config.py
  get review.splitLines` (`0` = never) form the groups yourself (a shared contract stays in one), deal one `gw-reviewer`
  per group plus a short one for what crosses them, each with `pendingFile`; join the findings.
- **Approved review findings are dealt by group of files:** after the user approves the findings of a `/code-review`,
  group them by the files they touch (findings that share a file go together; a group stays within the ~30-call cap)
  and deal one subagent per group, in series on the working branch or in parallel worktrees as in the rules above.
  The rung follows the files, also for the fixes of a phase 1 review (B27), whose scope is what `review-scope.py`
  lists (no `vendored` files, D82): `sonnet` for mechanical fixes (a rename, a doc, the installed copies), `opus` for
  hooks, push/merge guards, security and the scripts they call (a cheaper model there costs quality). A fix brief is the one
  case where the brief copies text: each finding verbatim with its failure scenario (from the findings file), plus
  that file's path, so the subagent fixes the cause, not the symptom. The brief also says what happens to the commit:
  on the working branch the subagent commits its fixes with the `Findings:` trailer and its log row
  (`handoff.py set-row`) in that same commit; in a worktree it commits without touching the log and the main session
  writes it after the merge. The main session reviews each returned diff against those scenarios before the next
  group (ten fixes inline: ~100 calls at ~120k).
- **One writing subagent at a time on the same branch.** Two that commit to the same branch collide in the log and in
  shared files. In parallel, only what does not write (searching, reading, measuring).
- **A subagent that writes in the background always works in a worktree, even alone:** the main session keeps
  committing on the working branch, and a lone writer there collides with it (the `Stop` hook halts the session over
  the writer's uncommitted changes). Same setup as the next rule; it never edits the main tree.
- **Code fixes of the frontier, in parallel, in isolated worktrees:** each subagent runs with `isolation: "worktree"` in
  the background, commits at every stable point (`WIP:` if still red, so a restart loses nothing), does not touch the
  log or push, and returns its branch. In its worktree it runs the tests of what it touches (`tests-for.py --diff
  {head} --run`), the linters and the copy check, not the full `check`: the check's lock is one per repo, so parallel full checks run in series. The main
  session has each one reviewed (step 3), merges them one by one (merge, never rebase; `merge-branch.sh --defer-check` but the last, whose merge runs the only full
  `check`, with the whole wave's related tests; no edits to the tree meanwhile, drafts to the scratchpad), writes the log and pushes. When the session folder is not the repo root
  (a cloud session starts in `/home/user`, next to other repos, and `isolation` lands the worktree in the wrong one),
  the main session creates each worktree itself with `git -C <repo> worktree add <folder> -b agent/<id>-<topic>` and
  puts that folder in the brief, without `isolation` (put it under `.claude/worktrees/`: a folder elsewhere is not
  cleaned by `merge-branch.sh`, remove it by hand with `git worktree remove`). Branches are `agent/<id>-<topic>`: `merge-branch.sh` adds their
  ids (the name's and the commits' `Refs:`) to the merge message as one `Refs:` trailer and cleans `agent/*` branches.
- **Shared records, main session only:** with parallel subagents none touches `log`, the findings register or any other
  shared record; they return their entries under `FOUND` and the main session writes them. Parallel writes conflict
  on merge.
- **What names files of a branch, after merging it:** indexes and docs that link to files created in a worktree are
  written in the main session after that branch is merged; before, the links point at files that do not exist yet.
- **Manual or end-to-end batches run in a `sonnet` subagent, in series:** the main session does not drive the
  tool itself; it deals batches and logs what returns. **Size a batch by its items: 6-8 checks**, and split it on
  the fly when it grows (batches of 11-14 blew a 60-call cap; 6-8 kept within it). Screenshots only when the finding
  is visual; otherwise the text tool's output. Batches share the environment, so each leaves it in a state the
  next can resume from and says so under `MISSING`. **Before dealing a batch, check that the starting state gives
  each check its precondition** (scenario, data, account); if not, the first chunk prepares it.
- **Repos only read are cloned apart,** outside the tree, unregistered. **A subagent never talks to the user:** its
  questions return as `QUESTIONS`.
- **A subagent cut off by a usage or API limit is resumed, not restarted:** send it a message (SendMessage to its id)
  once the limit resets; it continues from its transcript (a new one would redo the work). Commit its partial work as
  `WIP:` meanwhile.
- **Intermediate state stays out of git:** dumps, screenshots, scratch logs and bench outputs go to a scratch folder
  (or a path in `.gitignore`); only results, tests and the log are committed. Each subagent gets its own
  `{scratch}/<id>-<topic>/` (like its branch): in a shared folder an agent overwrote another's files.
- **Measure:** `/gw-opt-tokens` before each PR compares context, compactions and model split; if they do not fall, dealing stays here.
- **A batch of approved rows is dealt, not worked inline:** the rows of an approved proposal or a findings list go
  one per subagent (or 2 small related rows), in series on the working branch, each reviewed as in step 3. A row the
  main session keeps (a one-file fix) counts against a stretch: every 4-5 rows, or at ~150k context, it writes the
  handover in `log` and recommends a `/clear`. 18 rows inline cost a 191k average context over 157 calls.
- **Automatic compaction is the net, not the plan:** at task boundaries write the handover in `log` and recommend
  a `/clear` to the user rather than letting the context grow. In the cloud the net may be missing: the session
  starts outside the repo and does not load its `.claude/settings.json` (`doctor.py` warns).
