---
name: gw-mode
description: Show or switch the workflow's modes (careful, questions) in .claude/gw.json with one command. Use when the user asks which modes are active, to turn a mode on or off, to make the questions guard restrictive or a guide, or to stop careful asking before destructive commands.
license: MIT
compatibility: "Claude Code or any Agent Skills agent; python3 for .claude/gw/scripts/mode.py (standard library only); needs .claude/gw.json."
metadata:
  version: "0.9.0"
  source: "Galivelop workshop (block C, questions)"
---

# gw-mode

If `.claude/gw/gw-mode.md` exists in the project, read it first: it holds what is specific to the project.

**One switch for every mode; the script reads and writes the config, you never edit `.claude/gw.json` by hand for it.**

## Modes

- `careful` (`on` / `off`): the `careful.py` hook asks the user before a destructive command (`rm -r`, `git push
  --force`, `git reset --hard`).
- `questions` (`restrictive` = `on` / `guide` = `off`): `questions-guard.py` (C4, C5) blocks in restrictive mode and
  only advises in guide mode.
- `carefulExempt`, `carefulWorktrees`: lists; `list` shows them, the user edits them in `.claude/gw.json`.

## Steps

1. **See the state.** `python3 .claude/gw/scripts/mode.py list`. Done when you can say each mode's value. If it fails,
   the message says what is wrong with the config; fix that first (`python3 .claude/gw/scripts/config.py validate`).
2. **Switch only what the user asked.** `python3 .claude/gw/scripts/mode.py set <mode> on|off`. An unknown mode exits
   2 and lists the known ones; never guess a name.
3. **Confirm** by quoting the line it printed (`modes.questions: restrictive (true)`). Say the change is a config
   edit: it needs a commit to reach the other sessions and the team.
4. **Never turn a mode off to get past it.** If `careful` or the questions guard stops an action, ask the user; switch
   a mode only when they ask for the switch itself.
