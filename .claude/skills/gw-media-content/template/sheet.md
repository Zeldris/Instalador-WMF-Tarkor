# Sheet: <topic> (YYYY-MM-DD)

The source of everything published for this piece. What is not here, with its source, does not go out in the channels.
Piece folder: `<dir>/YYYY-MM-DD/NN-<topic>/` (NN = number of the piece of the day).

Languages: es, en

## Channels

- x
- reddit
- linkedin
- discord
- web

## What is told

- **In one sentence (for who uses it):** {{…}}
- **In one sentence (technical):** {{…}}
- **Status:** {{released in version X / merged on YYYY-MM-DD / in development}}

## Verified facts

| Fact | Source |
|---|---|
| {{fact}} | {{file, PR, CHANGELOG or link where it is verified}} |

## Reddit

Only if `reddit` is in `## Channels`. For each subreddit, a `Subreddit:` line and, below it, a section
`### Rules of r/<name>` with the rules pasted as they are (200 characters at least). Read the rules and note the day:
`Rules read:` cannot be in the future or older than 90 days (counted from the date folder of the piece).
The three field lines go before the first `###`, and the pasted text cannot contain `#` headings (paste them as
normal lines): a heading cuts the block.

- **Subreddit:** r/{{subreddit}}
- **Rules read:** YYYY-MM-DD
- **Self-promotion:** {{what the rules say about promoting your own work, and how this piece complies}}

### Rules of r/{{subreddit}}

{{paste the subreddit rules here, as they are}}

## Images

One row for each file of `media/` that is used (`.webp` for X, Discord and the web, `.png` for LinkedIn, `.pdf` for a
LinkedIn carousel). The alt text describes what is seen of the piece, in the format `es: texto / en: text`.
The first language of `Languages:` uses `media/<n>.webp`; another language may have its own image
`media/<n>.<language>.webp` (source `<n>.<language>.html`), with its row and the alt text in that language.

| Image | Alt text | Channels |
|---|---|---|
| `media/card.webp` | es: {{qué se ve}} / en: {{what is shown}} | x, discord, web |
| `media/card.png` | es: {{qué se ve}} / en: {{what is shown}} | linkedin |

## Internal use

What helps the team and is not published: task ids, branches, PRs and notes. None of this goes in the channels.

- {{…}}

## Published

| Channel | Language | Date | Link |
|---|---|---|---|
