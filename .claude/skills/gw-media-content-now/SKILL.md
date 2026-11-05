---
name: gw-media-content-now
description: "Produce one unpublished post piece (texts per channel plus images) in a dated folder, from a proposal id or a free topic. Use when the user picks a proposal from gw-media-content, or asks for a single post, announcement or image about something that just happened."
license: MIT
compatibility: "Needs Python 3, git, Node with Playwright and ImageMagick (convert with WebP) for the media step."
metadata:
  version: "0.5.0"
  source: "Galivelop workshop; generalised from a project's social-media skill"
---

# gw-media-content-now

If `.claude/gw/gw-media-content-now.md` exists in the project, read it first: it holds what is specific to the project.
Then read `.claude/gw/gw-media-content.md` if it exists, and its shape in `.claude/skills/gw-media-content/note.md`
(folder `<dir>`, languages, channels, extra channels, palette, screenshots, task prefixes, Reddit rules). Without a
`Folder`, `<dir>` is `docs/media`; 0.x: when that does not exist and `docs/difusion` does, use `docs/difusion` and tell the
user once that `/gw-update` moves it.

You make **one piece**: `<dir>/YYYY-MM-DD/NN-<topic>/`, with texts for each channel and the images that go with
them. Pieces accumulate in the day's folder. Nothing is ever published: the user posts and records where. Shared
material is in `.claude/skills/gw-media-content/`: `catalog.md`, `rules.json`, `note.md`, `template/`, `scripts/`.

## Steps

1. **Input.** A proposal id (`YYYY-MM-DD/P3`: read its block in `<dir>/proposals/YYYY-MM-DD.md` (or the old `propuestas/`)) or a free topic
   (pick the row of `catalog.md` that fits; with no repo data behind it, say so and stop). Done when you can name
   the topic, the facts to use and the channels: the proposal's networks (or the request's) among the active ones.
2. **Folder.** `<dir>/YYYY-MM-DD/` for today; `NN` is the next free two-digit number there (01 if none); `<topic>` is a
   lowercase slug (`a-z`, `0-9`, `-`). Copy `.claude/skills/gw-media-content/template/` into `NN-<topic>/` and shape it:
   - delete the channel files not in use; for an extra channel of own format, copy its template (note) as `<channel>.md`;
   - in `sheet.md` set `Languages:` (the first language is the main one) and `## Channels`, delete the `## Reddit` block
     when `reddit` is not a channel, and delete the example rows of `## Verified facts` and `## Images`;
   - replace every `<topic>`, `YYYY-MM-DD` and `{{...}}` placeholder in the folder, or delete its line.
   Done when the piece folder holds `sheet.md` plus one file per channel, with no placeholder left.
3. **Facts first: `sheet.md`.** Every claim in the piece goes in the table `Verified facts` with its source.
   Numbers come from `python3 .claude/skills/gw-media-content/scripts/figures.py [--since REF]`; the rest from a cited
   file and line or commit. Only what is merged; if the project has a canon (lore, design docs), claims about it come
   only from there. Task ids, branches and internal notes go in `Internal use`. Done when each fact a channel will use
   has a source cell.
4. **Media.** Every image a channel carries exists in `media/` and is listed in `## Images` with alt text in
   every language; a text-only piece leaves `## Images` with no rows.
   - From the template: `mv` (not `cp`) the source for the chosen format in `media/source/` to its final name, delete
     the other template sources, and fill every `{{...}}`. Names per language: the first language
     `media/source/<n>.html`; any other language that needs its own image `media/source/<n>.<lang>.html` (never a
     suffix for the first language: `check.py` rejects it). Apply the palette from the note.
   - Screenshots: steps in the note; crop to what matters, save in `media/source/` as `.png` or `.jpg`; no
     personal data, no placeholder or broken text on screen.
   - Render: `node .claude/skills/gw-media-content/scripts/render.mjs <piece-folder>` (it names what is missing and the
     command to fix it). From `media/source/<n>.html` it writes `media/<n>.webp`, `media/<n>-mini.webp` and
     `media/<n>.png`; from `<n>.<lang>.html`, `media/<n>.<lang>.webp` (+ `-mini`, `.png`); a `carousel*.html` gives a
     `.pdf`. Use the `.png` for LinkedIn (it takes `.png`, `.jpg`, `.gif`, not WebP), the `.webp` for X, Reddit,
     Discord and web, `.webp`, `.png` or `.jpg` for an extra channel, the `.pdf` carousel for LinkedIn only. Read each render
     image before using it.
5. **Channels.** Write each channel file in every language, from the sheet only, in the shape of its template file and
   within `rules.json` (`check.py` enforces it). Each post names its image on an `Image:` line; in an
   own-format channel there is no `Image:` line: the image path (`media/x.webp`) appears in the file's text.
   - **Reddit** (`## Reddit` in `sheet.md`): the `- **Subreddit:** r/<x>`, `- **Rules read:** YYYY-MM-DD` and
     `- **Self-promotion:**` lines go before the first `###`, then one `### Rules of r/<x>` per subreddit holding the
     rules the user pasted (at least `reddit.rules_min_chars` characters, no `#` headings inside: paste them as
     plain lines). `Rules read:` is counted from the piece's date folder and is at most `reddit.rules_days` days
     old. Take the rules from the note or the sheet when they are dated within that limit; otherwise ask the user to
     paste them (Reddit cannot be read automatically, and rules are never invented), then continue.
   - **Web** (`web.md`, see `note.md`): fill the ```json block of the template; leave `"status": "draft"` (only
     the user writes `"ready"`), `date` the planned publication day, one text per language in `text` and in every
     `wall` text (the languages of `Languages:` plus `Web languages` of the note). Each `wall` image is a `.webp`
     render whose `## Images` row lists `web`; without a wall entry, delete `wall`. In 0.x the template writes every
     key twice, in English and in the old Spanish spelling (`estado` `"borrador"`, `fecha`, `texto`, `muro`...); fill both
     with the same values (`check.py` fails when a pair differs); the Spanish ones go away in 1.0.
   - **Extra channels** (declared in the note): one `<channel>.md` as the note says: a section per language within its
     `limit`, or the copied own-format template filled in. If the note gives neither, ask.
6. **Check.** Build the command from the note as `note.md` says (`--task-prefixes`, `--web-languages` when the piece lists
   `web`, and `--limit <channel>=N` or `--own-format <channel>` for each extra channel of the piece) and run
   `python3 .claude/skills/gw-media-content/scripts/check.py [options] <piece-folder>`; it prints `OK`, and each
   line it prints is a fix to make. Then reread the English: natural, not a literal translation.
   Done when `OK` is printed and the reread found nothing to change.
   Pieces made before 0.5 (`ficha.md`, `medios/`, Spanish keys in `web.md`) still check, with a warning; leave them as
   they are unless the user asks to rename them.
7. **Close.** Mark the proposal `**Status:** done → <piece folder>`. Commit with the project's commit format; the log
   row names the folder, its channels and that it is ready to publish. Show the user the texts and image paths; with `web.md`, tell them
   the site publishes it only once they set `"status": "ready"` (and `"estado": "listo"` in 0.x).
   After publishing, the user fills `## Published` in `sheet.md`.
