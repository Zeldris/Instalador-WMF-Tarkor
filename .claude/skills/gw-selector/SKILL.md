---
name: gw-selector
description: Pick the skill and models for the task that is starting. Use at the start of every task, when a bug or a design request arrives, before reviewing a diff for the protected branch, when a block or phase closes, and whenever the user asks which workflow or model fits.
license: MIT
compatibility: Claude Code or any Agent Skills agent; reads .claude/gw.json when present
metadata:
  version: "0.6.0"
  source: "Galivelop workshop; generalised from the Tarkor, installer and portal selectors"
---

# Selector

If `.claude/gw/gw-selector.md` exists in the project, read it first: it holds what is specific to the project.

Classify the task with the table, then act on its row. Reply in the project's `language` (`.claude/gw.json`).

| Case | Skill(s) | Session model | Session effort | Subagent model |
|---|---|---|---|---|
| Design: new feature, open decision, architecture, UX, anything the user must decide | `grilling` + `domain-modeling`; `prototype` when numbers, rules or screens need trying | large (Opus) | high | light (Haiku) for `Explore` searches |
| Bug, red or flaky test, something visibly broken | `diagnosing-bugs` | large if the cause is not obvious; medium (Sonnet) if it shows at first sight | high if not obvious; medium | none |
| Huge or foggy effort that no single session can hold | `wayfinder` (a map of decision tickets, one per session) | large | high | light, for `research` tickets |
| Write up a feature already discussed as a spec | `to-spec` | large | medium | none |
| Large change: several systems, data, migration, concurrency, build or routing | the project's plan for it | large | high | light, to find usages |
| Scoped change: one component, one adjustment, one test, one small endpoint | none | medium | medium | none |
| Mechanical: docs, log, renames, adapting tests to a new signature, converting files | none | medium or light | low | light |
| Bring something from another repo (a workflow, skills, documents) | `gw-orchestrate-dealer` | large, to decide what to adapt | medium | light `Explore` that reads the other repo and returns a summary with paths; the main session never reads the files whole |
| Apply or update the workflow (`gw-init`, `gw-update`, `gw-doctor`) | `gw-orchestrate-dealer` | large, to decide | medium | light, to read the workflow's guide and scripts and return the decisions with paths |
| Review before the protected branch (phase 1) | after `/clear` or in a clean subagent, never in the session that wrote the code: `/code-review` of what `python3 .claude/gw/scripts/review-scope.py --workflow <workflow repo>` lists (the diff without `vendored` files, the unchanged workflow copies), then `pr` for the description. A trivial diff (`review-scope.py --trivial` exits 0: no code per `is-code.sh`, or `reviewTrivialLines` changed lines or fewer) is reviewed in the session, without a subagent | large | high | none; its fixes go to `sonnet`, except where the dealer rule puts `opus` |
| Closing a block or phase | `/code-review` of the diff since the last block review (on a long branch: since the last commit with a `Findings:` trailer, `Findings: 0` if none; the commit-msg hook warns when it passes `changeSize.block` lines), then `retro` (Claude runs it, the user confirms its proposals); now and then `improve-codebase-architecture` | large | medium | none |
| Social posts about the project (what to post, a post, an announcement or an image about something that just happened) | `gw-media-content` to propose, `gw-media-content-now` to produce one piece | medium | medium | none |
| Token spend or cost of a period (how much, which model, agent or task cost the most, against another period) | `gw-metrics` (the script makes the figures) | medium | low | none |
| Writing for agents (`AGENTS.md`, `CLAUDE.md`, skills, docs agents read) | `writing-for-agents` | medium | medium | none |

Use a skill only if it exists in this repo's `skills/` (or `.claude/skills/`) or the project declares it; otherwise
do the case without it and say so.

## Rules

- **The user picks the session model and effort** (`/model`, `/effort`); an agent only recommends them and cannot
  switch them. State the case in **one line** that keeps the session and the subagents apart and names the current
  ones: `Session: <model> <effort> (current: <X> <E>; /model and /effort to change them) · Subagents: <rung or none>
  · Skill: <y>`. `<X>` is the model the session reports (its system prompt, or the session tool in the cloud); `<E>`
  is the effort it reports, or the value of `CLAUDE_CODE_EFFORT_LEVEL` when set (it beats `/effort`: say so if it
  differs from the recommendation); write `unknown` for either when nothing says it. If the session deals work out
  with `gw-orchestrate-dealer`, it takes the model and effort of the riskiest row it deals, medium at least. Then
  carry on. Wait for an answer only when the risk is high: data migration, deleting,
  rewriting published content.
- **Disabled models:** `python3 .claude/gw/scripts/models.py list` prints `models.disabled`; never recommend or pass
  one of them (an alias such as `opus` covers its whole family). If a row's model is disabled, take the next rung
  that is not and say so in the line; only the user re-enables one (`models.py enable`).
- **Subagent model and effort, per agent:** every Agent call passes both `model` and `effort` (a rung such as
  `sonnet low` is `model: sonnet`, `effort: low`; the table's "light" is `haiku low`), or names a `subagent_type`
  whose definition (`.claude/agents/<type>.md`) sets them in its frontmatter; a `fork` inherits the session. Never
  rely on global variables: `CLAUDE_CODE_EFFORT_LEVEL` beats every per-agent effort, and
  `CLAUDE_CODE_SUBAGENT_MODEL` with `_FORCE=1` forces one model on all subagents (`doctor.py` warns of both;
  `subagent-cap.py` reminds of a call that sets neither). Delegate searches, long reads and mechanical work; design
  and decisions stay in the main session.
- **Closed plan, scoped implementation:** goes to a `sonnet` subagent and the main session reviews its diff before
  the commit. The fixes from a review are a closed plan too (`sonnet`); `opus` only to debug something non-obvious. Anything of more than one step runs through `gw-orchestrate-dealer`.
- **Subagent ladder:** `sonnet low` → `sonnet medium` → `opus medium` → `opus high`. Start at the lowest rung that
  fits; when a subagent does not finish its brief, the next attempt climbs one rung. **Two failures at one rung: stop
  and ask the user.** A subagent that never starts (tool error) is retried on the same rung and does not count as a
  failure. Unattended long work that closes nothing in a batch stops and writes the state to the log.
- **When in doubt between two rows, take the one with higher risk.**
- **Closing a task or PR:** with everything pushed and the log up to date, ask the user for a `/clear` in one line,
  saying why (a long context is almost all the spend; the log is enough to resume).
- **Compaction budget:** at the start of a task, estimate how many compactions it should need (0–5) and write it in
  the log next to the count the session already has (`recover.py --state` prints it). Write it as
  `Compaction budget: N` (or `Presupuesto de compactaciones: N` in a Spanish log), in the task's row with `logRows`,
  else in the state section; text after the number is free. `handoff.py` defines the format and `recover.py --state`
  reads it and, over the budget, warns. Going over the budget is the signal to deal more work out with
  `gw-orchestrate-dealer`, not to keep going.
- **Design references:** if `.claude/gw.json` lists `designReferences`, design rows contrast each proposal with them
  and name the source (see `grilling`).
- Decisions reached in a design session go to the project's plan or log (`log` in the config); glossary terms to
  `GLOSSARY.md`; decisions hard to reverse to `docs/adr/`.

## Project rows: `selector.cases`

`.claude/gw.json` may add rows under `selector.cases`. Read them at the start and treat them like the table above,
matching them before the generic rows. Shape of one entry:

```json
{ "selector": { "cases": [
  { "case": "Change to the installer's process spawning",
    "skill": "diagnosing-bugs",
    "sessionModel": "large",
    "sessionEffort": "high",
    "subagentModel": "sonnet medium" }
] } }
```

- `case`: when the row applies, in one sentence a task can be matched against.
- `skill`: skill name(s) or `none`.
- `sessionModel`: `large`, `medium` or `light` (or a model name).
- `sessionEffort`: `low`, `medium`, `high`, `xhigh` or `max`; without it, the effort of the generic row it overlaps,
  else `medium`.
- `subagentModel`: a rung of the ladder, a model name, or `none`.

A project row overrides the generic row it overlaps; the rules above apply to both.
