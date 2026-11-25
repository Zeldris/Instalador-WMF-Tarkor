"""Tests for check_seo.py. Run: python3 -B -m unittest discover -s skills/gw-seo/scripts -p 'test_check_seo.py'"""
import datetime as dt
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import check_seo

SCRIPT = Path(check_seo.__file__).resolve()
SITE = "https://example.test/Site/"
TODAY = dt.date(2026, 11, 5)
LD = '{"@context":"https://schema.org","@type":"Organization","name":"Acme"}'
UNSET = object()


def page(url, lang, alts, title, desc, **kw):
    """Render one HTML page. A kwarg set to None drops that element."""
    o = dict(canonical=url, og={}, twitter="summary", jsonld=LD, h1=1, h2=1,
             imgs='<img src="a.png" alt="A">', robots=None, head="")
    o.update(kw)
    h = ["<!doctype html>", f'<html lang="{lang}">' if lang else "<html>", "<head>"]
    if title is not None:
        h.append(f"<title>{title}</title>")
    if desc is not None:
        h.append(f'<meta name="description" content="{desc}">')
    if o["canonical"] is not None:
        h.append(f'<link rel="canonical" href="{o["canonical"]}">')
    for hl, href in alts:
        h.append(f'<link rel="alternate" hreflang="{hl}" href="{href}">')
    og = {"og:title": title, "og:description": desc, "og:url": url, "og:image": SITE + "img.png",
          "og:type": "website", "og:image:width": "1200", "og:image:height": "630"}
    og.update(o["og"])
    h += [f'<meta property="{k}" content="{v}">' for k, v in og.items() if v is not None]
    if o["twitter"]:
        h.append(f'<meta name="twitter:card" content="{o["twitter"]}">')
    if o["robots"]:
        h.append(f'<meta name="robots" content="{o["robots"]}">')
    if o["jsonld"]:
        h.append(f'<script type="application/ld+json">{o["jsonld"]}</script>')
    h.append(o["head"])
    h.append("</head><body>")
    h += ["<h1>Main</h1>"] * o["h1"] + ["<h2>Sec</h2>"] * o["h2"] + [o["imgs"] or ""]
    h.append("</body></html>")
    return "\n".join(h)


ES_URL, EN_URL = SITE, SITE + "en/"
ALTS = [("es", ES_URL), ("en", EN_URL), ("x-default", ES_URL)]
ES_T, EN_T = "Sitio de ejemplo para pruebas SEO", "Example site for SEO tests"
ES_D = "Descripcion de prueba en castellano para check_seo la longitud correcta del texto."
EN_D = "Test description in English used to check that the length of the text is correct."


def sitemap(entries):
    body = "".join(f"<url><loc>{loc}</loc>" + (f"<lastmod>{lm}</lastmod>" if lm else "") + "</url>"
                   for loc, lm in entries)
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'


def build(root, es=None, en=None, extras=None, entries=None, robots=UNSET, files=None):
    """Write a clean two-language site under root; kwargs tweak it."""
    root = Path(root)
    pages = {
        "index.html": page(ES_URL, "es", ALTS, ES_T, ES_D, **(es or {})),
        "en/index.html": page(EN_URL, "en", ALTS, EN_T, EN_D, **(en or {})),
    }
    for rel, (url, kw) in (extras or {}).items():
        args = dict(lang="es", alts=[], title="Pagina extra distinta", desc=ES_D + " Extra.")
        args.update(kw)
        pages[rel] = page(url, args.pop("lang"), args.pop("alts"), args.pop("title"), args.pop("desc"), **args)
    pages.update(files or {})
    for rel, text in pages.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, "utf-8")
    if robots is UNSET:
        robots = f"User-agent: *\nAllow: /\n\nSitemap: {SITE}sitemap.xml\n"
    if robots is not None:
        (root / "robots.txt").write_text(robots, "utf-8")
    if entries is None:
        entries = [(ES_URL, "2026-11-01"), (EN_URL, "2026-11-02")]
    if entries is not False:
        (root / "sitemap.xml").write_text(sitemap(entries), "utf-8")


class Base(unittest.TestCase):
    def run_site(self, **kw):
        with tempfile.TemporaryDirectory() as d:
            ignore = kw.pop("ignore", ())
            build(d, **kw)
            _, found = check_seo.check(Path(d), SITE, ignore=ignore, today=TODAY)
        return found

    def codes(self, **kw):
        return {f["code"] for f in self.run_site(**kw)}


class TestClean(Base):
    def test_clean_site_has_no_findings(self):
        self.assertEqual(self.run_site(), [])


class TestPageChecks(Base):
    def test_title(self):
        self.assertIn("title-missing", self._with(title=None))
        self.assertIn("title-long", self._with(title="x" * 61))
        self.assertIn("title-short", self._with(title="Short"))

    def _with(self, title=UNSET, desc=UNSET):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            build(root)
            t = ES_T if title is UNSET else title
            ds = ES_D if desc is UNSET else desc
            (root / "index.html").write_text(page(ES_URL, "es", ALTS, t, ds), "utf-8")
            return {f["code"] for f in check_seo.check(root, SITE, today=TODAY)[1]}

    def test_description(self):
        self.assertIn("description-missing", self._with(desc=None))
        self.assertIn("description-long", self._with(desc="d" * 161))
        self.assertIn("description-short", self._with(desc="too short"))

    def test_canonical_not_self(self):
        self.assertIn("canonical-not-self", self.codes(es=dict(canonical=SITE + "otra/")))

    def test_canonical_missing_and_relative(self):
        self.assertIn("canonical-missing", self.codes(es=dict(canonical=None)))
        self.assertIn("canonical-relative", self.codes(es=dict(canonical="/Site/")))

    def test_canonical_other_site(self):
        self.assertIn("canonical-other-site", self.codes(es=dict(canonical="https://other.test/")))

    def test_noindex_is_info(self):
        found = self.run_site(es=dict(robots="noindex, follow"))
        self.assertIn(("INFO", "noindex"), {(f["level"], f["code"]) for f in found})

    def test_og_missing_lists_tags(self):
        found = self.run_site(es=dict(og={"og:type": None}))
        msgs = [f["message"] for f in found if f["code"] == "og-missing"]
        self.assertEqual(len(msgs), 1)
        self.assertIn("og:type", msgs[0])

    def test_og_image_relative_and_size(self):
        c = self.codes(es=dict(og={"og:image": "/img.png", "og:image:width": None}))
        self.assertIn("og-image-relative", c)
        self.assertIn("og-image-size-missing", c)

    def test_twitter_card_missing(self):
        self.assertIn("twitter-card-missing", self.codes(es=dict(twitter=None)))

    def test_jsonld_invalid(self):
        self.assertIn("jsonld-invalid", self.codes(es=dict(jsonld="{not json")))

    def test_jsonld_placeholder(self):
        ld = '{"@context":"https://schema.org","@type":"Organization","name":"[Business Name]"}'
        self.assertIn("jsonld-placeholder", self.codes(es=dict(jsonld=ld)))

    def test_jsonld_lowercase_todo_is_a_word_not_a_placeholder(self):
        ld = '{"@context":"https://schema.org","@type":"Organization","name":"Org","description":"y todo queda guardado"}'
        self.assertNotIn("jsonld-placeholder", self.codes(es=dict(jsonld=ld)))
        ld = '{"@context":"https://schema.org","@type":"Organization","name":"Org","description":"TODO"}'
        self.assertIn("jsonld-placeholder", self.codes(es=dict(jsonld=ld)))

    def test_jsonld_no_context(self):
        self.assertIn("jsonld-no-context", self.codes(es=dict(jsonld='{"@type":"Organization"}')))

    def test_jsonld_retired_type_in_graph(self):
        ld = ('{"@context":"https://schema.org","@graph":[{"@type":"Organization","name":"A"},'
              '{"@type":["Thing","FAQPage"]}]}')
        found = self.run_site(es=dict(jsonld=ld))
        retired = [f for f in found if f["code"] == "jsonld-retired-type"]
        self.assertEqual(len(retired), 1)
        self.assertIn("FAQPage", retired[0]["message"])
        self.assertNotIn("jsonld-no-context", {f["code"] for f in found})

    def test_h1_multiple_and_missing(self):
        self.assertIn("h1-multiple", self.codes(es=dict(h1=2)))
        self.assertIn("h1-missing", self.codes(es=dict(h1=0)))

    def test_img_alt_missing_but_empty_alt_ok(self):
        self.assertIn("img-alt-missing", self.codes(es=dict(imgs='<img src="a.png">')))
        self.assertNotIn("img-alt-missing", self.codes(es=dict(imgs='<img src="a.png" alt="">')))

    def test_lang_missing(self):
        with tempfile.TemporaryDirectory() as d:
            build(d)
            (Path(d) / "index.html").write_text(page(ES_URL, None, ALTS, ES_T, ES_D), "utf-8")
            codes = {f["code"] for f in check_seo.check(Path(d), SITE, today=TODAY)[1]}
        self.assertIn("lang-missing", codes)

    def test_html_too_large(self):
        self.assertIn("html-too-large", self.codes(es=dict(head="<!--" + "x" * (2 * 1024 * 1024) + "-->")))


class TestHreflang(Base):
    def test_not_reciprocal(self):
        c = self.codes(en=dict(), files={"en/index.html": page(
            EN_URL, "en", [("en", EN_URL)], EN_T, EN_D)})
        self.assertIn("hreflang-not-reciprocal", c)

    def test_return_link_only_through_x_default_is_not_reciprocal(self):
        # The es page is also x-default: an en page that links back only as x-default does not list es.
        alts = [("en", EN_URL), ("x-default", ES_URL)]
        c = self.codes(files={"en/index.html": page(EN_URL, "en", alts, EN_T, EN_D)})
        self.assertIn("hreflang-not-reciprocal", c)

    def test_target_missing(self):
        alts = ALTS + [("gl", SITE + "gl/")]
        c = self.codes(files={"index.html": page(ES_URL, "es", alts, ES_T, ES_D)})
        self.assertIn("hreflang-target-missing", c)

    def test_no_self(self):
        c = self.codes(files={"index.html": page(ES_URL, "es", [("en", EN_URL)], ES_T, ES_D)})
        self.assertIn("hreflang-no-self", c)

    def test_relative_and_no_x_default(self):
        alts = [("es", ES_URL), ("en", "/Site/en/")]
        c = self.codes(files={"index.html": page(ES_URL, "es", alts, ES_T, ES_D)})
        self.assertIn("hreflang-relative", c)
        self.assertIn("hreflang-no-x-default", c)

    def test_lang_mismatch(self):
        c = self.codes(files={"index.html": page(ES_URL, "fr", ALTS, ES_T, ES_D)})
        self.assertIn("hreflang-lang-mismatch", c)

    def test_missing_expected_lang(self):
        with tempfile.TemporaryDirectory() as d:
            build(d)
            _, found = check_seo.check(Path(d), SITE, langs={"es", "en", "gl"}, today=TODAY)
        self.assertIn("hreflang-missing-lang", {f["code"] for f in found})


class TestSiteLevel(Base):
    def test_robots_blocks_all(self):
        self.assertIn("robots-blocks-all", self.codes(
            robots=f"User-agent: *\nDisallow: /\nSitemap: {SITE}sitemap.xml\n"))

    def test_robots_missing_and_no_sitemap(self):
        self.assertIn("robots-missing", self.codes(robots=None))
        self.assertIn("robots-no-sitemap", self.codes(robots="User-agent: *\nAllow: /\n"))

    def test_sitemap_missing_and_invalid(self):
        self.assertIn("sitemap-missing", self.codes(entries=False))
        self.assertIn("sitemap-invalid", self._invalid())

    def _invalid(self):
        with tempfile.TemporaryDirectory() as d:
            build(d)
            (Path(d) / "sitemap.xml").write_text("<urlset>", "utf-8")
            return {f["code"] for f in check_seo.check(Path(d), SITE, today=TODAY)[1]}

    def test_sitemap_url_not_built_and_outside(self):
        e = [(ES_URL, "2026-11-01"), (EN_URL, "2026-11-01"), (SITE + "nada/", None),
             ("https://other.test/", None)]
        c = self.codes(entries=e)
        self.assertIn("sitemap-url-not-built", c)
        self.assertIn("sitemap-url-outside-site", c)

    def test_sitemap_noindex(self):
        self.assertIn("sitemap-noindex", self.codes(en=dict(robots="noindex")))

    def test_sitemap_not_canonical(self):
        self.assertIn("sitemap-not-canonical", self.codes(en=dict(canonical=ES_URL)))

    def test_sitemap_missing_page(self):
        c = self.codes(extras={"acerca/index.html": (SITE + "acerca/", {})})
        self.assertIn("sitemap-missing-page", c)

    def test_lastmod_future_and_invalid(self):
        self.assertIn("lastmod-future", self.codes(entries=[(ES_URL, "2026-12-31"), (EN_URL, "2026-11-01")]))
        self.assertIn("lastmod-invalid", self.codes(entries=[(ES_URL, "05/11/2026"), (EN_URL, None)]))
        self.assertNotIn("lastmod-future", self.codes(entries=[(ES_URL, "2026-11-06"), (EN_URL, "2026-11-05T10:00:00Z")]))

    def test_lastmod_all_same(self):
        extras = {f"p{i}/index.html": (SITE + f"p{i}/", dict(title=f"Pagina numero {i} de prueba",
                                                          desc=ES_D + f" Variante {i}."))
                  for i in range(3)}
        entries = [(ES_URL, "2026-11-01"), (EN_URL, "2026-11-01")] + \
                  [(SITE + f"p{i}/", "2026-11-01") for i in range(3)]
        self.assertIn("lastmod-all-same", self.codes(extras=extras, entries=entries))


class TestParityAndDuplicates(Base):
    def test_parity_same_title(self):
        files = {"en/index.html": page(EN_URL, "en", ALTS, ES_T, EN_D)}
        self.assertIn("parity-same-title", self.codes(files=files))

    def test_parity_others(self):
        c = self.codes(es=dict(h2=4, imgs='<img alt="a"><img alt="b">', jsonld=LD.replace("Organization", "Person")))
        self.assertTrue({"parity-h2", "parity-images", "parity-jsonld-types"} <= c)

    def test_duplicate_title_across_clusters(self):
        extras = {"otra/index.html": (SITE + "otra/", dict(title=ES_T, desc=ES_D + " Otra."))}
        entries = [(ES_URL, "2026-11-01"), (EN_URL, "2026-11-02"), (SITE + "otra/", "2026-11-03")]
        found = self.run_site(extras=extras, entries=entries)
        dups = [f for f in found if f["code"] == "duplicate-title"]
        self.assertEqual(len(dups), 1)
        self.assertIn("otra/index.html", dups[0]["message"])

    def test_translation_pair_is_not_duplicate(self):
        self.assertNotIn("duplicate-title", self.codes())


class TestIgnore(Base):
    def test_404_not_checked(self):
        c = self.codes(files={"404.html": "<html><head></head><body></body></html>"})
        self.assertEqual(c, set())

    def test_ignore_flag_before_build_dir(self):
        with tempfile.TemporaryDirectory() as d:
            build(Path(d))
            r = subprocess.run([sys.executable, str(SCRIPT), "--ignore", "borrador/*", d],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("0 errors", r.stdout)

    def test_custom_ignore(self):
        files = {"borrador/index.html": "<html></html>"}
        self.assertTrue(self.codes(files=files))
        self.assertEqual(self.codes(files=files, ignore=("borrador/*",)), set())


class TestReviewFindings(Base):
    """E42 review: every case reproduces a failure of the first version."""

    def test_sitemap_index_children_are_read(self):
        idx = (f'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               f'<sitemap><loc>{SITE}sitemap-0.xml</loc></sitemap></sitemapindex>')
        with tempfile.TemporaryDirectory() as d:
            build(d)
            Path(d, "sitemap.xml").write_text(idx, "utf-8")
            Path(d, "sitemap-0.xml").write_text(
                sitemap([(ES_URL, "2026-11-01"), (EN_URL, "2026-11-02"), (SITE + "gone/", None)]), "utf-8")
            found = check_seo.check(Path(d), SITE, today=TODAY)[1]
        codes = {f["code"] for f in found}
        self.assertNotIn("sitemap-missing-page", codes)
        self.assertIn("sitemap-url-not-built", codes)

    def test_sitemap_index_missing_child(self):
        idx = (f'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               f'<sitemap><loc>{SITE}nope.xml</loc></sitemap></sitemapindex>')
        with tempfile.TemporaryDirectory() as d:
            build(d)
            Path(d, "sitemap.xml").write_text(idx, "utf-8")
            codes = {f["code"] for f in check_seo.check(Path(d), SITE, today=TODAY)[1]}
        self.assertIn("sitemap-missing", codes)

    def test_several_sitemap_lines_all_read(self):
        robots = f"User-agent: *\nAllow: /\nSitemap: {SITE}a.xml\nSitemap: {SITE}b.xml\n"
        with tempfile.TemporaryDirectory() as d:
            build(d, robots=robots, entries=False)
            Path(d, "a.xml").write_text(sitemap([(ES_URL, "2026-11-01")]), "utf-8")
            Path(d, "b.xml").write_text(sitemap([(EN_URL, "2026-11-01")]), "utf-8")
            found = check_seo.check(Path(d), SITE, today=TODAY)[1]
        self.assertEqual(found, [])

    def test_clean_urls_without_html_extension(self):
        about = SITE + "about"
        alts = [("es", about), ("x-default", about)]
        extras = {"about.html": (about, dict(alts=alts))}
        es = dict(head=f'<link rel="alternate" hreflang="es" href="{about}">')
        with tempfile.TemporaryDirectory() as d:
            build(d, extras=extras, entries=[(ES_URL, "2026-11-01"), (EN_URL, "2026-11-02"), (about, "2026-11-03")])
            codes = {f["code"] for f in check_seo.check(Path(d), SITE, today=TODAY)[1]}
        for bad in ("sitemap-url-not-built", "canonical-not-self", "hreflang-target-missing", "sitemap-missing-page"):
            self.assertNotIn(bad, codes)

    def test_sitemap_in_a_subfolder_does_not_change_the_site(self):
        with tempfile.TemporaryDirectory() as d:
            root = SITE.split("/Site/")[0] + "/"
            build(d, robots=f"Sitemap: {root}sitemaps/sitemap.xml\n",
                  es=dict(canonical=root, og={"og:url": root}), en=dict(canonical=root + "en/", og={"og:url": root + "en/"}))
            self.assertEqual(check_seo.resolve_site(Path(d), None), root)

    def test_partial_lastmod_dates_are_valid(self):
        for lm in ("2026", "2026-11"):
            self.assertNotIn("lastmod-invalid", self.codes(entries=[(ES_URL, lm), (EN_URL, "2026-11-02")]), lm)

    def test_regional_hreflang_satisfies_language(self):
        alts = [("es-ES", ES_URL), ("en-GB", EN_URL), ("x-default", ES_URL)]
        with tempfile.TemporaryDirectory() as d:
            build(d)
            Path(d, "index.html").write_text(page(ES_URL, "es", alts, ES_T, ES_D), "utf-8")
            Path(d, "en/index.html").write_text(page(EN_URL, "en", alts, EN_T, EN_D), "utf-8")
            found = check_seo.check(Path(d), SITE, langs={"es", "en"}, today=TODAY)[1]
        self.assertNotIn("hreflang-missing-lang", {f["code"] for f in found})

    def test_lang_fix_is_neutral(self):
        msg = next(f["message"] for f in self.run_site(files={"index.html": page(ES_URL, None, ALTS, ES_T, ES_D)}) if f["code"] == "lang-missing")
        self.assertNotIn('"es"', msg)
        self.assertIn('lang="<code>"', msg)

    def test_folder_named_like_a_page_is_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            build(d)
            Path(d, "x.html").mkdir()
            r = subprocess.run([sys.executable, str(SCRIPT), d, "--today", "2026-11-05"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_relative_sitemap_line_message(self):
        with tempfile.TemporaryDirectory() as d:
            build(d, robots="Sitemap: /sitemap.xml\n")
            r = subprocess.run([sys.executable, str(SCRIPT), d], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("absolute", r.stderr)
        self.assertIn("--site", r.stderr)

    def test_empty_build_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            n, found = check_seo.check(Path(d), SITE, today=TODAY)
        self.assertEqual(n, 0)
        self.assertIn(("ERROR", "no-pages"), {(f["level"], f["code"]) for f in found})

    def test_limits_are_flags_with_defaults(self):
        def run(*extra):
            with tempfile.TemporaryDirectory() as d:
                build(d, es=dict(h1=1))
                r = subprocess.run([sys.executable, str(SCRIPT), d, "--today", "2026-11-05", "--json", *extra],
                                   capture_output=True, text=True)
            return {f["code"] for f in json.loads(r.stdout)["findings"]}
        self.assertEqual(run(), set())
        self.assertIn("title-long", run("--title-max", "20"))
        self.assertIn("title-short", run("--title-min", "60"))
        self.assertIn("description-long", run("--description-max", "20"))
        self.assertIn("description-short", run("--description-min", "150"))
        self.assertIn("html-too-large", run("--max-html-bytes", "100"))

    def test_lastmod_same_threshold_flag(self):
        entries = [(ES_URL, "2026-11-01"), (EN_URL, "2026-11-01")]
        with tempfile.TemporaryDirectory() as d:
            build(d, entries=entries)
            limits = check_seo.Limits(lastmod_same_min=2)
            codes = {f["code"] for f in check_seo.check(Path(d), SITE, today=TODAY, limits=limits)[1]}
        self.assertIn("lastmod-all-same", codes)

    def test_default_ignore_can_be_replaced(self):
        files = {"google123.html": "<html></html>"}
        self.assertEqual(self.codes(files=files), set())
        with tempfile.TemporaryDirectory() as d:
            build(d, files=files)
            found = check_seo.check(Path(d), SITE, today=TODAY, default_ignore=())[1]
        self.assertIn("title-missing", {f["code"] for f in found})


class TestCli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)

    def test_site_derived_from_robots(self):
        with tempfile.TemporaryDirectory() as d:
            build(d)
            self.assertEqual(check_seo.resolve_site(Path(d), None), SITE)
            r = self.run_cli(d, "--today", "2026-11-05")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("2 pages, 0 errors, 0 warnings, 0 info", r.stdout)

    def test_exit_2_without_site(self):
        with tempfile.TemporaryDirectory() as d:
            build(d, robots="User-agent: *\nAllow: /\n")
            r = self.run_cli(d)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--site", r.stderr)

    def test_exit_2_missing_dir(self):
        self.assertEqual(self.run_cli("/nonexistent-dir-xyz", "--site", SITE).returncode, 2)

    def test_exit_1_on_error_and_strict_on_warning(self):
        with tempfile.TemporaryDirectory() as d:
            build(d, es=dict(canonical=None))
            r = self.run_cli(d, "--today", "2026-11-05")
        self.assertEqual(r.returncode, 1)
        self.assertIn("ERROR canonical-missing index.html:", r.stdout)
        with tempfile.TemporaryDirectory() as d:
            build(d, es=dict(h1=2))
            self.assertEqual(self.run_cli(d, "--today", "2026-11-05").returncode, 0)
            self.assertEqual(self.run_cli(d, "--today", "2026-11-05", "--strict").returncode, 1)

    def test_json_output(self):
        with tempfile.TemporaryDirectory() as d:
            build(d, es=dict(h1=2))
            r = self.run_cli(d, "--json", "--today", "2026-11-05")
        data = json.loads(r.stdout)
        self.assertEqual(data["site"], SITE)
        self.assertEqual(data["pages"], 2)
        self.assertEqual(data["summary"], {"errors": 0, "warnings": 1, "info": 0})
        self.assertEqual(data["findings"][0]["code"], "h1-multiple")


if __name__ == "__main__":
    unittest.main()
