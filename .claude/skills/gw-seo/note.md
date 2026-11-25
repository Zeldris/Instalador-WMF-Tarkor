# Project note of gw-seo

The note is `.claude/gw/gw-seo.md` in the project: `key: value` lines (keys in English), plus free text for what the
keys do not cover. The workflow neither creates nor overwrites it. Without it the defaults apply and you say so once.

| Key | Default | Holds |
|---|---|---|
| Build command | `npm run build` | the command that produces the static site |
| Build dir | `dist` | the folder `check_seo.py` reads |
| Site | the `Sitemap:` line of `robots.txt` | the absolute base URL, ending in `/` |
| Languages | the hreflang values found | the languages every page must exist in (ISO 639-1, comma-separated) |
| Ignore | none | extra globs for `--ignore` (`404.html`, `google*.html` and `assets/*` are always ignored) |
| Generator | none | the source files that write the `<head>`, the sitemap and `robots.txt`: where fixes go |
| Rules | none | the project's own SEO rules (a review checklist, a research note) |
| Limits | the defaults of `check_seo.py` | thresholds the project changes: `--title-min` 10, `--title-max` 60, `--description-min` 50, `--description-max` 160, `--max-html-bytes` 2097152, `--lastmod-same-min` 4 |
| Default ignore | `404.html`, `google*.html`, `assets/*` | replaces them with `--default-ignore GLOB` (once per glob; `--default-ignore ""` for none) |

Every row that maps to a flag is read by you from the note and passed on the command line: the script reads no project
file, and `.claude/gw.json` has no key for it. Say in the note the exact command the project runs, for example
`python3 .claude/skills/gw-seo/scripts/check_seo.py dist --title-max 70 --ignore 'drafts/*'`.
