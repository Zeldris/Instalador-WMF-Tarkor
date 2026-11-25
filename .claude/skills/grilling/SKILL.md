---
name: grilling
description: Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
license: MIT (see LICENSE-mattpocock-skills)
metadata:
  version: "0.9.0"
  source: "mattpocock/skills@5beb35b"
---

If `.claude/gw/grilling.md` exists in the project, read it first: it holds what is specific to the project.

> Original skill by Matt Pocock ([mattpocock/skills](https://github.com/mattpocock/skills), MIT).

Interview the user relentlessly until you reach a shared understanding. Map this as a **design tree**: every decision branches into the decisions that hang off it.

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled: the questions you can ask _now_ without guessing at answers you haven't heard yet. Ask the whole frontier in one round: number each question and give your recommended answer. Then wait for the user's answers before the next round.

Format a round like so:

```
❓ **Q1** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>

---

❓ **Q2** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>
```

Word each question so "yes" accepts your recommended answer.

Each round the user answers reshapes the tree: settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round. A question whose answer depends on another question still open in this round belongs to a _later_ round, not this one.

Finding _facts_ is your job, never the user's. When a frontier question needs a fact from the environment (filesystem, tools, etc.), dispatch a sub-agent to find it; don't ask the user for anything you could look up yourself. Don't block on it: a running exploration is an unsettled prerequisite, so only the questions downstream of it wait for the sub-agent to report; ask the rest of the frontier now. The _decisions_ are the user's: put each to them and wait.

The session is done when the frontier is empty: every branch of the design tree visited, nothing left silently assumed. Do not act on it until the user confirms you have reached a shared understanding.

## In a Galivelop-workflow project

This section is the only change to the upstream skill.

- **Save each round before you show it**, so a session cut before the answer loses nothing and the next one knows
  what was asked. Append every question of the round to the questions file with
  `python3 .claude/gw/scripts/questions.py add --refs <task id> --rec "<recommended answer>" "<question>" ...` (one
  `--rec` per question, in order; the answers stay empty), commit it with the hand-off log naming the round's ids
  (`Q-<n>` to `Q-<m>`), push with `bash .claude/gw/scripts/push.sh <branch>`, and only then present the round.
  Number its questions with those `Q-<n>` ids instead of `Q1`, `Q2`. The user answers by number and
  `questions.py answer "5. a, 6. ok"` writes the answers into the file.

- If `.claude/gw.json` lists `designReferences` (products, frameworks or standards the project measures itself
  against), contrast each recommended answer with them and say which reference it comes from. Without the key, skip
  this.
