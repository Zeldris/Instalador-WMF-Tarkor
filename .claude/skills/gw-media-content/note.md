# Project note of gw-media-content

Shared by `gw-media-content` and `gw-media-content-now`. The note is `.claude/gw/gw-media-content.md` in the project: a
list of `key: value` lines (keys in English). The workflow neither creates nor overwrites it. Without it the defaults
apply and you say so once. The 0.x Spanish names of the extra-channel shape (`límite`, `format: own`,
`plantilla`, `tono`) are still read as the same keys; ask the user to rename them.

| Key | Default | Holds |
|---|---|---|
| Folder | `docs/media` | the `<dir>` of every path in the skills (0.x: with no `Folder` in the note, no `docs/media` and a `docs/difusion`, use `docs/difusion` and tell the user to run `/gw-update`, which moves it) |
| Languages | `es, en` | any ISO 639-1 codes (two lowercase letters); the first is the main language; one `## <lang>` section per language in every channel file |
| Channels | `x, reddit, linkedin, discord` | the active channels; add `web` when the project's website reads the pieces (see below) |
| Extra channels | none | a channel beyond those five: see below |
| Web languages | the piece's `Languages:` | the website's languages (e.g. `es, gl, en`), passed as `check.py --web-languages` |
| Palette | the template's | CSS variable overrides for `media/source/*.html` |
| Screenshots | none | the steps that produce a screenshot of the running app |
| Task prefixes | none | e.g. `INS,FLU`: task-id prefixes of the project, passed to `check.py --task-prefixes` |
| Reddit | none | per subreddit: the rules pasted by the user and the date read |

## Web

`web` is the project's own website: `web.md` holds one ```json block another system reads (copy
`template/web.md`) with `status`, `date`, `text` (one text per language) and an optional `wall` (title, body paragraphs
and images, each with its alt text per language). The skill always leaves `"status": "draft"`; only the user
writes `"ready"`, which is the go to publish. The keys of `text` are the languages of `web.md`: every one of
`Languages:` plus any other the site needs; every other text in the block carries exactly those. With `Web languages`
in the note, they must be exactly those. Each image of `wall` is a `.webp` render listed in `## Images` with `web`
in its Channels cell. `web` is never an extra channel.

**In 0.x, write every key twice**, with the same value: the English one and its old Spanish spelling (`status`/`estado`
with `"draft"`/`"borrador"` and `"ready"`/`"listo"`, `date`/`fecha`, `text`/`texto`, `wall`/`muro`, `title`/`titulo`,
`body`/`cuerpo`, `images`/`imagenes`, `file`/`archivo`), so a website written before the rename keeps reading the
block. `check.py` fails when a pair differs, accepts a `web.md` with only the Spanish keys (with a warning that asks for
the English ones too) and one with only the English keys (no warning). The Spanish keys are removed in 1.0.

## Extra channels

Channel names are lowercase `[a-z0-9-]+`. Declare each one under `Extra channels:` with its shape, one line per
channel, in exactly one of two ways:

```
Extra channels:
- mastodon: limit: 500; tone: friendly
- portal: format: own; template: docs/media/portal.json
```

- `limit: N` is a channel with the usual shape (`<channel>.md`, a `## <lang>` section per language, `Image:` lines) and
  at most `N` characters per language section.
- `format: own` + `template: <path in the project>` is a channel whose file another system consumes (a JSON
  block for a website, say): `<channel>.md` has the shape of that template, with no `## <lang>` sections and no length
  check. `gw-media-content-now` copies the template into the piece as `<channel>.md`.

Tone and image format are free text for the agent. A channel without `limit` or `format: own` has no length
check: ask the user which of the two it is. Every piece lists the extra channels it uses in `## Channels` of its
`sheet.md`; images of an extra channel are `.webp`, `.png` or `.jpg`.

## The check command

Build it from the note and from the piece's own `## Channels` (an option for a channel the piece does not list is a
usage error, exit 2). Each extra channel of the piece adds one option:

```
python3 .claude/skills/gw-media-content/scripts/check.py \
  [--task-prefixes INS,FLU] \
  [--limit mastodon=500]... [--own-format portal]... [--web-languages es,gl,en] \
  <dir>/YYYY-MM-DD/NN-<topic>
```

`--task-prefixes` carries the `Task prefixes` value; `--limit <channel>=N` is for each `limit: N` channel and
`--own-format <channel>` for each `format: own` channel; `--web-languages` carries `Web languages` when the piece
lists `web`. Options go before the folder.

## Reddit

The line `Reddit:` holds, per subreddit, the rules the user pasted and the date read. The piece's `sheet.md` needs them
under `### Rules of r/<subreddit>` with `Rules read:` at most `reddit.rules_days` (in `rules.json`) days before
the piece's date folder: copy them from the note when that holds; otherwise ask the user to paste them again. Rules
are never invented or fetched: Reddit blocks automatic readers.
