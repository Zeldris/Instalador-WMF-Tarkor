#!/usr/bin/env python3
"""gw-media-content: checks a piece folder before anything is published.

    python3 check.py [--task-prefixes A,B,...] [--limit channel=N]... [--own-format channel]...
                     [--web-languages es,gl,en] <dir>/YYYY-MM-DD/NN-<topic> [more folders]

A folder argument may also be a date folder or the whole <dir> (default docs/media): every piece below it is
checked. No config: the per-network limits are read from ../rules.json.

Piece layout:
    sheet.md              facts with their source; sections `## Channels` (one channel per line), `## Images`
                          (table: Image | Alt text `es: ... / en: ...` | Channels: every channel listed
                          there needs an `Image:` line pointing to the file, and the other way round), `## Published`;
                          the line `Languages: es, en` (mandatory; any ISO 639-1 code, two lowercase letters; the first
                          one is the main language); channel names are lowercase [a-z0-9-]+
    <channel>.md          one per channel in `## Channels`, with one `## es` / `## en` section per language
                          (a `##` heading that is not a language ends the section: use `###` inside a post);
                          `Image: media/<name>.webp` lines say which render goes with the post (.png for LinkedIn)
    media/source/         sources: .html .svg .png .jpg .jpeg
    media/                renders: <name>.webp + <name>-mini.webp (every channel but LinkedIn), <name>.png (LinkedIn
                          takes .png, .jpg and .gif), or <name>.pdf (LinkedIn document carousel)
Images per language: the first language of `Languages:` uses `media/<name>.webp` (no suffix); any other language may
have its own `media/<name>.<lang>.webp` (+ `<name>.<lang>-mini.webp`, rendered from `source/<name>.<lang>.html`). An
`Image:` line inside a `## <lang>` section may point to the plain file or to the `.<lang>.` file of that same language;
the `## Images` table may list both (the `.<lang>.` row needs the alt text only in its language). A `.<lang>.` suffix
for a language that is not in `Languages:` (or the suffix of the first language) is an error.
Reddit: with reddit.md, `## Reddit` in sheet.md holds `Subreddit:` lines (r/<name>, one or several), `Rules read:`
(YYYY-MM-DD, not in the future and at most `reddit.rules_days` days old, counted at the date folder of the piece) and
`Self-promotion:`, all before the first `###`; and, for every subreddit, a subsection `### Rules of r/<name>` with the
rules text pasted as is (at least `reddit.rules_min_chars` characters once whitespace is collapsed; the block
ends at the next line that starts with `##`, so the pasted text cannot contain `#` headings: paste them as plain lines).
Web: web.md feeds the project's website and holds one ```json block (copy template/web.md): «status» ("draft",
which the skill writes; "ready" is the user's go to publish), «date» (YYYY-MM-DD), «text» {lang: text} and the
optional «wall» {title {lang}, body [{lang}], images [{file, alt {lang}}]}. The keys of «text» are the
languages of web.md: every one of `Languages:` plus any other the site needs; every other {lang: text} map has exactly
those. «file» is a render (media/<name>.webp) or {lang: render}; a `## Images` row that lists web needs its path
in «wall.images». With --web-languages es,gl,en the languages of «text» must be exactly those.
Known channels: x, reddit, linkedin, discord (limits in rules.json) and web. Any other ("extra") channel listed in `## Channels`
has its file `<channel>.md` and takes images .webp, .png and .jpg (`extra_channel.image_formats`). Without options it gets
the generic checks only: template gaps, jargon, `Image:` lines and a `## <lang>` section per language, with no length
limit. Options (before the folders, the first two repeatable):
    --limit channel=N         each language section of <channel>.md has at most N characters (plain count, `Image:`
                              lines excluded)
    --own-format channel      <channel>.md is consumed by another system (e.g. a JSON block for a website): it must exist
                              and not be empty; no `## <lang>` sections and no length check (template gaps and jargon
                              are still looked for); a `## Images` row that lists it needs the image path
                              (`media/x.webp`) somewhere in the file's text, instead of an `Image:` line
    --web-languages es,gl,en  the exact languages of «text» in web.md (the site's languages)
    --task-prefixes A,B       extra task-id prefixes the jargon check looks for (INS,FLU)
A known channel in --limit or --own-format, the same channel in both, or a channel (web for --web-languages) that
no checked piece lists under `## Channels` is a usage error (exit 2).

Old layout (0.x compatibility): a piece with `ficha.md` and no `sheet.md` (Spanish headings, `medios/`, the Spanish
keys of web.md) is checked on a translated copy, with a warning on stderr; the old option names --prefijos-tarea,
--limite, --formato-propio and --idiomas-web are accepted with a warning too.

web.md in 0.x carries the English keys and the old Spanish ones (estado with borrador/listo, fecha, texto, muro,
titulo, cuerpo, imagenes, archivo) with the same values, so a website that reads the old ones keeps working; they
are removed in 1.0. If both are there they must match (a mismatch is a problem); only the English ones pass silently;
only the Spanish ones pass with a warning on stderr that asks for the English ones too.

Prints OK, or one line per problem with the fix; exit 1 on any problem (2 on bad usage).
"""
import json
import re
import shutil
import struct
import sys
import tempfile
import unicodedata
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES_FILE = HERE.parent / "rules.json"
KNOWN = ("x", "reddit", "linkedin", "discord", "web")
LANG = re.compile(r"[a-z]{2}")  # ISO 639-1, any code
CHANNEL = re.compile(r"[a-z0-9-]+")
LANG_SUFFIX = re.compile(r"\.([a-z]{2})(?:-mini)?\.[A-Za-z0-9]+$")  # media/<name>.<lang>.webp, <name>.<lang>-mini.webp
SOURCE_EXTS = (".html", ".svg", ".png", ".jpg", ".jpeg")  # the same list as render.mjs
URL = re.compile(r"https?://\S+")
URL_END = ".,;:!?)]}»\"'"  # punctuation that closes a sentence, not part of a link
RENDER = "node .claude/skills/gw-media-content/scripts/render.mjs"  # the installed path in a project
BASE_FORMAT = (".webp",)  # every channel without `image_formats` in rules.json
RENDERS = re.compile(r"^media/[^/]+\.(?:webp|png|jpg|gif|pdf)$")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
PIECE_DIR = re.compile(r"^\d{2}-[a-z0-9][a-z0-9-]*$")
# A lone … is a gap only when it is a whole line (or the whole value after a `label:`), not a word in prose.
GAP = re.compile(r"\{\{[^}]*\}\}|(?m:^[ \t>*_-]*(?:\*{0,2}[^\n:]{1,40}:\*{0,2}[ \t]*)?…[ \t]*$)|<topic>|YYYY-MM-DD")
IMAGE_LINE = re.compile(r"(?mi)^[ \t>*_-]*Image:[ \t]*(.*)$")
# Internal jargon: finding numbers (P3, F12) named as findings, task ids with a known prefix (QA-215), branch names,
# WIP: markers. A link is never read for jargon, and AES-256, WPA-3, AK-47, P1/P2 or F5 in prose pass. The prefixes
# are the generic ones; a project adds its own with --task-prefixes A,B,... (its INS-3 or FLU-12 ids).
TASK_PREFIXES = ("QA", "TASK", "TICKET", "ISSUE", "BUG", "JIRA", "GW", "EPIC", "STORY")
JARGON = (
    re.compile(r"\b(?:claude|feat|fix|chore|hotfix|release)/[\w./-]*\w|\bccr-[\w-]*\w|\bWIP:"),
    re.compile(r"(?i:\b(?:hallazgos?|findings?|propuestas?|proposals?|ítems?|items?))[ \t]+#?([PF]\d{1,3})\b"
               r"|[\[(]([PF]\d{1,3})[\])]"),
)
# Every rules.json key the script reads ("channel.key"); load_rules fails closed when one is missing.
RULE_KEYS = (
    "x.length", "x.url_weight", "x.wide_symbol_weight", "x.thread_posts", "x.image_bytes", "x.alt_max",
    "reddit.title", "reddit.rules_days", "reddit.rules_min_chars",
    "extra_channel.image_formats",
    "linkedin.length", "linkedin.image_pixels", "linkedin.image_formats", "linkedin.alt_max",
    "linkedin.document_bytes", "linkedin.document_pages",
    "discord.message", "discord.image_bytes", "discord.alt_max",
)


class IncompleteRules(Exception):
    pass


def validate_rules(rules: dict):
    for key in RULE_KEYS:
        channel, k = key.split(".")
        r = rules.get(channel, {}).get(k)
        if not isinstance(r, dict) or r.get("value") is None:
            raise IncompleteRules(f"rules.json lacks {key}; restore it")


def load_rules(path=RULES_FILE) -> dict:
    try:
        rules = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise IncompleteRules(f"rules.json cannot be read ({e}); restore it") from None
    validate_rules(rules)
    return rules


def rule(rules: dict, channel: str, key: str):
    """Value of a rule, or None when the channel or the rule is not in rules.json (RULE_KEYS are always there)."""
    return rules.get(channel, {}).get(key, {}).get("value")


def formats(rules: dict, channel: str) -> tuple:
    if channel not in KNOWN:
        return tuple(rule(rules, "extra_channel", "image_formats"))
    return tuple(rule(rules, channel, "image_formats") or BASE_FORMAT)


def jargon_patterns(prefixes=()) -> tuple:
    """The jargon patterns: the fixed ones and the task ids with the generic prefixes plus the project's own."""
    every = dict.fromkeys(TASK_PREFIXES + tuple(prefixes))
    return (re.compile(r"\b(?:" + "|".join(map(re.escape, every)) + r")-\d{1,5}\b"),) + JARGON


def jargon(text: str, prefixes=()) -> list:
    text = URL.sub(" ", text)
    return sorted({next(g for g in m.groups() if g) if m.groups() else m.group(0)
                   for p in jargon_patterns(prefixes) for m in p.finditer(text)})


def x_weight(c: str) -> int:
    """twitter-text weight: ranges 0-4351, 8192-8205, 8208-8223 and 8242-8247 weigh 1, the rest 2."""
    o = ord(c)
    if o <= 4351 or 8192 <= o <= 8205 or 8208 <= o <= 8223 or 8242 <= o <= 8247:
        return 1
    return 2


def _emoji_base(c: str) -> bool:
    o = ord(c)
    return (0x1F000 <= o <= 0x1FAFF or 0x2190 <= o <= 0x21FF or 0x2300 <= o <= 0x23FF or 0x25A0 <= o <= 0x27BF
            or 0x2900 <= o <= 0x297F or 0x2B00 <= o <= 0x2BFF
            or o in (0xA9, 0xAE, 0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D, 0x3297, 0x3299))


def _emoji_end(text: str, i: int) -> int:
    """Index after the emoji sequence that starts at i (i + 1 when it is a single character)."""
    n, c = len(text), text[i]
    if 0x1F1E6 <= ord(c) <= 0x1F1FF:  # a flag: two regional indicators
        return i + 2 if i + 1 < n and 0x1F1E6 <= ord(text[i + 1]) <= 0x1F1FF else i + 1
    if c in "0123456789#*":  # a keycap: digit, optional FE0F, 20E3
        j = i + 2 if i + 1 < n and text[i + 1] == "\ufe0f" else i + 1
        return j + 1 if j < n and text[j] == "\u20e3" else i + 1
    if not _emoji_base(c):
        return i + 1
    j = i + 1
    while True:
        while j < n and (text[j] in "\ufe0f\u20e3" or 0x1F3FB <= ord(text[j]) <= 0x1F3FF or 0xE0020 <= ord(text[j]) <= 0xE007F):
            j += 1  # variation selector, keycap, skin tone, tag characters
        if j + 1 < n and text[j] == "\u200d" and _emoji_base(text[j + 1]):  # a ZWJ chain (family, profession)
            j += 2
            continue
        return j


def x_length(text: str, url_weight: int, wide_weight: int) -> int:
    """X's weighted count: a link weighs url_weight (the punctuation that closes a sentence after it does not belong to
    it); an emoji sequence (flag, emoji with a skin tone or variation selector, ZWJ family) is one block of
    wide_weight; any other wide character weighs wide_weight; a variation selector on its own weighs 0."""
    def link(m):
        url = m.group(0)
        return "x" * url_weight + url[len(url.rstrip(URL_END)):]
    text = unicodedata.normalize("NFC", URL.sub(link, text))
    total, i = 0, 0
    while i < len(text):
        j = _emoji_end(text, i)
        if j > i + 1:
            total += wide_weight
            i = j
            continue
        c, i = text[i], i + 1
        if c != "\ufe0f":
            total += wide_weight if x_weight(c) == 2 else 1
    return total


def sections(text: str) -> dict:
    """Splits a channel file by its `## es` / `## en` headings. Any other `##` heading ends the language section."""
    parts, current = {}, None
    for line in text.splitlines():
        t = line.strip()
        m = re.match(r"^##\s+([a-z]{2})\s*$", t)
        if m:
            current = m.group(1)
            parts.setdefault(current, [])
        elif re.match(r"^##\s+\S", t):
            current = None
        elif current:
            parts[current].append(line)
    return {k: "\n".join(v) for k, v in parts.items()}


def repeated_languages(text: str) -> list:
    every = re.findall(r"(?m)^##\s+([a-z]{2})\s*$", text)
    return sorted({i for i in every if every.count(i) > 1})


def section_of(text: str, title: str) -> str:
    m = re.search(r"(?ms)^##\s+" + re.escape(title) + r"\s*$(.*?)(?=^## |\Z)", text)
    return m.group(1) if m else ""


def field(text: str, *names) -> str:
    for n in names:
        m = re.search(r"(?mi)^[\s>*-]*\*{0,2}" + re.escape(n) + r"[ \t]*:[ \t]*\*{0,2}[ \t]*(.*)$", text)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return ""


def requested_channels(sheet: str) -> list:
    out = []
    for line in section_of(sheet, "Channels").splitlines():
        c = line.strip().lstrip("-*").strip().strip("`")
        if c:
            out.append(c)
    return out


def without_images(text: str) -> str:
    return IMAGE_LINE.sub("", text).strip()


X_MARK = re.compile(r"(?m)^\*\*\d+/(?:\d+)?\*\*\s*")  # **1/** or **1/4**


def x_posts(section: str):
    """(text before the first marker, posts). Each post starts with **n/** or **n/m**; without markers the whole
    section is one post."""
    chunks = X_MARK.split(without_images(section))
    if len(chunks) == 1:
        return "", ([chunks[0].strip()] if chunks[0].strip() else [])
    return chunks[0].strip(), [t.strip() for t in chunks[1:] if t.strip()]


# ---- image headers (no Pillow) ----

def dimensions(path: Path):
    """(width, height) of a WebP, PNG, JPEG or GIF, or None when the header is truncated or not understood."""
    d = path.read_bytes()
    try:
        if d[:8] == b"\x89PNG\r\n\x1a\n":
            if len(d) < 24 or d[12:16] != b"IHDR":
                return None
            return _with_area(*struct.unpack(">II", d[16:24]))
        if d[:6] in (b"GIF87a", b"GIF89a"):
            return _with_area(*struct.unpack("<HH", d[6:10]))
        if d[:4] == b"RIFF" and d[8:12] == b"WEBP":
            if len(d) < 20 or len(d) < struct.unpack("<I", d[4:8])[0] + 8:
                return None  # the RIFF size says more bytes than the file has: truncated
            kind = d[12:16]
            if kind == b"VP8X" and len(d) >= 30:
                return _with_area(1 + int.from_bytes(d[24:27], "little"), 1 + int.from_bytes(d[27:30], "little"))
            if kind == b"VP8L" and len(d) >= 25 and d[20] == 0x2F:
                bits = int.from_bytes(d[21:25], "little")
                return _with_area((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
            if kind == b"VP8 " and len(d) >= 30 and d[23:26] == b"\x9d\x01\x2a":
                return _with_area(int.from_bytes(d[26:28], "little") & 0x3FFF, int.from_bytes(d[28:30], "little") & 0x3FFF)
        if d[:2] == b"\xff\xd8":
            i = 2
            while i + 9 < len(d):
                if d[i] != 0xFF:
                    i += 1
                    continue
                marker = d[i + 1]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
                    i += 1 if marker == 0xFF else 2
                    continue
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    h, w = struct.unpack(">HH", d[i + 5:i + 9])
                    return _with_area(w, h)
                i += 2 + struct.unpack(">H", d[i + 2:i + 4])[0]
    except (struct.error, IndexError):
        pass
    return None


def _with_area(wide: int, height: int):
    return (wide, height) if wide > 0 and height > 0 else None


def pdf_pages(path: Path):
    """Page count of a PDF (page objects, else the largest /Count), or None."""
    d = path.read_bytes()
    if not d.startswith(b"%PDF"):
        return None
    n = len(re.findall(rb"/Type\s*/Page(?![A-Za-z])", d))
    if n:
        return n
    counts = [int(x) for x in re.findall(rb"/Count\s+(\d+)", d)]
    return max(counts) if counts else None


def alt_by_language(cell: str) -> dict:
    out = {}
    for m in re.finditer(r"(?:^|\s/\s)\s*([a-z]{2})\s*:\s*(.*?)(?=\s/\s+[a-z]{2}\s*:|$)", cell.strip()):
        out[m.group(1)] = m.group(2).strip()
    return out


def image_table(sheet: str):
    """{path: (alt cell, channels cell)} from `## Images`, or None when the section is missing."""
    if not re.search(r"(?m)^##\s+Images\s*$", sheet):
        return None
    rows = {}
    for row in section_of(sheet, "Images").splitlines():
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0] in ("Image", "") or set(cells[0]) <= set("-: "):
            continue
        rows[cells[0].strip("`")] = (cells[1], cells[2] if len(cells) > 2 else "")
    return rows


# ---- the checks ----

def _gap(m) -> str:
    t = m.group(0).strip()
    return "…" if t.endswith("…") and "{{" not in t else t


def check_channel(channel, text, languages, rules, prefixes=(), limit=None):
    f = []
    name = channel + ".md"
    parts = sections(text)
    for i in languages:
        if not parts.get(i, "").strip():
            f.append(f"{name}: no «## {i}» section; add it with the post in that language")
    for i in repeated_languages(text):
        f.append(f"{name}: «## {i}» appears more than once; merge the sections into one")
    for i in parts:
        if i not in languages:
            f.append(f"{name}: language «{i}» is not in the piece; remove the section or add it to «Languages:» in sheet.md")
    for j in jargon(text, prefixes):
        f.append(f"{name}: internal jargon «{j}»; move it to «## Internal use» in sheet.md and remove it from the post")
    for m in GAP.finditer(text):
        f.append(f"{name}: template gap «{_gap(m)}» left; write the text")
    for i in languages:
        t = without_images(parts.get(i, ""))
        if not t:
            continue
        if channel == "x":
            n_max, mp = rule(rules, "x", "length"), rule(rules, "x", "thread_posts")
            url_weight, wide = rule(rules, "x", "url_weight"), rule(rules, "x", "wide_symbol_weight")
            before, posts = x_posts(t)
            if before:
                f.append(f"{name} ({i}): text before «**1/**»; start every post with a marker (**1/**, **2/**…) "
                         "or move that text into the first post")
            if not mp["min"] <= len(posts) <= mp["max"]:
                f.append(f"{name} ({i}): {len(posts)} posts; a thread has {mp['min']} to {mp['max']} (**1/**, **2/**…); "
                         "split or merge the posts")
            for k, p in enumerate(posts, 1):
                n = x_length(p, url_weight, wide)
                if n > n_max:
                    f.append(f"{name} ({i}) post {k}: {n} weighted characters (max {n_max}; a link counts "
                             f"{url_weight}, an emoji {wide}); shorten it by {n - n_max}")
        elif channel == "linkedin":
            mx = rule(rules, "linkedin", "length")
            if len(t) > mx:
                f.append(f"{name} ({i}): {len(t)} characters (max {mx}); shorten it by {len(t) - mx}")
        elif channel == "discord":
            mx = rule(rules, "discord", "message")
            for k, b in enumerate(re.split(r"(?m)^---\s*$", t), 1):
                if len(b.strip()) > mx:
                    f.append(f"{name} ({i}) message {k}: {len(b.strip())} characters (max {mx}); "
                             "split it with a line containing only ---")
        elif channel == "reddit":
            m = re.search(r"(?mi)^\*\*(?:Title|Título|Titulo)\s*:\*\*[ \t]*(.+)$", t)
            mx = rule(rules, "reddit", "title")
            if not m:
                f.append(f"{name} ({i}): no title; add a line «**Title:** …»")
            elif len(m.group(1).strip()) > mx:
                f.append(f"{name} ({i}): title of {len(m.group(1).strip())} characters (max {mx}); shorten it")
        elif channel not in KNOWN and limit and len(t) > limit:
            f.append(f"{name} ({i}): {len(t)} characters (max {limit}, set with --limit {channel}={limit}); "
                     f"shorten it by {len(t) - limit}")
    return f


def check_own_format(channel, text, prefixes=()):
    """A channel set with --own-format: its file feeds another system, so there are no language sections and no
    length; it must not be empty, and template gaps and jargon are still looked for."""
    name = channel + ".md"
    if not text.strip():
        return [f"{name}: empty (channel set with --own-format); write the content the other system reads"]
    f = [f"{name}: internal jargon «{j}»; move it to «## Internal use» in sheet.md and remove it from the content"
         for j in jargon(text, prefixes)]
    f += [f"{name}: template gap «{_gap(m)}» left; write the text" for m in GAP.finditer(text)]
    return f


JSON_BLOCK = re.compile(r"(?ms)^```json[ \t]*\n(.*?)^```[ \t]*$")
WEB_KEYS = ("status", "date", "text", "wall")
WALL_KEYS = ("title", "body", "images")
WEB_STATUSES = ("draft", "ready")


def _map(value, where, langs) -> list:
    """The problems of a {lang: text} map that must hold exactly the languages of «text», each with text."""
    if not isinstance(value, dict):
        return [f"web.md: «{where}» must be an object with one text per language ({', '.join(langs)}); write it as "
                '{"' + '": "…", "'.join(langs) + '": "…"}']
    f = [f"web.md: «{where}» has no «{i}»; add its text in that language" for i in langs if i not in value]
    f += [f"web.md: «{where}» has «{i}», which is not in «text»; remove it or add «{i}» to «text»"
          for i in value if i not in langs]
    f += [f"web.md: «{where}.{i}» is empty; write the text" for i in langs
          if i in value and (not isinstance(value[i], str) or not value[i].strip())]
    return f


def _web_files(file, where, langs, folder, languages, command):
    """(problems, paths) of a wall image «file»: one render for every language, or a {lang: render} map."""
    if isinstance(file, dict):
        f = _map(file, where, langs)
        pairs = [(i, r) for i, r in file.items() if i in langs and isinstance(r, str) and r.strip()]
    elif isinstance(file, str) and file.strip():
        f, pairs = [], [(None, file)]
    else:
        return [f"web.md: «{where}» must be a render path (media/<name>.webp) or one per language; write it"], []
    paths = []
    for lang, path in pairs:
        path = path.strip()
        if not RENDERS.match(path):
            f.append(f"web.md: «{where}» is «{path}», not a render; point to media/<name>.webp")
            continue
        own = language_of_file(path)
        p = suffix_problem(path, languages, "web.md")
        if p:
            f.append(p)
        elif lang and own and own != lang:
            f.append(f"web.md: «{path}» is the image of «{own}» but sits under «{lang}» in «{where}»; move it")
        if not (folder / path).is_file():
            f.append(f"web.md: «{path}» does not exist; render it ({command})")
        if path not in paths:  # a missing render is reported once, here, not again by its row in «## Images»
            paths.append(path)
    return f, paths


def check_web(text, languages, prefixes=(), folder=Path("."), web_languages=None):
    """web.md feeds a website: one ```json block with «status» ("draft" until the user writes "ready"), «date»,
    «text» {lang: text} and the optional «wall» {title, body[], images[{file, alt}]}. The languages are the
    keys of «text»: those of `Languages:` and any other the site needs (exactly --web-languages when it is set); every other
    {lang: text} map holds the same ones. Returns (problems, the image paths of «wall.images»)."""
    command = f"{RENDER} {folder}"
    f = [f"web.md: internal jargon «{j}»; move it to «## Internal use» in sheet.md and remove it from the content"
         for j in jargon(text, prefixes)]
    f += [f"web.md: template gap «{_gap(m)}» left; write the text" for m in GAP.finditer(text)]
    blocks = JSON_BLOCK.findall(text)
    if len(blocks) != 1:
        found = "no ```json block" if not blocks else f"{len(blocks)} ```json blocks"
        return f + [f"web.md: {found}; keep exactly one, as in the template (template/web.md)"], []
    try:
        data = json.loads(blocks[0])
    except ValueError as e:
        return f + [f"web.md: the ```json block is not valid JSON ({e}); fix it"], []
    if not isinstance(data, dict):
        return f + ["web.md: the ```json block must be an object with " + ", ".join(WEB_KEYS) + "; copy the template"], []
    data, mismatches, alone = unify_web(data)
    f += mismatches
    if alone:
        print(f"check.py: warning: {folder}/web.md has Spanish keys (estado, fecha, texto, muro...) without the English "
              "ones (status, date, text, wall...); in 0.x write both with the same values (the old ones go away in 1.0)",
              file=sys.stderr)
    f += [f"web.md: unknown key «{k}»; remove it (keys: {', '.join(WEB_KEYS)})" for k in data if k not in WEB_KEYS]
    f += [f"web.md: no «{k}»; add it as in the template (template/web.md)" for k in WEB_KEYS[:3] if k not in data]
    status = data.get("status")
    if "status" in data and status not in WEB_STATUSES:
        f.append(f"web.md: «status» is {json.dumps(status, ensure_ascii=False)}; write \"draft\" (the skill leaves "
                 "it so) or \"ready\" (the user's go to publish)")
    day = data.get("date")
    try:
        ok = isinstance(day, str) and bool(DATE_RE.fullmatch(day)) and bool(date.fromisoformat(day))
    except ValueError:
        ok = False
    if "date" in data and not ok and day != "YYYY-MM-DD":  # the template's date is reported as a gap
        f.append(f"web.md: «date» is {json.dumps(day, ensure_ascii=False)}; write the publication date as "
                 "\"YYYY-MM-DD\"")
    web_text = data.get("text")
    if not isinstance(web_text, dict) or not web_text:
        if "text" in data:
            f.append("web.md: «text» must be an object with one text per language ({\"es\": \"…\", \"en\": \"…\"}); "
                     "write it")
        return f, []
    langs = [i for i in web_text if LANG.fullmatch(i)]
    f += [f"web.md: «text» has the key «{i}»; use two-letter lowercase ISO 639-1 codes (es, en, gl)"
          for i in web_text if not LANG.fullmatch(i)]
    f += [f"web.md: «text» has no «{i}» (it is in «Languages:» of sheet.md); add its text" for i in languages
          if i not in web_text]
    if web_languages:
        listing = ",".join(web_languages)
        f += [f"web.md: «text» has no «{i}» (set with --web-languages {listing}); add its text" for i in web_languages
              if i not in web_text and i not in languages]
        f += [f"web.md: «text» has «{i}», which is not in --web-languages {listing}; remove it" for i in langs
              if i not in web_languages]
    f += _map({i: web_text[i] for i in langs}, "text", langs)
    wall = data.get("wall")
    if wall is None:
        return f, []
    if not isinstance(wall, dict):
        return f + ["web.md: «wall» must be an object with title, body and images; copy it from the template"], []
    f += [f"web.md: unknown key «wall.{k}»; remove it (keys: {', '.join(WALL_KEYS)})" for k in wall
          if k not in WALL_KEYS]
    if "title" not in wall:
        f.append("web.md: «wall» has no «title»; add one title per language")
    else:
        f += _map(wall["title"], "wall.title", langs)
    body = wall.get("body")
    if "body" in wall:
        if not isinstance(body, list) or not body:
            f.append("web.md: «wall.body» must be a list of paragraphs, each one with a text per language; write "
                     "one or remove the key")
        else:
            for n, paragraph in enumerate(body):
                f += _map(paragraph, f"wall.body[{n}]", langs)
    paths = []
    images = wall.get("images")
    if "images" in wall and not isinstance(images, list):
        f.append("web.md: «wall.images» must be a list of {file, alt}; write it or remove the key")
    for n, img in enumerate(images if isinstance(images, list) else []):
        where = f"wall.images[{n}]"
        if not isinstance(img, dict):
            f.append(f"web.md: «{where}» must be an object with file and alt; write it")
            continue
        f += [f"web.md: unknown key «{where}.{k}»; remove it (keys: file, alt)" for k in img if k not in ("file", "alt")]
        f += [f"web.md: «{where}» has no «{k}»; add it" for k in ("file", "alt") if k not in img]
        if "alt" in img:
            f += _map(img["alt"], f"{where}.alt", langs)
        if "file" in img:
            p, r = _web_files(img["file"], f"{where}.file", langs, folder, languages, command)
            f += p
            paths += [x for x in r if x not in paths]
    return f, paths


SUBREDDIT_NAME = re.compile(r"[A-Za-z0-9_]{2,21}")
BLOCK_END = re.compile(r"(?m)^#{2,}(?:[ \t]|$)")
RULES_BLOCK = re.compile(r"(?mi)^###[ \t]+Rules[ \t]+of[ \t]+(?:/?r/)?(\S+)[ \t]*$")


def reddit_header(sheet: str) -> str:
    """The `## Reddit` section up to its first `###` subsection (the whole sheet when there is no such section)."""
    section = section_of(sheet, "Reddit")
    return re.split(r"(?m)^###", section)[0] if section else sheet


def subreddits(header: str):
    """([names], [problems]) from the `Subreddit:` lines; a line with a template gap is skipped (the gap is reported)."""
    names, problems = [], []
    for m in re.finditer(r"(?mi)^[ \t>*-]*\*{0,2}Subreddits?[ \t]*:[ \t]*\*{0,2}[ \t]*(.*)$", header):
        value = m.group(1).strip()
        if "{{" in value or value in ("", "…"):
            continue
        for tok in re.split(r"[,;\s]+", value):
            name = re.sub(r"^/?r/", "", tok.strip("`*_ "), flags=re.I)
            if not name:
                continue
            if not SUBREDDIT_NAME.fullmatch(name):
                problems.append(f"sheet.md: «Subreddit:» «{tok}» is not a subreddit name; write it as r/<name>")
            elif name.lower() not in [n.lower() for n in names]:
                names.append(name)
    return names, problems


def rules_blocks(section: str):
    """({name.lower(): pasted text}, [names repeated]) from the `### Rules of r/<name>` subsections."""
    chunks = RULES_BLOCK.split(section)
    blocks, repeated = {}, []
    for name, text in zip(chunks[1::2], chunks[2::2]):
        text = BLOCK_END.split(text, 1)[0]  # the block ends at the next heading of level 2 or more
        k = name.strip("`*_").lower()
        if k in blocks:
            repeated.append(name)
        blocks[k] = (blocks.get(k, "") + " " + text).strip() if k in blocks else text
    return blocks, repeated


def check_reddit(sheet, rules=None, today=None, piece_day=None):
    """piece_day: the date of the piece's folder; `Rules read:` is aged against it (against today when None), and a
    date after today is always in the future."""
    rules = rules or load_rules()
    today = today or date.today()
    reference = piece_day or today
    f = []
    header = reddit_header(sheet)
    for label, names in (("Subreddit", ("Subreddit", "Subreddits")), ("Rules read", ("Rules read",)),
                              ("Self-promotion", ("Self-promotion",))):
        v = field(header, *names)
        if not v or v == "…":
            f.append(f"sheet.md: reddit.md needs «{label}:» in sheet.md; put the field before the first «###» block of "
                     f"«## Reddit», paste the subreddit rules and write the «{label}:» line")
        elif label == "Rules read":
            m = DATE_RE.search(v)
            try:
                day_read = date.fromisoformat(m.group(0))
            except (AttributeError, ValueError):
                f.append(f"sheet.md: «Rules read:» «{v}» has no valid YYYY-MM-DD date; write the day you read the rules")
                continue
            age_days, mx = (reference - day_read).days, rule(rules, "reddit", "rules_days")
            if day_read > today:
                f.append(f"sheet.md: «Rules read:» «{v}» is in the future; write the day you read the rules")
            elif age_days > mx:
                f.append(f"sheet.md: «Rules read:» «{v}» is {age_days} days old (max {mx}); read the rules again, paste "
                         "them under «### Rules of r/<name>» and write today's date"
                         + (f" (the age is counted at the piece date {reference})" if reference != today else ""))
    names, problems = subreddits(header)
    f += problems
    value = field(header, "Subreddit", "Subreddits")
    if not names and not problems and value not in ("", "…") and "{{" not in value:
        f.append("sheet.md: no subreddit: write «- **Subreddit:** r/<name>» in «## Reddit» before the first «###» block")
    blocks, repeated = rules_blocks(section_of(sheet, "Reddit"))
    for r in repeated:
        f.append(f"sheet.md: «### Rules of r/{r}» appears more than once; merge the blocks into one")
    minimum = rule(rules, "reddit", "rules_min_chars")
    for n in names:
        text = re.sub(r"\s+", " ", blocks.get(n.lower(), "")).strip()
        if n.lower() not in blocks:
            f.append(f"sheet.md: no rules block for r/{n}; paste the rules text (at least {minimum} characters, copied from "
                     f"reddit.com/r/{n}/about/rules) under a «### Rules of r/{n}» heading inside «## Reddit» of sheet.md")
        elif len(text) < minimum:
            f.append(f"sheet.md: the rules block of r/{n} has {len(text)} characters (min {minimum}); paste the complete "
                     f"rules text under «### Rules of r/{n}» in «## Reddit» of sheet.md; the pasted text ends at the next "
                     "line starting with «##», so paste headings as plain lines without «#», and the «Subreddit:» fields "
                     "go before the first «###» block")
    for k in blocks:
        if "{{" not in k and k not in [n.lower() for n in names]:
            f.append(f"sheet.md: «### Rules of r/{k}» matches no «Subreddit:» line; add r/{k} to «Subreddit:» or remove "
                     "the block")
    return f


def channels_of_cell(cell: str) -> list:
    return [c for c in (x.strip("`*_ ").lower() for x in re.split(r"[,;\s]+", cell)) if c]


def language_of_file(path: str):
    """The language in a `.<lang>.` suffix of a file name (media/card.gl.webp, card.gl-mini.webp), or None."""
    m = LANG_SUFFIX.search(path.rsplit("/", 1)[-1])
    return m.group(1) if m else None


def suffix_problem(path: str, languages, where: str):
    """The error for a `.<lang>.` suffix that is not allowed (a language outside `Languages:`, or the first one)."""
    lang = language_of_file(path)
    if lang is None:
        return None
    if lang not in languages:
        return (f"{where}: «{path}» has the language suffix «.{lang}.» but «{lang}» is not in «Languages:» of sheet.md; "
                f"add it there or rename the file")
    if languages and lang == languages[0]:
        return (f"{where}: «{path}» has the suffix «.{lang}.» but «{lang}» is the first language and uses the file "
                f"without suffix; rename it to «{path.replace('.' + lang, '', 1)}»")
    return None


def check_images(folder, sheet, channel_texts, languages, rules, prefixes=(), own_format=(), web_paths=()):
    """web_paths: the image paths of «wall.images» in web.md (web.md has no `Image:` lines)."""
    f = []
    command = f"{RENDER} {folder}"
    table = image_table(sheet)
    if table is None:
        f.append("sheet.md: no «## Images» section; add the table | Image | Alt text | Channels |")
        table = {}
    # the `Image:` lines of each channel
    lines, pairs = {}, set()
    if "web" in channel_texts and web_paths:
        lines["web"] = list(web_paths)
    for channel, text in channel_texts.items():
        if channel == "web":
            continue
        for m in IMAGE_LINE.finditer(text):
            path = m.group(1).strip().strip("`*_ ")
            if not RENDERS.match(path):
                f.append(f"{channel}.md: «Image: {path}» is not a render; point to media/<name>{formats(rules, channel)[0]} "
                         "(or .pdf)")
            else:
                p = suffix_problem(path, languages, f"{channel}.md")
                if p:
                    f.append(p)
                lines.setdefault(channel, [])
                if path not in lines[channel]:
                    lines[channel].append(path)
                if not (folder / path).is_file():
                    f.append(f"{channel}.md: «Image: {path}» does not exist; render it ({command})")
    for channel, text in channel_texts.items():  # an `Image:` line of another language's file sits in the wrong section
        if channel == "web":
            continue
        for lang, section in sections(text).items():
            for m in IMAGE_LINE.finditer(section):
                path = m.group(1).strip().strip("`*_ ")
                other = language_of_file(path) if RENDERS.match(path) else None
                if other and other != lang and other in languages:
                    f.append(f"{channel}.md ({lang}): «{path}» is the image of «{other}» but sits in the «## {lang}» section; "
                             f"move the line to «## {other}»")
    for channel, paths in lines.items():
        for path in paths:
            if not (folder / path).is_file():
                continue
            if path not in table:
                f.append(f"{channel}.md: «{path}» is not in «## Images» of sheet.md; add a row with its alt text")
            elif channel not in channels_of_cell(table[path][1]):
                f.append(f"{channel}.md: «{path}» is not listed for «{channel}» in «## Images» of sheet.md; add «{channel}» "
                         "to the Channels cell of its row")
            pairs.add((channel, path))
    # the rows of `## Images`
    for path, (alt, cell) in table.items():
        if not path.startswith("media/"):
            continue
        by_language = alt_by_language(alt)
        p = suffix_problem(path, languages, "sheet.md")
        if p:
            f.append(p)
        own = language_of_file(path)
        for i in ([own] if own in languages[1:] else languages):  # a `.<lang>.` render needs its language's alt only
            if not by_language.get(i) or by_language[i] == "…":
                f.append(f"sheet.md: «{path}» has no alt text in «{i}»; write «{i}: …» in its alt cell (es: … / en: …)")
        for j in jargon(alt, prefixes):
            f.append(f"sheet.md: alt text of «{path}» has internal jargon «{j}»; remove it")
        if not (folder / path).is_file():
            f.append(f"sheet.md: «{path}» does not exist; render it ({command})")
        elif path.endswith(".webp"):
            mini = path.replace(".webp", "-mini.webp")
            if not (folder / mini).is_file():
                f.append(f"sheet.md: «{path}» has no -mini.webp; render it again ({command})")
            elif dimensions(folder / mini) is None:
                f.append(f"{mini}: not a valid image; render it again ({command})")
        for c in channels_of_cell(cell):
            if c == "web" and c in channel_texts and path not in lines.get(c, []):
                f.append(f"sheet.md: «{path}» lists channel «web» but no «file» in «wall.images» of web.md points to "
                         "it; add it there or remove «web» from the Channels cell")
            elif c in own_format and c in channel_texts and path not in channel_texts[c]:
                f.append(f"sheet.md: «{path}» lists channel «{c}» but {c}.md does not contain the path «{path}» (channel "
                         f"with its own format); write the path in the file or remove «{c}» from the Channels cell")
            elif c in channel_texts and c not in own_format and path not in lines.get(c, []):
                f.append(f"sheet.md: «{path}» lists channel «{c}» but {c}.md has no «Image: {path}» line; add the line "
                         f"or remove «{c}» from the Channels cell")
            if c in channel_texts and (folder / path).is_file():
                pairs.add((c, path))
    for channel, path in sorted(pairs):
        f += check_file(folder / path, path, channel, table.get(path, ("", ""))[0], rules, command)
    listed = set(table)
    media = folder / "media"
    loose = [x for e in ("webp", "png", "jpg", "gif", "pdf") for x in media.glob(f"*.{e}")]
    for img in sorted(loose):
        if not img.name.endswith("-mini.webp") and f"media/{img.name}" not in listed:
            f.append(f"media/{img.name}: not in «## Images» of sheet.md; add a row with its alt text or delete the file")
    sources = media / "source"
    for s in sorted(sources.glob("*")):
        suf = s.suffix.lower()
        if suf in SOURCE_EXTS:
            p = suffix_problem(f"media/source/{s.name}", languages, f"media/source/{s.name}")
            if p:
                f.append(p)
        if suf in (".html", ".svg") and "{{" in s.read_text(encoding="utf-8", errors="replace"):
            f.append(f"media/source/{s.name}: template gaps {{{{…}}}} left; fill them and render again")
        if suf in SOURCE_EXTS and not any((media / f"{s.stem}{e}").is_file() for e in (".webp", ".pdf")):
            f.append(f"media/source/{s.name}: not rendered; run {command}")
    return f


def check_file(path, rel, channel, alt, rules, command):
    f = []
    if rel.endswith(".pdf"):
        if channel != "linkedin":
            return [f"{channel}.md: «{rel}» is a PDF and only LinkedIn takes a document; use a "
                    f"{formats(rules, channel)[0]} render"]
        size, mx = path.stat().st_size, rule(rules, "linkedin", "document_bytes")
        if size > mx:
            f.append(f"{rel}: {size} bytes (LinkedIn max {mx}); export a lighter PDF")
        pages, mp = pdf_pages(path), rule(rules, "linkedin", "document_pages")
        if pages is None:
            f.append(f"{rel}: the page count cannot be read; render the PDF again ({command})")
        elif pages > mp:
            f.append(f"{rel}: {pages} pages (LinkedIn max {mp}); cut the carousel")
        return f
    allowed = formats(rules, channel)
    if Path(rel).suffix.lower() not in allowed:
        f.append(f"{channel}.md: «{rel}» is a {Path(rel).suffix.lower()} and {channel} takes {', '.join(allowed)}; "
                 f"point to media/<name>{allowed[0]} (the render writes it)")
    size, mx = path.stat().st_size, rule(rules, channel, "image_bytes")
    if mx and size > mx:
        f.append(f"{rel}: {size} bytes (max {mx} for {channel}); lower the quality or the size and render again")
    dim, mpx = dimensions(path), rule(rules, channel, "image_pixels")
    if dim is None:
        f.append(f"{rel}: not a valid image; render it again ({command})")
    elif mpx and dim[0] * dim[1] >= mpx:
        f.append(f"{rel}: {dim[0]}x{dim[1]} = {dim[0] * dim[1]} pixels (must be under {mpx} for {channel}); scale it down")
    amax = rule(rules, channel, "alt_max")
    if amax:
        for i, t in alt_by_language(alt).items():
            if len(t) > amax:
                f.append(f"sheet.md: alt text «{i}» of «{rel}» has {len(t)} characters (max {amax} for {channel}); shorten it")
    return f


def read_text(path: Path, rel: str):
    """(text, None), or (None, problem) when the file is not valid UTF-8 or cannot be read. A BOM is dropped."""
    try:
        return path.read_text(encoding="utf-8-sig"), None
    except UnicodeDecodeError:
        return None, f"{rel}: not valid UTF-8 text; open it in an editor and save it as UTF-8"
    except OSError as e:
        return None, f"{rel}: cannot be read ({e.strerror or e}); check the file and its permissions"


OLD_OPTIONS = {"--prefijos-tarea": "--task-prefixes", "--limite": "--limit", "--formato-propio": "--own-format",
               "--idiomas-web": "--web-languages"}
# 0.x compatibility: the Spanish headings, labels and web.md keys of a piece written before A8 (translated on a copy).
OLD_HEADINGS = {"Canales": "Channels", "Imágenes": "Images", "Publicado": "Published", "Uso interno": "Internal use"}
OLD_LABELS = (("Idiomas", "Languages"), ("Normas leídas", "Rules read"), ("Normas leidas", "Rules read"),
              ("Autopromoción", "Self-promotion"), ("Autopromocion", "Self-promotion"))
OLD_WEB_KEYS = {"estado": "status", "fecha": "date", "texto": "text", "muro": "wall", "titulo": "title",
                "cuerpo": "body", "imagenes": "images", "archivo": "file"}
OLD_WEB_STATUS = {"borrador": "draft", "listo": "ready"}


def old_sheet(text: str) -> str:
    """ficha.md (Spanish) as sheet.md (English): headings, labels, the image table header and the media/ paths."""
    for old, new in OLD_HEADINGS.items():
        text = re.sub(r"(?m)^(##[ \t]+)" + old + r"[ \t]*$", r"\g<1>" + new, text)
    for old, new in OLD_LABELS:
        text = re.sub(r"(?mi)^([\s>*-]*\*{0,2})" + old + r"([ \t]*:)", r"\g<1>" + new + r"\g<2>", text)
    text = re.sub(r"(?mi)^(###[ \t]+)Normas[ \t]+de([ \t])", r"\g<1>Rules of\g<2>", text)
    text = re.sub(r"(?m)^(\|[ \t]*)Imagen([ \t]*\|)", r"\g<1>Image\g<2>", text)
    return text.replace("medios/", "media/")


def old_web_data(value):
    if isinstance(value, dict):
        return {OLD_WEB_KEYS.get(k, k): old_web_data(v) for k, v in value.items()}
    if isinstance(value, list):
        return [old_web_data(v) for v in value]
    return value


def old_web(text: str) -> str:
    """web.md with the Spanish keys of its JSON block (estado, fecha, texto, muro...) as the English ones."""
    def block(m):
        try:
            data = json.loads(m.group(2))
        except ValueError:
            return m.group(0)
        data = old_web_data(data)
        if isinstance(data, dict) and data.get("status") in OLD_WEB_STATUS:
            data["status"] = OLD_WEB_STATUS[data["status"]]
        return m.group(1) + json.dumps(data, ensure_ascii=False, indent=2) + m.group(3)
    return re.sub(r"(?s)(```json[ \t]*\n)(.*?)(\n[ \t]*```)", block, text, count=1)


def unify_web(data, where=""):
    """(data with the English keys only, problems, whether an old key stood without its English one). A web.md of 0.x
    carries both spellings with the same values; each old key is checked against its English one at any depth."""
    if isinstance(data, list):
        out, f, alone = [], [], False
        for n, item in enumerate(data):
            d, p, a = unify_web(item, f"{where}[{n}]")
            out.append(d)
            f += p
            alone = alone or a
        return out, f, alone
    if not isinstance(data, dict):
        return data, [], False
    out, f, alone = {}, [], False
    for k, v in data.items():
        if k not in OLD_WEB_KEYS:
            out[k], p, a = unify_web(v, f"{where}.{k}" if where else k)
            f += p
            alone = alone or a
    for k, v in data.items():
        if k not in OLD_WEB_KEYS:
            continue
        name = OLD_WEB_KEYS[k]
        at = f"{where}.{name}" if where else name
        d, p, a = unify_web(v, at)
        if name == "status" and isinstance(d, str) and d in OLD_WEB_STATUS:
            d = OLD_WEB_STATUS[d]
        if name not in out:
            out[name], alone = d, True
            f += p
        elif out[name] != d:
            f.append(f"web.md: «{k}» and «{name}»{' of «' + where + '»' if where else ''} differ "
                     f"({json.dumps(v, ensure_ascii=False)} and {json.dumps(data[name], ensure_ascii=False)}); in 0.x "
                     f"both are written with the same value (the old keys go away in 1.0): fix «{name}» and "
                     f"«{k}» to match")
    return out, f, alone


def old_piece(folder: Path, tmp: Path) -> Path:
    """A translated copy of a piece folder written with the old Spanish names (ficha.md, medios/), under tmp."""
    copy = tmp / folder.resolve().parent.name / folder.resolve().name
    copy.mkdir(parents=True)
    for p in sorted(folder.iterdir()):
        if p.is_dir():
            if p.name in ("medios", "media"):
                shutil.copytree(p, copy / "media", dirs_exist_ok=True)
                if (copy / "media" / "fuente").is_dir() and not (copy / "media" / "source").exists():
                    (copy / "media" / "fuente").rename(copy / "media" / "source")
            continue
        if p.suffix != ".md":
            shutil.copy2(p, copy / p.name)
            continue
        text, error = read_text(p, p.name)
        if error:  # unreadable stays unreadable in the copy
            shutil.copy2(p, copy / ("sheet.md" if p.name == "ficha.md" else p.name))
            continue
        if p.name == "ficha.md":
            (copy / "sheet.md").write_text(old_sheet(text), encoding="utf-8")
        else:
            text = re.sub(r"(?mi)^([ \t>*_-]*)Imagen:", r"\g<1>Image:", text).replace("medios/", "media/")
            if p.name == "web.md":
                text = old_web(text)
            (copy / p.name).write_text(text, encoding="utf-8")
    return copy


def rename_old_options(args: list) -> list:
    """The old Spanish option names are accepted during 0.x, with a warning on stderr that gives the new name."""
    out = []
    for arg in args:
        name, eq, value = arg.partition("=")
        if name in OLD_OPTIONS:
            print(f"check.py: warning: {name} is deprecated; use {OLD_OPTIONS[name]}", file=sys.stderr)
            arg = OLD_OPTIONS[name] + eq + value
        out.append(arg)
    return out


def check(folder: Path, rules=None, prefixes=(), limits=None, own_format=(), today=None, web_languages=None) -> list:
    """The problems of one piece folder. limits {channel: max characters per language section} and own_format (channels
    whose file has its own format) are the --limit and --own-format options; today is the date `Rules read:` is
    measured against when the piece is not under a date folder (today); web_languages (--web-languages) are the exact
    languages of web.md."""
    limits, own_format = limits or {}, set(own_format)
    try:
        rules = rules or load_rules()
        validate_rules(rules)
    except IncompleteRules as e:
        return [str(e)]
    folder = Path(folder)
    f = []
    if not folder.is_dir():
        return ["the folder does not exist; create it as <dir>/YYYY-MM-DD/NN-<topic>"]
    if (folder / "ficha.md").is_file() and not (folder / "sheet.md").is_file():
        print(f"check.py: warning: {folder} uses the old Spanish layout (ficha.md, medios/); rename ficha.md to sheet.md, "
              "medios/ to media/ and its fuente/ to source/, and translate the headings (see the skill's template)",
              file=sys.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            return check(old_piece(folder, Path(tmp)), rules, prefixes, limits, own_format, today, web_languages)
    parent = folder.resolve().parent.name
    try:
        date_ok = bool(DATE_RE.fullmatch(parent)) and bool(date.fromisoformat(parent))
    except ValueError:
        date_ok = False
    if not PIECE_DIR.match(folder.resolve().name) or not date_ok:
        f.append("folder name: expected <dir>/YYYY-MM-DD/NN-<topic> (e.g. 2026-10-25/01-release); rename the folder")
    if not (folder / "sheet.md").is_file():
        f.append("no sheet.md; create it from the piece template (facts with their source)")
    channel_files = sorted(p.stem for p in folder.glob("*.md") if p.name != "sheet.md")
    if not (folder / "sheet.md").is_file():
        if not channel_files:
            f.append("no channel file; add <channel>.md (x, reddit, linkedin, discord)")
        return f
    sheet, error = read_text(folder / "sheet.md", "sheet.md")
    if error:
        return [error]
    for m in GAP.finditer(sheet):
        f.append(f"sheet.md: template gap «{_gap(m)}» left; write the text")
    if not re.search(r"(?m)^##\s+Published\s*$", sheet):
        f.append("sheet.md: no «## Published» section; add the table | Channel | Language | Date | Link |")
    raw = list(dict.fromkeys(requested_channels(sheet)))
    if not raw:
        f.append("sheet.md: no channels under «## Channels»; list one channel per line (x, reddit, linkedin, discord…)")
    requested = []
    for c in raw:
        if CHANNEL.fullmatch(c):
            requested.append(c)
        else:
            f.append(f"sheet.md: channel «{c}» under «## Channels» is not a valid name; use lowercase letters, digits and "
                     "hyphens ([a-z0-9-]+), one channel per line")
    for c in requested:
        if not (folder / f"{c}.md").is_file():
            f.append(f"{c}.md: listed under «## Channels» but missing; write it or remove the line")
    for c in channel_files:
        if c not in requested:
            if c in KNOWN:
                f.append(f"{c}.md: channel not requested; delete the file or list «{c}» under «## Channels» in sheet.md")
            else:
                f.append(f"{c}.md: unknown channel file; list it under «## Channels» in sheet.md or delete the file")
    active = [c for c in requested if (folder / f"{c}.md").is_file()]
    texts = {}
    for c in active:
        text, error = read_text(folder / f"{c}.md", f"{c}.md")
        if error:
            f.append(error)
        else:
            texts[c] = text
    active = [c for c in active if c in texts]
    declared = [x.strip() for x in re.split(r"[,\s]+", field(sheet, "Languages")) if x.strip()]
    if not declared:
        f.append('no languages: add "Languages: es, en" to sheet.md')
    for i in declared:
        if not LANG.fullmatch(i):
            f.append(f"sheet.md: «Languages:» has «{i}»; use two-letter lowercase ISO 639-1 codes separated by commas "
                     "(es, en, gl)")
    declared = [i for i in dict.fromkeys(declared) if LANG.fullmatch(i)]
    languages = declared or sorted({i for c, t in texts.items() if c not in own_format and c != "web"
                                    for i in sections(t)})
    web_paths = []
    for c in active:
        if c == "web":
            p, web_paths = check_web(texts[c], languages, prefixes, folder, web_languages)
            f += p
        elif c in own_format:
            f += check_own_format(c, texts[c], prefixes)
        else:
            f += check_channel(c, texts[c], languages, rules, prefixes, limits.get(c))
    if "reddit" in active:
        f += check_reddit(sheet, rules, today, date.fromisoformat(parent) if date_ok else None)
    f += check_images(folder, sheet, texts, languages, rules, prefixes, own_format, web_paths)
    return list(dict.fromkeys(f))


def pieces(arg: Path) -> list:
    """A piece folder, or the pieces below a date folder or the whole <dir>."""
    if (arg / "sheet.md").is_file() or (arg / "ficha.md").is_file() or not arg.is_dir():
        return [arg]
    in_date = bool(DATE_RE.fullmatch(arg.resolve().name))
    children = sorted(p for p in arg.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")))
    out = []
    for h in children:
        if PIECE_DIR.match(h.name) or (h / "sheet.md").is_file() or (h / "ficha.md").is_file():
            out.append(h)
        elif DATE_RE.fullmatch(h.name):
            out += pieces(h)
        elif looks_like_piece(h, in_date):  # a misnamed folder without sheet.md: checked, so that it is reported
            out.append(h)
    return out or [arg]


def looks_like_piece(p: Path, in_date=False) -> bool:
    """A folder with a media/ (or old media/) folder or the file of a known channel is a piece, whatever its name; under a date folder
    any folder with a .md file is (a piece with only <extra channel>.md files); proposals/ (old propuestas/) at the root is not."""
    if (p / "media").is_dir() or (p / "medios").is_dir() or any((p / f"{c}.md").is_file() for c in KNOWN):
        return True
    return in_date and any(p.glob("*.md"))


USAGE = ("usage: check.py [--task-prefixes A,B,...] [--limit channel=N]... [--own-format channel]... "
       "[--web-languages es,gl,en] <dir>/YYYY-MM-DD/NN-<topic> [...]  (e.g. docs/media/2026-10-25/01-release; "
       "--task-prefixes adds the task-id prefixes of the project, e.g. INS,FLU; --limit portal=500 caps each language "
       "section of an extra channel; --own-format portal marks an extra channel whose file has its own format; "
       "--web-languages es,gl,en sets the exact languages of web.md)")


def parse_options(args: list):
    """(folders, prefixes, limits, own-format channels, web languages, error). The options come before the folders."""
    args, prefixes, limits, own_format, web = rename_old_options(args), [], {}, [], None
    while args and args[0].startswith("--"):
        option = args.pop(0)
        name, eq, value = option.partition("=")
        if not eq:
            value = args.pop(0) if args else ""
        if name == "--task-prefixes":
            added = [x.strip().upper() for x in value.split(",") if x.strip()]
            prefixes += added
            if not added or not all(re.fullmatch(r"[A-Z][A-Z0-9]*", x) for x in added):
                return args, prefixes, limits, own_format, web, "--task-prefixes needs prefixes of letters and digits separated by commas (INS,FLU)"
        elif name == "--limit":
            channel, _, n = value.partition("=")
            if not CHANNEL.fullmatch(channel) or not n.isdigit() or int(n) < 1:
                return args, prefixes, limits, own_format, web, "--limit needs channel=N with a lowercase channel name and N >= 1 (--limit portal=500)"
            if channel in KNOWN:
                return args, prefixes, limits, own_format, web, ("--limit is for extra channels; web has its own checks (web.md)" if channel == "web" else
                                                              f"--limit is for extra channels; the limit of {channel} is in rules.json")
            limits[channel] = int(n)
        elif name == "--own-format":
            if not CHANNEL.fullmatch(value):
                return args, prefixes, limits, own_format, web, "--own-format needs a lowercase channel name (--own-format portal)"
            if value in KNOWN:
                return args, prefixes, limits, own_format, web, f"--own-format is for extra channels; {value} has its own checks"
            own_format.append(value)
        elif name == "--web-languages":
            web = list(dict.fromkeys(x.strip() for x in value.split(",") if x.strip()))
            if not web or not all(LANG.fullmatch(x) for x in web):
                return args, prefixes, limits, own_format, web, ("--web-languages needs two-letter lowercase language codes "
                                                               "separated by commas (--web-languages es,gl,en)")
        else:
            return args, prefixes, limits, own_format, web, f"unknown option {name}"
    for channel in sorted(set(own_format) & set(limits)):
        return args, prefixes, limits, own_format, web, f"{channel} is in --limit and --own-format; a channel with its own format has no length check"
    return args, prefixes, limits, own_format, web, None


def unused_options(folders: list, limits: dict, own_format, web=None) -> str:
    """The error for a --limit or --own-format channel (or --web-languages without web) that no checked piece lists
    under `## Channels`, or None.
    Pieces without a readable sheet.md say so on their own; when none can be read there is nothing to compare."""
    declared, read_count = [], 0
    for c in folders:
        sheet, _ = read_text(Path(c) / "sheet.md", "sheet.md")
        if sheet is None and (Path(c) / "ficha.md").is_file():
            sheet, _ = read_text(Path(c) / "ficha.md", "ficha.md")
            sheet = old_sheet(sheet) if sheet is not None else None
        if sheet is not None:
            read_count += 1
            declared += [x for x in requested_channels(sheet) if x not in declared]
    if not read_count:
        return None
    listing = ", ".join(declared) or "none"
    used = [(f"--limit {k}={v}", k) for k, v in limits.items()] + [(f"--own-format {c}", c) for c in own_format]
    if web:
        used.append((f"--web-languages {','.join(web)}", "web"))
    for option, channel in used:
        if channel not in declared:
            return (f"{option} names a channel that no checked piece declares in «## Channels» (declared: {listing}); fix the "
                    "channel name or drop the option")
    return None


def main(args: list) -> int:
    args, prefixes, limits, own_format, web, error = parse_options(args)
    if error:
        print(f"{error}. {USAGE}")
        return 2
    if not args:
        print(USAGE)
        return 2
    try:
        rules, found = load_rules(), False
    except IncompleteRules as e:
        print(e)
        return 1
    all_pieces = [p for a in args for p in pieces(Path(a))]
    error = unused_options(all_pieces, limits, own_format, web)
    if error:
        print(f"{error}. {USAGE}")
        return 2
    for p in all_pieces:
        for problem in check(p, rules, prefixes, limits, own_format, web_languages=web):
            found = True
            print(f"{p}: {problem}")
    if not found:
        print("OK")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
