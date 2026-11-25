#!/usr/bin/env python3
"""Offline SEO checker for a statically built site.

Usage:
    check_seo.py <build_dir> [--site URL] [--langs en,es] [--ignore GLOB ...]
                 [--default-ignore GLOB ...] [--title-min N] [--title-max N]
                 [--description-min N] [--description-max N] [--max-html-bytes N]
                 [--lastmod-same-min N] [--json] [--strict] [--today YYYY-MM-DD]

--site    absolute base URL ending in "/". Default: derived from the first
          absolute "Sitemap:" URL in <build_dir>/robots.txt (the longest
          folder of it that is a prefix of the home page canonical).
--langs   expected hreflang languages. Default: those found in the build.
--ignore  globs on the path relative to build_dir, added to the default ones.
--default-ignore  replaces the default globs (404.html, google*.html, assets/*);
          pass it once per glob, or "" for none.
Thresholds (defaults in brackets): --title-min [10], --title-max [60],
          --description-min [50], --description-max [160], --max-html-bytes
          [2097152], --lastmod-same-min [4: warns when at least that many
          lastmod values are all equal].
--json    machine-readable output.
--strict  warnings also make the exit code 1.
--today   override today's date (tests only).

Exit codes: 0 no errors (warnings allowed), 1 errors (or warnings with
--strict), 2 usage or I/O problem (missing dir, no --site and no robots.txt
Sitemap line).

Text output: one "LEVEL code page: message" line per finding, then
"N pages, E errors, W warnings, I info". Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import itertools
import json
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

DEFAULT_IGNORE = ("404.html", "google*.html", "assets/*")
OG_REQUIRED = ("og:title", "og:description", "og:url", "og:image", "og:type")
RETIRED_TYPES = {"FAQPage", "HowTo", "SpecialAnnouncement", "ClaimReview",
                 "VehicleListing", "EstimatedSalary",
                 "OccupationalAggregateRating", "LearningVideo"}
PLACEHOLDER = re.compile(
    r"\[(business name|city|state|phone|address|your [^\]]+)\]|lorem ipsum"
    r"|(?-i:\bTODO\b)|example\.com", re.I)  # TODO in capitals only: «todo» is a Spanish word
LASTMOD = re.compile(r"^(\d{4}(?:-\d{2}(?:-\d{2})?)?)(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?"
                     r"(Z|[+-]\d{2}:\d{2}))?$")
MAX_HTML = 2 * 1024 * 1024
ABSOLUTE = re.compile(r"^https?://", re.I)


class Limits:
    """Thresholds of the checks; the defaults are the documented ones (flags override them)."""

    def __init__(self, title_min=10, title_max=60, description_min=50, description_max=160,
                 max_html_bytes=MAX_HTML, lastmod_same_min=4) -> None:
        self.title_min, self.title_max = title_min, title_max
        self.description_min, self.description_max = description_min, description_max
        self.max_html_bytes, self.lastmod_same_min = max_html_bytes, lastmod_same_min


class UsageError(Exception):
    """Problem with arguments or files: exit code 2."""


# --------------------------------------------------------------------- parsing
class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lang = None
        self.title = None
        self.metas: dict[str, list[str]] = {}
        self.canonicals: list[str] = []
        self.alternates: list[tuple[str, str]] = []
        self.jsonld: list[str] = []
        self.h1 = self.h2 = self.imgs = self.imgs_no_alt = 0
        self._title: list[str] | None = None
        self._ld: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "").strip() or None
        elif tag == "title" and self.title is None:
            self._title = []
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").strip().lower()
            if key and "content" in a:
                self.metas.setdefault(key, []).append(a["content"].strip())
        elif tag == "link":
            rel = a.get("rel", "").lower().split()
            href = a.get("href", "").strip()
            if "canonical" in rel:
                self.canonicals.append(href)
            elif "alternate" in rel and a.get("hreflang"):
                self.alternates.append((a["hreflang"].strip(), href))
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._ld = []
        elif tag == "h1":
            self.h1 += 1
        elif tag == "h2":
            self.h2 += 1
        elif tag == "img":
            self.imgs += 1
            self.imgs_no_alt += "alt" not in a

    def handle_endtag(self, tag):
        if tag == "title" and self._title is not None:
            self.title = re.sub(r"\s+", " ", "".join(self._title)).strip()
            self._title = None
        elif tag == "script" and self._ld is not None:
            self.jsonld.append("".join(self._ld))
            self._ld = None

    def handle_data(self, data):
        if self._title is not None:
            self._title.append(data)
        elif self._ld is not None:
            self._ld.append(data)


class Page:
    def __init__(self, rel: str, url: str, path: Path) -> None:
        self.rel, self.url = rel, url
        self.urls = {url}
        if rel.endswith(".html") and not rel.endswith("index.html"):
            self.urls.add(url[: -len(".html")])  # clean URL: about.html served as /about
        elif url.endswith("/") and rel != "index.html":
            self.urls.add(url.rstrip("/"))
        self.size = path.stat().st_size
        p = PageParser()
        p.feed(path.read_bytes().decode("utf-8", "replace"))
        p.close()
        self.p = p
        self.metas = p.metas
        self.alternates = p.alternates
        self.canonical = p.canonicals[0] if p.canonicals else None
        self.noindex = any("noindex" in v.lower()
                           for k in ("robots", "googlebot") for v in p.metas.get(k, []))
        self.description = self.meta("description")
        self.jsonld, self.jsonld_errors = [], 0
        for raw in p.jsonld:
            try:
                self.jsonld.append(json.loads(raw))
            except ValueError:
                self.jsonld_errors += 1

    def meta(self, key: str) -> str | None:
        vals = self.metas.get(key)
        return vals[0] if vals else None

    def alt_urls(self) -> set[str]:
        return {h for _, h in self.alternates}

    def top_types(self) -> set[str]:
        items: list = []
        for doc in self.jsonld:
            if isinstance(doc, list):
                items += doc
            elif isinstance(doc, dict) and isinstance(doc.get("@graph"), list):
                items += doc["@graph"]
            else:
                items.append(doc)
        out: set[str] = set()
        for it in items:
            if isinstance(it, dict):
                out |= set(as_list(it.get("@type")))
        return out


def as_list(v) -> list[str]:
    return [x for x in (v if isinstance(v, list) else [v]) if isinstance(x, str)]


def walk(node):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def primary(tag: str) -> str:
    return tag.lower().split("-")[0]


# ----------------------------------------------------------------- site loading
def page_url(site: str, rel: str) -> str:
    if rel == "index.html":
        return site
    return site + (rel[: -len("index.html")] if rel.endswith("/index.html") else rel)


def parse_robots(text: str) -> tuple[list[str], bool]:
    """Return (sitemap URLs, whether a `User-agent: *` group has `Disallow: /`)."""
    sitemaps, blocks_all = [], False
    agents: list[str] = []
    in_rules = False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (s.strip() for s in line.split(":", 1))
        key = key.lower()
        if key == "sitemap":
            sitemaps.append(value)
        elif key == "user-agent":
            if in_rules:
                agents, in_rules = [], False
            agents.append(value)
        elif key in ("disallow", "allow"):
            in_rules = True
            if key == "disallow" and value == "/" and "*" in agents:
                blocks_all = True
    return sitemaps, blocks_all


def home_canonical(build: Path) -> str | None:
    home = build / "index.html"
    if not home.is_file():
        return None
    parser = PageParser()
    parser.feed(home.read_bytes().decode("utf-8", "replace"))
    return parser.canonicals[0] if parser.canonicals else None


def resolve_site(build: Path, site: str | None) -> str:
    if site is None:
        robots = build / "robots.txt"
        listed = parse_robots(robots.read_text("utf-8", "replace"))[0] if robots.is_file() else []
        absolute = [sm for sm in listed if ABSOLUTE.match(sm)]
        if listed and not absolute:
            raise UsageError("the 'Sitemap:' line of robots.txt is not an absolute URL; make it absolute or pass "
                             "--site https://host/base/")
        if absolute:
            sm = absolute[0]
            host = re.match(r"^https?://[^/]+/", sm + "/")
            folders = []
            if host:
                base = host.group(0)
                parts = sm[len(base):].split("/")[:-1]
                folders = [base + "/".join(parts[:i]) + ("/" if i else "") for i in range(len(parts), -1, -1)]
            canonical = home_canonical(build)
            site = next((f for f in folders if canonical and canonical.startswith(f)), None) or \
                (folders[0] if folders else sm.rsplit("/", 1)[0] + "/")
    if site is None:
        raise UsageError("cannot tell the site URL: pass --site https://host/base/ "
                         "(no 'Sitemap:' line found in robots.txt)")
    if not ABSOLUTE.match(site) or not site.endswith("/"):
        raise UsageError("--site must be an absolute URL ending in '/'")
    return site


def load_pages(build: Path, site: str, ignore) -> dict[str, Page]:
    pages: dict[str, Page] = {}
    for f in sorted(build.rglob("*.html")):
        if not f.is_file():
            continue
        rel = f.relative_to(build).as_posix()
        if any(fnmatch.fnmatch(rel, g) for g in ignore):
            continue
        pages[page_url(site, rel)] = Page(rel, page_url(site, rel), f)
    return pages


# ----------------------------------------------------------------------- checks
class Findings(list):
    def add(self, level: str, code: str, page: str, msg: str) -> None:
        self.append({"level": level, "code": code, "page": page, "message": msg})


def check_basics(p: Page, site: str, out: Findings, lim: Limits) -> None:
    r, e, w = p.rel, "ERROR", "WARN"
    if not p.p.title:
        out.add(e, "title-missing", r, f"no <title>; add a unique title of {lim.title_min}-{lim.title_max} characters")
    elif len(p.p.title) > lim.title_max:
        out.add(w, "title-long", r, f"title has {len(p.p.title)} chars (>{lim.title_max}); shorten it")
    elif len(p.p.title) < lim.title_min:
        out.add(w, "title-short", r, f"title has {len(p.p.title)} chars (<{lim.title_min}); make it descriptive")
    d = p.description
    if not d:
        out.add(e, "description-missing", r, f'no meta description; add <meta name="description"> of {lim.description_min}-{lim.description_max} characters')
    elif len(d) > lim.description_max:
        out.add(w, "description-long", r, f"description has {len(d)} chars (>{lim.description_max}); shorten it")
    elif len(d) < lim.description_min:
        out.add(w, "description-short", r, f"description has {len(d)} chars (<{lim.description_min}); expand it")
    cans = p.p.canonicals
    if not cans:
        out.add(e, "canonical-missing", r, 'no canonical; add <link rel="canonical" href="<absolute page URL>">')
    else:
        if len(cans) > 1:
            out.add(e, "canonical-multiple", r, f"{len(cans)} canonical links; keep only one")
        c = cans[0]
        if not ABSOLUTE.match(c):
            out.add(e, "canonical-relative", r, f"canonical '{c}' is not absolute; use the full URL")
        elif not c.startswith(site):
            out.add(e, "canonical-other-site", r, f"canonical '{c}' is outside {site}; point it at this site")
        elif c not in p.urls:
            out.add(w, "canonical-not-self", r, f"canonical '{c}' differs from page URL {p.url}; make it self-referencing unless intended")
    if p.noindex:
        out.add("INFO", "noindex", r, "page has noindex; it will not be indexed")
    if not p.p.lang:
        out.add(w, "lang-missing", r, 'no <html lang>; add lang="<code>" with the page language (for example lang="en")')
    if p.p.h1 == 0:
        out.add(w, "h1-missing", r, "no <h1>; add one main heading")
    elif p.p.h1 > 1:
        out.add(w, "h1-multiple", r, f"{p.p.h1} <h1> elements; keep one")
    if p.p.imgs_no_alt:
        out.add(w, "img-alt-missing", r, f"{p.p.imgs_no_alt} img without alt; add alt (alt=\"\" if decorative)")
    if p.size > lim.max_html_bytes:
        out.add(w, "html-too-large", r, f"HTML is {p.size} bytes (>{lim.max_html_bytes}): Googlebot reads only the first 2 MB; split or trim it")


def check_hreflang(p: Page, index: dict[str, Page], langs: set[str],
                    site: str, out: Findings) -> None:
    if not p.alternates:
        return
    r = p.rel
    seen: dict[str, str] = {}
    for lang, href in p.alternates:
        if not ABSOLUTE.match(href):
            out.add("ERROR", "hreflang-relative", r, f"hreflang {lang} href '{href}' is not absolute; use the full URL")
        if lang.lower() in seen and seen[lang.lower()] != href:
            out.add("ERROR", "hreflang-duplicate", r, f"hreflang {lang} appears twice with different URLs; keep one")
        seen[lang.lower()] = href
    selfs = [lg for lg, h in p.alternates if h in p.urls]
    if not selfs:
        out.add("ERROR", "hreflang-no-self", r, "no hreflang alternate points at the page itself; add a self-referencing entry")
    elif p.p.lang:
        real = [lg for lg in selfs if lg.lower() != "x-default"]
        if real and all(primary(lg) != primary(p.p.lang) for lg in real):
            out.add("WARN", "hreflang-lang-mismatch", r, f"self hreflang '{real[0]}' does not match <html lang=\"{p.p.lang}\"; align them")
    for lang, href in p.alternates:
        if href in p.urls or not ABSOLUTE.match(href):
            continue
        tgt = index.get(href)
        if tgt is None:
            if href.startswith(site):
                out.add("ERROR", "hreflang-target-missing", r, f"hreflang {lang} target {href} is not in the build; fix or remove the link")
        elif not any(h in p.urls and lg.lower() != "x-default" for lg, h in tgt.alternates):
            # x-default alone is not a return link: each version must list the others by language.
            out.add("ERROR", "hreflang-not-reciprocal", r, f"lists {href} but {tgt.rel} does not link back; add the return hreflang")
    found = {lg.lower() for lg, _ in p.alternates}
    if "x-default" not in found:
        out.add("WARN", "hreflang-no-x-default", r, "no x-default alternate; add one pointing at the default language")
    have = {primary(lg) for lg in found - {"x-default"}}
    missing = sorted(lg for lg in langs if primary(lg) not in have)
    if missing:
        out.add("WARN", "hreflang-missing-lang", r, f"hreflang lacks {', '.join(missing)}; add those alternates")


def check_social(p: Page, out: Findings) -> None:
    r = p.rel
    missing = [k for k in OG_REQUIRED if not p.meta(k)]
    if missing:
        out.add("WARN", "og-missing", r, f"missing {', '.join(missing)}; add the Open Graph tags")
    if p.meta("og:url") and p.canonical and p.meta("og:url") != p.canonical:
        out.add("WARN", "og-url-not-canonical", r, "og:url differs from canonical; make them equal")
    img = p.meta("og:image")
    if img:
        if not ABSOLUTE.match(img):
            out.add("ERROR", "og-image-relative", r, f"og:image '{img}' is not absolute; use the full URL")
        if not (p.meta("og:image:width") and p.meta("og:image:height")):
            out.add("WARN", "og-image-size-missing", r, "og:image without og:image:width/height; add both")
    if not p.meta("twitter:card"):
        out.add("WARN", "twitter-card-missing", r, 'no twitter:card; add <meta name="twitter:card">')


def check_jsonld(p: Page, out: Findings) -> None:
    r = p.rel
    if p.jsonld_errors:
        out.add("ERROR", "jsonld-invalid", r, f"{p.jsonld_errors} JSON-LD block(s) do not parse; fix the JSON syntax")
    for doc in p.jsonld:
        for top in (doc if isinstance(doc, list) else [doc]):
            if isinstance(top, dict) and "@context" not in top:
                out.add("WARN", "jsonld-no-context", r, 'top-level JSON-LD object lacks "@context"; add "https://schema.org"')
    hits, types = set(), set()
    for node in walk(p.jsonld):
        if isinstance(node, str) and PLACEHOLDER.search(node):
            hits.add(PLACEHOLDER.search(node).group(0))
        elif isinstance(node, dict):
            types |= set(as_list(node.get("@type")))
    if hits:
        out.add("ERROR", "jsonld-placeholder", r, f"JSON-LD contains placeholder text ({', '.join(sorted(hits))}); replace it with real data")
    for t in sorted(types & RETIRED_TYPES):
        out.add("WARN", "jsonld-retired-type", r, f"Google no longer shows a rich result for {t}; see references.md")


def sitemap_entries(build: Path, site: str, rel: str, out: Findings, seen: set[str]):
    """Yield (loc, lastmod) of a sitemap file; a sitemap index is followed into its children of this site."""
    if rel in seen:
        return
    seen.add(rel)
    smap = build / rel
    if not smap.is_file():
        out.add("ERROR", "sitemap-missing", "site", f"no {rel}; generate a sitemap")
        return
    try:
        root = ET.fromstring(smap.read_bytes())
    except ET.ParseError as exc:
        out.add("ERROR", "sitemap-invalid", "site", f"{rel} is not valid XML ({exc}); regenerate it")
        return
    local = lambda el: el.tag.rsplit("}", 1)[-1]
    for node in (e for e in root.iter() if local(e) in ("url", "sitemap")):
        loc = next((c.text.strip() for c in node if local(c) == "loc" and c.text), "")
        if local(node) == "sitemap":
            if loc.startswith(site):
                yield from sitemap_entries(build, site, loc[len(site):], out, seen)
            else:
                out.add("ERROR", "sitemap-url-outside-site", "site", f"sitemap index entry {loc} is outside {site}; remove or fix it")
            continue
        lm = next((c.text.strip() for c in node if local(c) == "lastmod" and c.text), None)
        yield loc, lm


def check_robots_sitemap(build: Path, site: str, pages: dict[str, Page], index: dict[str, Page],
                         today: dt.date, out: Findings, lim: Limits) -> None:
    robots = build / "robots.txt"
    starts = []
    if not robots.is_file():
        out.add("ERROR", "robots-missing", "site", "no robots.txt; add one with a Sitemap: line")
    else:
        sitemaps, blocks = parse_robots(robots.read_text("utf-8", "replace"))
        if blocks:
            out.add("ERROR", "robots-blocks-all", "site", "'User-agent: *' has 'Disallow: /'; remove it or the site is not crawled")
        if not sitemaps:
            out.add("WARN", "robots-no-sitemap", "site", "robots.txt has no Sitemap: line; add the sitemap URL")
        starts = [sm[len(site):] for sm in sitemaps if sm.startswith(site)]
    listed: set[str] = set()
    lastmods: list[str] = []
    seen_files: set[str] = set()
    for loc, lm in (e for rel in (starts or ["sitemap.xml"]) for e in sitemap_entries(build, site, rel, out, seen_files)):
        listed.add(loc)
        if not loc.startswith(site):
            out.add("ERROR", "sitemap-url-outside-site", "site", f"sitemap URL {loc} is outside {site}; remove or fix it")
        elif loc not in index:
            out.add("ERROR", "sitemap-url-not-built", "site", f"sitemap URL {loc} matches no built page; remove it or build the page")
        else:
            pg = index[loc]
            if pg.noindex:
                out.add("ERROR", "sitemap-noindex", "site", f"sitemap lists {loc} which is noindex; remove it from the sitemap")
            if pg.canonical and pg.canonical != loc:
                out.add("ERROR", "sitemap-not-canonical", "site", f"sitemap lists {loc} but its canonical is {pg.canonical}; list the canonical URL")
        if lm is not None:
            m = LASTMOD.match(lm)
            try:
                parts = [int(x) for x in m.group(1).split("-")] if m else None
                day = dt.date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1) if parts else None
            except ValueError:
                day = None
            if day is None:
                out.add("ERROR", "lastmod-invalid", "site", f"lastmod '{lm}' of {loc} is not a W3C date; use YYYY-MM-DD (YYYY and YYYY-MM are also valid)")
            else:
                lastmods.append(m.group(1))
                if day > today + dt.timedelta(days=1):
                    out.add("ERROR", "lastmod-future", "site", f"lastmod {lm} of {loc} is in the future; fix the date")
    if len(lastmods) >= lim.lastmod_same_min and len(set(lastmods)) == 1:
        out.add("WARN", "lastmod-all-same", "site", f"all {len(lastmods)} lastmod values are {lastmods[0]}: looks like the build date and Google stops trusting it; use real change dates")
    for pg in pages.values():
        if not pg.noindex and pg.canonical in pg.urls and pg.canonical not in listed:
            out.add("WARN", "sitemap-missing-page", pg.rel, "indexable page is not in the sitemap; add it")


def clusters(pages: dict[str, Page], index: dict[str, Page]) -> list[list[Page]]:
    parent = {u: u for u in pages}

    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    for u, pg in pages.items():
        for h in pg.alt_urls():
            if h in index:
                parent[find(u)] = find(index[h].url)
    groups: dict[str, list[Page]] = {}
    for u, pg in pages.items():
        groups.setdefault(find(u), []).append(pg)
    return [sorted(g, key=lambda x: x.rel) for g in groups.values() if len(g) > 1]


def check_parity(groups: list[list[Page]], out: Findings) -> None:
    for group in groups:
        for a, b in itertools.combinations(group, 2):
            if a.p.title and a.p.title == b.p.title:
                out.add("WARN", "parity-same-title", a.rel, f"same title as {b.rel}; untranslated? translate it")
            if a.description and a.description == b.description:
                out.add("WARN", "parity-same-description", a.rel, f"same description as {b.rel}; untranslated? translate it")
            if abs(a.p.h2 - b.p.h2) > 1:
                out.add("WARN", "parity-h2", a.rel, f"{a.p.h2} h2 vs {b.p.h2} in {b.rel}; align the sections")
            if a.p.imgs != b.p.imgs:
                out.add("WARN", "parity-images", a.rel, f"{a.p.imgs} images vs {b.p.imgs} in {b.rel}; align the images")
            if a.top_types() != b.top_types():
                out.add("WARN", "parity-jsonld-types", a.rel, f"JSON-LD types differ from {b.rel} ({sorted(a.top_types())} vs {sorted(b.top_types())}); align them")


def check_duplicates(pages: dict[str, Page], groups: list[list[Page]], out: Findings) -> None:
    cluster_of = {pg.url: i for i, g in enumerate(groups) for pg in g}
    for code, label, getter in (("duplicate-title", "title", lambda p: p.p.title),
                                ("duplicate-description", "description", lambda p: p.description)):
        by_value: dict[str, list[Page]] = {}
        for pg in pages.values():
            if getter(pg):
                by_value.setdefault(getter(pg), []).append(pg)
        for value, pgs in by_value.items():
            ids = {cluster_of.get(pg.url, pg.url) for pg in pgs}
            if len(ids) > 1:
                names = ", ".join(sorted(pg.rel for pg in pgs))
                out.add("WARN", code, "site", f"same {label} '{value[:60]}' on {names}; write a unique {label} for each page")


def check(build: Path, site: str, langs=None, ignore=(), today=None, limits=None, default_ignore=DEFAULT_IGNORE):
    """Run every check; return (page count, findings)."""
    today = today or dt.date.today()
    lim = limits or Limits()
    pages = load_pages(build, site, tuple(default_ignore) + tuple(ignore))
    index = {u: pg for pg in pages.values() for u in pg.urls}
    if langs is None:
        langs = {lg.lower() for pg in pages.values() for lg, _ in pg.alternates} - {"x-default"}
    out = Findings()
    if not pages:
        out.add("ERROR", "no-pages", "site", "no HTML pages found in the build folder; run the project's build first")
    for pg in pages.values():
        check_basics(pg, site, out, lim)
        check_hreflang(pg, index, set(langs), site, out)
        check_social(pg, out)
        check_jsonld(pg, out)
    check_robots_sitemap(build, site, pages, index, today, out, lim)
    groups = clusters(pages, index)
    check_parity(groups, out)
    check_duplicates(pages, groups, out)
    out.sort(key=lambda f: (f["page"], f["code"], f["message"]))
    return len(pages), out


# -------------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Offline SEO checker for a built site.")
    ap.add_argument("build_dir")
    ap.add_argument("--site")
    ap.add_argument("--langs")
    ap.add_argument("--ignore", action="append", default=[], metavar="GLOB",
                    help="glob to skip, relative to build_dir (repeat the flag for several)")
    ap.add_argument("--default-ignore", action="append", default=None, metavar="GLOB",
                    help=f"replace the default ignored globs {list(DEFAULT_IGNORE)} (once per glob; \"\" for none)")
    for flag, default in (("title-min", 10), ("title-max", 60), ("description-min", 50), ("description-max", 160),
                          ("max-html-bytes", MAX_HTML), ("lastmod-same-min", 4)):
        ap.add_argument(f"--{flag}", type=int, default=default, metavar="N", help=f"default {default}")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--today")
    args = ap.parse_args(argv)
    try:
        build = Path(args.build_dir)
        if not build.is_dir():
            raise UsageError(f"{build} is not a directory; build the site first")
        site = resolve_site(build, args.site)
        langs = {x.strip().lower() for x in args.langs.split(",") if x.strip()} if args.langs else None
        try:
            today = dt.date.fromisoformat(args.today) if args.today else None
        except ValueError:
            raise UsageError("--today must be YYYY-MM-DD")
        ignore = list(args.ignore)
        limits = Limits(args.title_min, args.title_max, args.description_min, args.description_max,
                        args.max_html_bytes, args.lastmod_same_min)
        default_ignore = DEFAULT_IGNORE if args.default_ignore is None else [g for g in args.default_ignore if g]
        npages, findings = check(build, site, langs, ignore, today, limits, default_ignore)
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    count = lambda lv: sum(f["level"] == lv for f in findings)
    e, w, i = count("ERROR"), count("WARN"), count("INFO")
    if args.json:
        print(json.dumps({"site": site, "pages": npages, "findings": findings,
                          "summary": {"errors": e, "warnings": w, "info": i}},
                         ensure_ascii=False, indent=2))
    else:
        for f in findings:
            print(f"{f['level']} {f['code']} {f['page']}: {f['message']}")
        print(f"{npages} pages, {e} errors, {w} warnings, {i} info")
    return 1 if e or (args.strict and w) else 0


if __name__ == "__main__":
    sys.exit(main())
