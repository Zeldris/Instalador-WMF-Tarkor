---
name: gw-metrics
description: Read the token reports of a day, week, month or quarter (by model, agent, branch and task id, with money from the dated price table) and explain where the spend went. Use when the user asks how much was spent, which model, agent or task cost the most, how a period compares with another, for a token or cost report of a period, or to save one in the repo.
license: MIT
compatibility: "Claude Code or any Agent Skills agent; python3 for .claude/gw/scripts/metrics.py (standard library only); needs the token ledger (metrics in .claude/gw.json)."
metadata:
  version: "0.6.0"
  source: "Galivelop workshop (block B, measurement)"
---

# gw-metrics

If `.claude/gw/gw-metrics.md` exists in the project, read it first: it holds what is specific to the project.

**The script makes every figure; you only read them.** Never add, convert or estimate tokens or money yourself: quote
the report's numbers, and when a question needs a number the report does not show, say so instead of working it out.

## Steps

1. **Pick the period.** From the user's words: `day`, `week` (ISO, Monday to Sunday), `month` or `quarter`, and a date
   inside it (`YYYY-MM-DD`, UTC; today when none is given). "Yesterday" or "last week" means a date in that period.
2. **Make the report.**
   `python3 .claude/gw/scripts/metrics.py report --period <period> [--date YYYY-MM-DD]`. Done when it printed a report
   or said `no ledger rows`; in that case tell the user the period is empty and, if the ledger itself is missing, that
   `metrics.record` must be on (`python3 .claude/gw/scripts/config.py get metrics`).
3. **Explain it** in the project's `language` (`.claude/gw.json`), in a few lines, each one citing the table it comes
   from:
   - the total in tokens and USD, and that USD is a reference when the user pays by subscription;
   - the biggest share by model, by agent and by task id, and anything that stands out (one subagent type above the main
     session, a branch nobody expected, a large share under `(none)`: work without a `Refs:` trailer);
   - cache: a high `Cache read` against `Input` is normal and cheap; a large `Cache write` points at contexts rebuilt
     often (`/clear`, compaction, many short subagents) and `gw-opt-tokens` measures why;
   - the task-id table can add up to more than the total (a row with two ids counts in both): never sum it;
   - a `Without a price` section: those tokens are not in the USD figures; adding the model to `metrics.prices` fixes it.
4. **Compare when asked** ("than last week", "September against October"): `python3 .claude/gw/scripts/metrics.py
   compare --period <period> [--date YYYY-MM-DD] [--against YYYY-MM-DD]` sets the period of `--date` beside the one
   before it, or beside the one of the same kind that holds `--against`. Quote its `Change` column (`new` = nothing in
   the first period; `n/a` = unpriced tokens on one side) and name the rows that moved most; never work out a change it
   does not print.
5. **Quality beside spend, when asked** ("was it worth it", "which tasks needed rework"):
   `python3 .claude/gw/scripts/metrics.py quality --period <period> [--date YYYY-MM-DD]` sets, per task id, the spend
   beside signals read only from commit messages: commits, red (`WIP:`), rework (`fix`/revert commits after the id's
   first one), and the `Findings:` and `Retries:` trailers. Quote its figures, never your own count. A task with few
   commits is a weak signal; ignored trailers (non-integer values) are listed at the end and are worth fixing.
6. **Save it only when asked.** `--write` (report or quality, which adds `-quality` to the name) saves it under `metrics.reports` (`docs/metrics/` by default) as
   `daily/`, `weekly/`, `monthly/` or `quarterly/<name>.md`; the same ledger gives the same file, so rerunning it is safe.
   It goes in the next commit, with the log, like any other change.

## Limits

- The `SessionStart` hook already warns (`metrics.py alert`, B6) when a model's spend today or yesterday passes
  `metrics.alert.factor` times its daily mean; when the user asks about such a warning, run the day report it names.

- `compare` only prints; to keep a comparison, save the two reports with `--write`.
- The ledger only holds what the `Stop` hook recorded and was pushed: a cloud session whose container died before its
  last commit is missing, and the report cannot tell.
- `cacheWrite` is priced as the 5-minute write (1.25 × input); 1-hour writes cost more and the ledger does not split
  them, so USD can be slightly low.
