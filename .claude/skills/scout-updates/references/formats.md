# Formats of the scout memory files

Both files live in `.claude/gw/scout/` of the target project and are kept by `scout-updates`; the user may edit them
(above all the constraints).

## `architecture.md`

An inventory in the spirit of an SBOM / ML-BOM ([CycloneDX](https://cyclonedx.org/capabilities/mlbom/)), in readable
Markdown.

```markdown
# Architecture - <project>

Kept by `scout-updates`. Every section carries its seal; to compare: `scripts/compare.py`.

## Constraints

- Minimum hardware: <machine>, <total memory>, <memory free for the component>.
- <local or cloud>, <language>, <budget>, <allowed licences>.

## AI models
<!-- seal: 2026-10-20 | 78667dc | backend/.env.example, backend/src/config/env.ts -->

| Component | Version | Use | Where it is configured |
|---|---|---|---|
| narrator | `model:tag` (base, quantisation, size) | narrates turns | `env.ts` `LLM_MODEL_NARRATOR` |
```

- **Sections**, by type, only those the project has: `AI models`, `Dependencies`, `Runtimes`,
  `Infrastructure and CI`, `External services`, `Planned`. The title is the focus name (`/scout-updates runtimes`).
- **`Planned`**: designed but not implemented components. The seal lists the design documents; the section says
  which constraints apply to them if they differ from the general ones.
- **`Constraints`** carries no seal and is never compared: the user writes it (step 0) and it is the step-4 filter.
- **Seal**, on the line after the title: `<!-- seal: YYYY-MM-DD | <short commit> | path, path -->`. The paths are the
  files the section comes from, relative to the root; a folder covers the manifests under it. Comparing with no
  change updates only the date; rewriting updates date and commit (`git rev-parse --short HEAD`).
- **Component**: what it is, exact version (or the manifest range), what it is used for, and every place it is pinned
  (a migration touches them all).
- **Dependencies**: the direct ones that matter (framework, ORM, client libraries, test tools); the rest summarised
  with their count and lockfile. Vulnerabilities are not recorded here: they are of the moment and come from the search.

## `proposals.md`

Cumulative record of everything proposed. **Nothing is deleted**: it prevents re-proposing what is settled or was
rejected.

```markdown
# Proposals - <project>

| Id | Date | Component | Proposal | Source (consulted) | State |
|---|---|---|---|---|---|
| P-001 | 2026-10-20 | narrator | `model-a` -> `model-b` (Trial, probable) | <url> (2026-10-20) | proposed |
```

- **Id**: `P-` and a running number, the next after the highest.
- **Proposal**: current -> proposed, with the ring and evidence strength of the card.
- **States**: `proposed` (in a report, undecided) · `accepted` (add the task that applies it) · `applied` (task closed)
  · `rejected: <reason>` (the reason is mandatory; it is what is checked to reopen) · `superseded by P-n` (the old row
  stays, unedited).
- **Reopen** a rejected one only if its reason no longer holds: add a new row that cites it ("reopens P-002: the
  budget is no longer 20/month") and mark the old one `superseded by P-n`.
- **Do not repeat:** before proposing, look the component and candidate up in the table. If it is alive (`proposed`,
  `accepted`) update it only with new evidence, in the same row (new source and date).

## The report (step 6)

Starts with a `## Coverage` table (one row per component of `architecture.md`: result, and what was consulted), then
one card per proposal with the fields listed in `SKILL.md`. `scripts/compare.py --report <report>` checks the table.
