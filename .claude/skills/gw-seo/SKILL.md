---
name: gw-seo
description: Check and improve the SEO and link previews of a project's static website before it is published. Use when a page, a route, the page generator, the sitemap, robots.txt or structured data changes, before taking website changes to the protected branch, and when the user asks about SEO, indexing or link previews.
license: MIT (adapted material from claude-seo, see LICENSE-claude-seo.txt)
compatibility: "Claude Code or any Agent Skills agent; python3 3.10+ for scripts/check_seo.py (standard library only) and the project's own build."
metadata:
  version: "0.9.0"
  source: "Galivelop workshop (born in a project's static website, E42); checks and references adapted from AgriciDaniel/claude-seo@6be93f4 (MIT)"
---

# gw-seo

If `.claude/gw/gw-seo.md` exists in the project, read it first: it holds what is specific to the project (shape in
[`note.md`](note.md)). Without it the defaults apply and you say so once.

The checkable part is a script, [`scripts/check_seo.py`](scripts/check_seo.py): it reads the **built** site, offline,
and reports every page's title, description, canonical, hreflang, Open Graph, JSON-LD, headings and images, plus
`robots.txt`, `sitemap.xml` and the parity between language versions. You only judge what a script cannot. Facts
and their primary sources live in [`references.md`](references.md); never state an SEO fact from memory, and never
promise a ranking effect.

## Steps

1. **Build.** Run the note's build command (default `npm run build`). Done when the build folder (default `dist`)
   comes from the current tree.
2. **Run the check** from the repo root:

   ```bash
   python3 .claude/skills/gw-seo/scripts/check_seo.py <build-dir> [--site <url>] [--langs en,es]
   ```

   Without `--site` it reads the site from the `Sitemap:` line of `robots.txt`; without `--langs`, from the hreflang
   values it finds. Fix every `ERROR` **in the source that generates the page** (the note's `Generator`), never in
   the build folder, then build and run it again. Done when it reports 0 errors and every `WARN` has a verdict: fixed,
   or kept with a one-line reason (e.g. a long title that is the project's real name).
3. **Judge what the script cannot**, for each page that changed:
   - **Title and description** say what the page is, in each language, with the words a person would search for in
     that language (not a word-for-word translation when the usual search term differs); the first ~60 characters
     of the title carry the meaning.
   - **Structured data** describes only what the page really shows, with a type Google still supports
     ([`references.md`](references.md#structured-data)); no invented ratings, reviews or prices.
   - **A new route or a changed URL** that may already be indexed is a one-way door: stop and ask the user (the old
     URL needs a redirect or must stay).
   - **AI crawlers in `robots.txt`** are the user's decision: present the table in
     [`references.md`](references.md#ai-crawlers) and wait.
   Done when every changed page has a verdict.
4. **Report** to the user: errors fixed, warnings kept and why, decisions waiting on them, and the manual actions
   only they can do (Search Console, Bing Webmaster Tools, refreshing a link preview), each with its tool from
   [`references.md`](references.md#manual-actions).

## Rules

- **A rule that keeps breaking becomes a check** in `check_seo.py`, with its test; this skill only keeps judgement.
- **Out of scope**: keyword research, backlinks, paid SEO APIs, local business listings, e-commerce, and AI-written
  content. Say so instead of improvising them.
- **References age.** Each entry carries the date it was read; one older than a year is re-read at its primary source
  before you rely on it, and the date updated.
