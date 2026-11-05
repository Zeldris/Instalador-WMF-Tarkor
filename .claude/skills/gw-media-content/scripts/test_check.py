"""Tests of check.py: every case builds its own piece folder in a tempdir (a valid one) and breaks one thing;
each asserts the message, not only the result. Run: python3 -m unittest discover -s skills/gw-media-content/scripts"""
import contextlib
import io
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check  # noqa: E402

TODAY = date.today()
RULES_TEXT = ("1. Sé amable con los demás miembros. 2. Nada de spam. 3. La autopromoción solo los sábados y con una "
          "publicación de aportación por cada una de promoción. 4. Pon etiqueta a los mensajes. 5. Sin enlaces acortados. ")
assert len(RULES_TEXT) >= 200
SHEET = """# Sheet: release

Languages: es, en

## Channels

- x
- reddit
- linkedin
- discord

## Facts

| Fact | Source |
|---|---|
| Sale la 1.0 | CHANGELOG.md |

## Reddit

- **Subreddit:** r/gamedev
- **Rules read:** {today}
- **Self-promotion:** solo los sábados

### Rules of r/gamedev

{set_rules}

## Images

| Image | Alt text | Channels |
|---|---|---|
| `media/card.webp` | es: Tarjeta de la versión / en: Release card | x |
| `media/card.png` | es: Tarjeta de la versión / en: Release card | linkedin |

## Internal use

Tarea QA-12 en la rama claude/algo.

## Published

| Channel | Language | Date | Link |
|---|---|---|---|
""".replace("{today}", TODAY.isoformat()).replace("{set_rules}", RULES_TEXT)
CHANNELS = {
    "x": "## es\n\n**1/** Sale la versión.\nImage: media/card.webp\n\n**2/** Detalles.\n\n## en\n\n**1/** Release out.\n\n**2/** Details.\n",
    "reddit": "## es\n\n**Title:** Sale la versión\n\nTexto.\n\n## en\n\n**Title:** Release out\n\nText.\n",
    "linkedin": "## es\n\nTexto largo.\nImage: media/card.png\n\n## en\n\nLong text.\nImage: media/card.png\n",
    "discord": "## es\n\n### Novedades\n\n## en\n\n### News\n",
}


RENDER = "node .claude/skills/gw-media-content/scripts/render.mjs"


def webp(width=100, height=50, extra=0):
    body = b"WEBPVP8X" + struct.pack("<I", 10) + bytes(4) + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", len(body)) + body + bytes(extra)


def png(width, height):
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"


def jpeg(width, height):
    sof = b"\xff\xc0" + struct.pack(">HBHH", 11, 8, height, width) + b"\x03\x01\x11\x00"
    return b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 6) + b"JFIF" + sof + bytes(10)


def gif(width, height):
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00\x00\x00;"


def pdf(pages):
    return b"%PDF-1.4\n" + b"".join(b"%d 0 obj\n<< /Type /Page >>\nendobj\n" % i for i in range(pages)) + b"%%EOF\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.folder = self.tmp / TODAY.isoformat() / "01-release"
        (self.folder / "media" / "source").mkdir(parents=True)
        self.write("sheet.md", SHEET)
        for c, t in CHANNELS.items():
            self.write(f"{c}.md", t)
        (self.folder / "media" / "card.webp").write_bytes(webp())
        (self.folder / "media" / "card-mini.webp").write_bytes(webp(10, 5))
        (self.folder / "media" / "card.png").write_bytes(png(100, 50))
        (self.folder / "media" / "source" / "card.html").write_text("<p>ok</p>")
        self.rules = check.load_rules()

    def write(self, name, text):
        (self.folder / name).write_text(text, encoding="utf-8")

    def change(self, name, old, new):
        t = (self.folder / name).read_text(encoding="utf-8")
        self.assertIn(old, t)
        self.write(name, t.replace(old, new, 1))

    def pdf_in_linkedin(self, pages):
        """LinkedIn posts a carousel PDF instead of the .png."""
        (self.folder / "media" / "carousel.pdf").write_bytes(pdf(pages))
        (self.folder / "media" / "card.png").unlink()
        self.change("sheet.md", "`media/card.png` | es: Tarjeta de la versión / en: Release card",
                     "`media/carousel.pdf` | es: Carrusel / en: Carousel")
        self.write("linkedin.md", CHANNELS["linkedin"].replace("card.png", "carousel.pdf"))

    def problems(self, rules=None):
        return "\n".join(check.check(self.folder, rules or self.rules))

    def assertProblem(self, fragment, **kw):
        self.assertIn(fragment, self.problems(**kw))


class Structure(Base):
    def test_valid_piece_passes(self):
        self.assertEqual(self.problems(), "")

    def test_cli_prints_ok_and_exits_zero(self):
        r = subprocess.run([sys.executable, str(HERE / "check.py"), str(self.folder)], capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "OK"))

    def test_cli_fails_with_one_line_per_problem(self):
        self.change("x.md", "**2/** Detalles.", "**2/** QA-12 {{gap}}")
        r = subprocess.run([sys.executable, str(HERE / "check.py"), str(self.folder)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("internal jargon «QA-12»", r.stdout)
        self.assertIn("template gap «{{gap}}»", r.stdout)

    def test_no_arguments_is_a_usage_error(self):
        r = subprocess.run([sys.executable, str(HERE / "check.py")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage: check.py [--task-prefixes A,B,...]", r.stdout)

    def test_date_folder_expands_to_its_pieces(self):
        self.assertEqual([p.name for p in check.pieces(self.folder.parent)], ["01-release"])

    def test_empty_folder(self):
        empty = self.tmp / "2026-10-26" / "02-empty"
        empty.mkdir(parents=True)
        out = "\n".join(check.check(empty, self.rules))
        self.assertIn("no sheet.md", out)
        self.assertIn("no channel file", out)

    def test_folder_that_does_not_exist(self):
        self.assertIn("does not exist", "\n".join(check.check(self.tmp / "nada", self.rules)))

    def test_missing_sheet(self):
        (self.folder / "sheet.md").unlink()
        self.assertProblem("no sheet.md")

    def test_wrong_folder_name(self):
        bad = self.tmp / "yesterday" / "topic"
        shutil.copytree(self.folder, bad)
        self.assertIn("folder name: expected <dir>/YYYY-MM-DD/NN-<topic>", "\n".join(check.check(bad, self.rules)))

    def test_sheet_without_published(self):
        self.change("sheet.md", "## Published", "## Otro")
        self.assertProblem("no «## Published» section")

    def test_sheet_without_channels(self):
        self.change("sheet.md", "## Channels", "## Otros")
        self.assertProblem("no channels under «## Channels»")

    def test_requested_channel_without_file(self):
        (self.folder / "discord.md").unlink()
        self.assertProblem("discord.md: listed under «## Channels» but missing")

    def test_known_channel_not_requested(self):
        self.change("sheet.md", "- discord\n", "")
        self.assertProblem("discord.md: channel not requested; delete the file")

    def test_listed_extra_channel_gets_only_the_generic_checks(self):
        self.change("sheet.md", "- discord\n", "- discord\n- portal\n")
        self.change("sheet.md", "Release card | x |", "Release card | x, portal |")
        self.write("portal.md", "## es\n\n" + "a" * 5000 + "\n\n## en\n\nb\nImage: media/card.webp\n")
        self.assertEqual(self.problems(), "")

    def test_listed_extra_channel_checks_languages_jargon_gaps_and_image(self):
        self.change("sheet.md", "- discord\n", "- discord\n- portal\n")
        self.write("portal.md", "## es\n\nWIP: {{x}}\nImage: media/no.webp\n")
        out = self.problems()
        self.assertIn("portal.md: no «## en» section", out)
        self.assertIn("portal.md: internal jargon «WIP:»", out)
        self.assertIn("portal.md: template gap «{{x}}»", out)
        self.assertIn("portal.md: «Image: media/no.webp» does not exist", out)

    def test_unlisted_unknown_channel_is_an_error(self):
        self.write("portal.md", "## es\n\na\n\n## en\n\nb\n")
        self.assertProblem("portal.md: unknown channel file; list it under «## Channels» in sheet.md")

    def test_missing_language_in_a_channel(self):
        self.write("linkedin.md", "## es\n\nSolo español.\n")
        self.assertProblem("linkedin.md: no «## en» section")

    def test_language_not_in_the_piece(self):
        self.write("linkedin.md", CHANNELS["linkedin"] + "\n## gl\n\nGalego.\n")
        self.assertProblem("linkedin.md: language «gl» is not in the piece")

    def test_languages_is_mandatory_in_the_sheet(self):
        self.change("sheet.md", "Languages: es, en\n", "")
        self.assertProblem('no languages: add "Languages: es, en" to sheet.md')

    def test_without_languages_the_rest_are_still_deduced(self):
        self.change("sheet.md", "Languages: es, en\n", "")
        self.write("linkedin.md", "## es\n\nSolo español.\n")
        self.assertProblem("linkedin.md: no «## en» section")

    def test_repeated_language_section(self):
        self.write("linkedin.md", CHANNELS["linkedin"] + "\n## es\n\nOtra vez.\n")
        self.assertProblem("linkedin.md: «## es» appears more than once; merge the sections into one")

    def test_a_non_language_heading_closes_the_section(self):
        # the 3001 characters under «## Notas» are not part of «## es»: no length error
        self.write("linkedin.md", "## es\n\nCorto.\nImage: media/card.png\n\n## Notas\n\n" + "a" * 3001 + "\n\n## en\n\nok\n")
        self.assertEqual(self.problems(), "")

    def test_a_section_cut_by_a_heading_is_empty(self):
        self.write("linkedin.md", "## es\n## Notas\nTexto largo.\n\n## en\n\nok\n")
        self.assertProblem("linkedin.md: no «## es» section")


class TextChecks(Base):
    def test_template_gap_in_the_sheet(self):
        self.change("sheet.md", "Sale la 1.0", "{{fact}}")
        self.assertProblem("sheet.md: template gap «{{fact}}»")

    def test_template_gap_in_a_channel(self):
        self.change("reddit.md", "Texto.", "{{text}}")
        self.assertProblem("reddit.md: template gap «{{text}}»")

    def test_template_gap_in_a_source(self):
        (self.folder / "media" / "source" / "card.html").write_text("<p>{{title}}</p>")
        self.assertProblem("media/source/card.html: template gaps")

    def test_internal_jargon_in_a_channel(self):
        for jargon, text in (("P3", "hallazgo P3"), ("F12", "finding F12"), ("P1", "ver (P1)"), ("QA-215", "QA-215"),
                             ("EPIC-3", "EPIC-3"), ("claude/rama-x", "claude/rama-x"), ("WIP:", "WIP:")):
            with self.subTest(jargon=jargon):
                self.change("linkedin.md", "Long text.", f"Long text {text}.")
                self.assertProblem(f"linkedin.md: internal jargon «{jargon}»")
                self.change("linkedin.md", f"Long text {text}.", "Long text.")

    def test_project_prefixes_are_not_jargon_by_default(self):
        for text in ("INS-3", "FLU-12", "WMF-7"):
            with self.subTest(text=text):
                self.change("linkedin.md", "Long text.", f"Long text {text}.")
                self.assertEqual(self.problems(), "")
                self.change("linkedin.md", f"Long text {text}.", "Long text.")

    def test_prefixes_are_added_with_the_argument(self):
        self.change("linkedin.md", "Long text.", "Long text INS-3 y FLU-12.")
        problems = "\n".join(check.check(self.folder, self.rules, ("INS", "FLU")))
        self.assertIn("linkedin.md: internal jargon «INS-3»", problems)
        self.assertIn("linkedin.md: internal jargon «FLU-12»", problems)
        self.assertEqual(check.jargon("QA-1 y INS-3", ("INS",)), ["INS-3", "QA-1"])  # the generic ones stay

    def test_cli_task_prefixes(self):
        self.change("linkedin.md", "Long text.", "Long text INS-3.")
        for args in (["--task-prefixes", "INS,FLU"], ["--task-prefixes=ins, flu"]):
            r = subprocess.run([sys.executable, str(HERE / "check.py"), *args, str(self.folder)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn("internal jargon «INS-3»", r.stdout)
        without = subprocess.run([sys.executable, str(HERE / "check.py"), str(self.folder)], capture_output=True, text=True)
        self.assertEqual((without.returncode, without.stdout.strip()), (0, "OK"))

    def test_cli_task_prefixes_misspelled(self):
        for args, reason in ((["--task-prefixes"], "--task-prefixes needs prefixes"),
                             (["--task-prefixes", "IN S-1"], "--task-prefixes needs prefixes"),
                             (["--fast"], "unknown option --fast")):
            r = subprocess.run([sys.executable, str(HERE / "check.py"), *args, str(self.folder)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn(reason, r.stdout)
            self.assertIn("usage: check.py [--task-prefixes A,B,...]", r.stdout)

    def test_allowed_jargon_does_not_trigger(self):
        self.change("linkedin.md", "Long text.", "Long text con GPT-4, UTF-8 y P2P.")
        self.assertEqual(self.problems(), "")

    def test_ciphers_and_priorities_are_not_jargon(self):
        for text in ("AES-256", "WPA-3", "AK-47", "bugs P1/P2", "pulsa F5", "SHA-256 e ISO-8601", "El P1 y el P2"):
            with self.subTest(text=text):
                self.change("linkedin.md", "Long text.", f"Long text {text}.")
                self.assertEqual(self.problems(), "")
                self.change("linkedin.md", f"Long text {text}.", "Long text.")

    def test_a_branch_inside_a_link_is_not_jargon(self):
        self.change("linkedin.md", "Long text.", "Long text https://github.com/o/r/tree/claude/mi-rama-x y https://x.org/QA-12 fin.")
        self.assertEqual(self.problems(), "")
        self.change("linkedin.md", "claude/mi-rama-x y", "claude/mi-rama-x y claude/other")
        self.assertProblem("linkedin.md: internal jargon «claude/other»")

    def test_sheet_jargon_is_allowed_in_internal_use_but_not_in_the_alt(self):
        # QA-12 is in «## Internal use» of the fixture: allowed there, an error in an alt text
        self.assertIn("QA-12", (self.folder / "sheet.md").read_text(encoding="utf-8"))
        self.assertEqual(self.problems(), "")
        self.change("sheet.md", "Release card | x |", "Release card QA-12 | x |")
        self.assertProblem("sheet.md: alt text of «media/card.webp» has internal jargon «QA-12»")

    def test_a_lone_ellipsis_in_prose_is_not_a_gap(self):
        self.change("linkedin.md", "Long text.", "Long text … y más… o … así.")
        self.assertEqual(self.problems(), "")

    def test_an_ellipsis_that_is_the_whole_line_or_value_is_a_gap(self):
        self.change("linkedin.md", "Long text.", "Long text.\n\n…\n")
        self.assertProblem("linkedin.md: template gap «…» left")
        self.change("linkedin.md", "\n\n…\n", "")
        self.change("sheet.md", "## Reddit", "- **Status:** …\n\n## Reddit")
        self.assertProblem("sheet.md: template gap «…» left")

    def test_x_counts_an_emoji_as_2(self):
        self.change("x.md", "**1/** Sale la versión.", "**1/** " + "🙂" * 140)
        self.assertEqual(self.problems(), "")
        self.change("x.md", "🙂" * 140, "🙂" * 141)
        self.assertProblem("x.md (es) post 1: 282 weighted characters (max 280")

    def test_x_counts_a_url_as_23(self):
        url = "https://ejemplo.org/" + "a" * 100
        self.change("x.md", "**1/** Sale la versión.", f"**1/** {url} " + "a" * 256)
        self.assertEqual(self.problems(), "")
        self.change("x.md", "a" * 256, "a" * 257)
        self.assertProblem("x.md (es) post 1: 281 weighted characters")

    def lx(self, text):
        return check.x_length(text, check.rule(self.rules, "x", "url_weight"),
                                    check.rule(self.rules, "x", "wide_symbol_weight"))

    def test_x_accents_and_quotes_count_1(self):
        self.assertEqual(self.lx("áéíóú“”—"), 8)
        self.assertEqual(self.lx("日本"), 4)
        self.assertEqual(self.lx("❤️"), 2)
        self.assertEqual(self.lx("http://a.b/" + "c" * 80), 23)
        self.assertEqual(self.lx("©"), 1)

    def test_x_an_emoji_sequence_is_one_block_of_2(self):
        for name, text in (("family", "👨‍👩‍👧‍👦"), ("bandera", "🇪🇸"), ("tono de piel", "👍🏽"), ("profesión", "👩🏽‍💻"),
                              ("tecla", "1️⃣"), ("corazón", "❤️")):
            with self.subTest(name):
                self.assertEqual(self.lx(text), 2)
                self.assertEqual(self.lx("a" + text + "b"), 4)
        self.assertEqual(self.lx("🇪🇸🇫🇷"), 4)
        self.assertEqual(self.lx("👍👍"), 4)

    def test_x_trailing_punctuation_is_not_part_of_the_link(self):
        self.assertEqual(self.lx("(https://a.b/c)."), 1 + 23 + 2)
        self.assertEqual(self.lx("¿https://a.b/c?"), 1 + 23 + 1)
        self.assertEqual(self.lx("«https://a.b/c», https://d.e/f;"), 1 + 23 + 2 + 1 + 23 + 1)
        self.assertEqual(self.lx("https://a.b/c?q=1&r=2"), 23)

    def test_x_a_thread_with_family_emoji_at_the_limit(self):
        family = "👨‍👩‍👧‍👦"
        self.change("x.md", "**1/** Sale la versión.", "**1/** " + family * 140)
        self.assertEqual(self.problems(), "")
        self.change("x.md", family * 140, family * 141)
        self.assertProblem("x.md (es) post 1: 282 weighted characters (max 280")

    def test_x_text_before_the_first_marker(self):
        self.change("x.md", "## es\n\n**1/**", "## es\n\nIntro suelta.\n\n**1/**")
        self.assertProblem("x.md (es): text before «**1/**»")

    def test_x_the_n_of_m_marker_is_valid(self):
        self.write("x.md", "## es\n\n**1/2** Uno.\nImage: media/card.webp\n\n**2/2** Dos.\n\n## en\n\n**1/2** One.\n\n**2/2** Two.\n")
        self.assertEqual(self.problems(), "")
        self.assertEqual(check.x_posts("**1/2** Uno.\n\n**2/2** Dos."), ("", ["Uno.", "Dos."]))

    def test_x_number_of_posts_in_the_thread(self):
        self.write("x.md", "## es\n\n" + "".join(f"**{i}/** Uno.\n\n" for i in range(1, 6)) + "## en\n\n**1/** One.\n")
        self.assertProblem("x.md (es): 5 posts; a thread has 1 to 4")

    def test_x_without_markers_is_one_post(self):
        self.write("x.md", "## es\n\nUn post suelto.\nImage: media/card.webp\n\n## en\n\nOne post.\n")
        self.assertEqual(self.problems(), "")

    def test_discord_limit_per_block(self):
        self.write("discord.md", "## es\n\n" + "a" * 1999 + "\n---\n" + "b" * 2001 + "\n\n## en\n\nok\n")
        out = self.problems()
        self.assertIn("discord.md (es) message 2: 2001 characters (max 2000)", out)
        self.assertNotIn("message 1", out)

    def test_linkedin_limit(self):
        self.write("linkedin.md", "## es\n\n" + "a" * 3001 + "\n\n## en\n\nok\n")
        self.assertProblem("linkedin.md (es): 3001 characters (max 3000)")

    def test_linkedin_at_3000_passes_and_the_image_line_does_not_count(self):
        self.write("linkedin.md", "## es\n\n" + "a" * 3000 + "\nImage: media/card.png\n\n## en\n\nok\nImage: media/card.png\n")
        self.assertEqual(self.problems(), "")

    def test_reddit_title_too_long(self):
        self.change("reddit.md", "Sale la versión", "a" * 301)
        self.assertProblem("reddit.md (es): title of 301 characters (max 300)")

    def test_reddit_without_title(self):
        self.change("reddit.md", "**Title:** Release out", "Release out")
        self.assertProblem("reddit.md (en): no title")


class Reddit(Base):
    def test_missing_subreddit(self):
        self.change("sheet.md", "- **Subreddit:** r/gamedev\n", "")
        self.assertProblem("reddit.md needs «Subreddit:» in sheet.md")

    def test_missing_self_promotion(self):
        self.change("sheet.md", "- **Self-promotion:** solo los sábados\n", "")
        self.assertProblem("«Self-promotion:» line")

    def test_invalid_rules_date(self):
        self.change("sheet.md", TODAY.isoformat() + "\n- **Self-promotion", "yesterday\n- **Self-promotion")
        self.assertProblem("«Rules read:» «yesterday» has no valid YYYY-MM-DD date")

    def test_without_reddit_its_data_is_not_required(self):
        self.change("sheet.md", "- reddit\n", "")
        (self.folder / "reddit.md").unlink()
        self.assertEqual(self.problems(), "")


class Images(Base):
    def test_image_that_does_not_exist(self):
        self.change("x.md", "media/card.webp", "media/other.webp")
        self.assertProblem("x.md: «Image: media/other.webp» does not exist; render it (" + RENDER + " ")

    def test_image_that_is_not_a_render(self):
        self.change("x.md", "media/card.webp", "https://x.org/a.png")
        self.assertProblem("x.md: «Image: https://x.org/a.png» is not a render; point to media/<name>.webp")
        self.change("linkedin.md", "media/card.png", "https://x.org/a.png")
        self.assertProblem("linkedin.md: «Image: https://x.org/a.png» is not a render; point to media/<name>.png")

    def test_image_outside_the_table(self):
        (self.folder / "media" / "other.webp").write_bytes(webp())
        (self.folder / "media" / "other-mini.webp").write_bytes(webp())
        self.change("x.md", "media/card.webp", "media/other.webp")
        self.assertProblem("x.md: «media/other.webp» is not in «## Images» of sheet.md")

    def test_alt_missing_in_a_language(self):
        self.change("sheet.md", " / en: Release card", "")
        self.assertProblem("«media/card.webp» has no alt text in «en»")

    def test_sheet_without_image_table(self):
        self.change("sheet.md", "## Images", "## Otras")
        self.assertProblem("no «## Images» section")

    def test_render_without_mini(self):
        (self.folder / "media" / "card-mini.webp").unlink()
        self.assertProblem("«media/card.webp» has no -mini.webp; render it again (" + RENDER + " ")

    def test_render_not_listed_in_the_sheet(self):
        (self.folder / "media" / "loose.webp").write_bytes(webp())
        self.assertProblem("media/loose.webp: not in «## Images»")

    def test_source_not_rendered(self):
        for name in ("chart.html", "photo.jpg", "drawing.svg", "screenshot.png"):
            (self.folder / "media" / "source" / name).write_bytes(b"x")
            self.assertProblem(f"media/source/{name}: not rendered; run {RENDER} ")

    def test_source_rendered_to_pdf_passes(self):
        (self.folder / "media" / "source" / "carousel.html").write_text("<p>ok</p>")
        self.pdf_in_linkedin(3)
        self.assertEqual(self.problems(), "")

    def test_image_weight(self):
        rules = json.loads(json.dumps(self.rules))
        rules["x"]["image_bytes"]["value"] = 100
        (self.folder / "media" / "card.webp").write_bytes(webp(extra=500))
        self.assertProblem("media/card.webp: 530 bytes (max 100 for x)", rules=rules)

    def test_image_pixels(self):
        (self.folder / "media" / "card.png").write_bytes(png(7000, 6000))
        self.assertProblem("media/card.png: 7000x6000 = 42000000 pixels (must be under 36152320 for linkedin)")
        (self.folder / "media" / "card.png").write_bytes(jpeg(7000, 6000))
        self.assertProblem("media/card.png: 7000x6000 = 42000000 pixels (must be under 36152320 for linkedin)")

    def test_alt_too_long(self):
        self.change("sheet.md", "Tarjeta de la versión", "a" * 1001)
        self.assertProblem("alt text «es» of «media/card.webp» has 1001 characters (max 1000 for x)")

    def test_pdf_only_in_linkedin(self):
        (self.folder / "media" / "carousel.pdf").write_bytes(pdf(2))
        self.change("sheet.md", "| linkedin |", "| linkedin |\n| `media/carousel.pdf` | es: C / en: C | x |")
        self.change("x.md", "media/card.webp", "media/carousel.pdf")
        self.assertProblem("x.md: «media/carousel.pdf» is a PDF and only LinkedIn takes a document")

    def test_pdf_pages(self):
        rules = json.loads(json.dumps(self.rules))
        rules["linkedin"]["document_pages"]["value"] = 3
        self.pdf_in_linkedin(4)
        self.assertProblem("media/carousel.pdf: 4 pages (LinkedIn max 3)", rules=rules)

    def test_pdf_weight(self):
        rules = json.loads(json.dumps(self.rules))
        rules["linkedin"]["document_bytes"]["value"] = 50
        self.pdf_in_linkedin(2)
        self.assertProblem("media/carousel.pdf:", rules=rules)
        self.assertProblem("(LinkedIn max 50)", rules=rules)


class Formats(Base):
    def test_linkedin_accepts_png_jpg_and_gif_and_x_only_webp(self):
        for ext, data in ((".png", png(100, 50)), (".jpg", jpeg(100, 50)), (".gif", gif(100, 50))):
            with self.subTest(ext):
                (self.folder / "media" / "card.png").unlink(missing_ok=True)
                (self.folder / "media" / f"card{ext}").write_bytes(data)
                t = (self.folder / "linkedin.md").read_text(encoding="utf-8")
                self.write("linkedin.md", t.replace("card.png", f"card{ext}"))
                f = (self.folder / "sheet.md").read_text(encoding="utf-8")
                self.write("sheet.md", f.replace("card.png", f"card{ext}"))
                self.assertEqual(self.problems(), "")
                (self.folder / "media" / f"card{ext}").unlink()
                self.write("linkedin.md", t)
                self.write("sheet.md", f)

    def test_x_with_png_is_an_error(self):
        self.change("x.md", "media/card.webp", "media/card.png")
        self.change("sheet.md", "| x |", "| x, linkedin |")
        self.assertProblem("x.md: «media/card.png» is a .png and x takes .webp; point to media/<name>.webp")

    def test_linkedin_with_webp_is_an_error(self):
        self.change("linkedin.md", "media/card.png", "media/card.webp")
        self.assertProblem("linkedin.md: «media/card.webp» is a .webp and linkedin takes .png, .jpg, .gif; "
                         "point to media/<name>.png")

    def test_a_loose_png_in_media_without_a_row_is_an_error(self):
        (self.folder / "media" / "loose.png").write_bytes(png(10, 10))
        self.assertProblem("media/loose.png: not in «## Images»")

    def test_the_weight_of_a_png_is_checked(self):
        rules = json.loads(json.dumps(self.rules))
        rules["x"]["image_bytes"]["value"] = 20
        self.change("x.md", "media/card.webp", "media/card.png")
        self.change("sheet.md", "| x |", "| x, linkedin |")
        self.assertProblem("media/card.png: 29 bytes (max 20 for x)", rules=rules)

    def test_linkedin_formats_are_in_rules_with_a_primary_source(self):
        r = self.rules["linkedin"]["image_formats"]
        self.assertEqual((r["value"], r["mark"]), ([".png", ".jpg", ".gif"], "P"))
        self.assertIn("images-api", r["source"])


class ImageRows(Base):
    def test_a_row_channel_without_an_image_line(self):
        self.change("sheet.md", "Release card | x |", "Release card | x, discord |")
        self.assertProblem("sheet.md: «media/card.webp» lists channel «discord» but discord.md has no "
                         "«Image: media/card.webp» line")

    def test_image_line_of_a_channel_the_row_does_not_list(self):
        self.change("discord.md", "## es\n", "## es\nImage: media/card.webp\n")
        self.assertProblem("discord.md: «media/card.webp» is not listed for «discord» in «## Images» of sheet.md")

    def test_the_row_is_validated_against_each_channel_of_its_cell(self):
        # discord.md has no `Image:` line (an error of its own), but the row says discord: weight and alt are checked
        rules = json.loads(json.dumps(self.rules))
        rules["discord"]["image_bytes"]["value"] = 100
        self.change("sheet.md", "Release card | x |", "Release card | x, discord |")
        (self.folder / "media" / "card.webp").write_bytes(webp(extra=500))
        self.assertProblem("media/card.webp: 530 bytes (max 100 for discord)", rules=rules)
        self.change("sheet.md", "Tarjeta de la versión", "a" * 1025)
        self.assertProblem("alt text «es» of «media/card.webp» has 1025 characters (max 1024 for discord)")

    def test_the_linkedin_row_checks_pixels_even_if_the_channel_does_not_point(self):
        (self.folder / "media" / "card.png").write_bytes(png(7000, 6000))
        self.write("linkedin.md", "## es\n\nTexto largo.\n\n## en\n\nLong text.\n")
        out = self.problems()
        self.assertIn("lists channel «linkedin» but linkedin.md has no «Image: media/card.png» line", out)
        self.assertIn("7000x6000 = 42000000 pixels", out)


class TruncatedImages(Base):
    MSG = "not a valid image; render it again (" + RENDER + " "

    def test_a_non_image_in_x(self):
        (self.folder / "media" / "card.webp").write_bytes(b"garbage")
        self.assertProblem("media/card.webp: " + self.MSG)

    def test_png_truncated_with_the_full_signature(self):
        (self.folder / "media" / "card.png").write_bytes(png(100, 50)[:20])
        self.assertProblem("media/card.png: " + self.MSG)

    def test_png_without_ihdr(self):
        (self.folder / "media" / "card.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(30))
        self.assertProblem("media/card.png: " + self.MSG)

    def test_jpeg_truncated_with_the_full_signature(self):
        (self.folder / "media" / "card.png").write_bytes(jpeg(100, 50)[:18])
        self.assertProblem("media/card.png: " + self.MSG)

    def test_webp_vp8x_truncated(self):
        (self.folder / "media" / "card.webp").write_bytes(webp()[:29])
        self.assertProblem("media/card.webp: " + self.MSG)

    def test_the_mini_must_also_be_valid(self):
        (self.folder / "media" / "card-mini.webp").write_bytes(webp(10, 5)[:25])
        self.assertProblem("media/card-mini.webp: " + self.MSG)

    def test_unreadable_pdf_gives_the_full_command(self):
        self.pdf_in_linkedin(1)
        (self.folder / "media" / "carousel.pdf").write_bytes(b"%PDF-1.4\n")
        self.assertProblem("media/carousel.pdf: the page count cannot be read; render the PDF again (" + RENDER + " ")


class Headers(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def dim(self, name, data):
        p = self.tmp / name
        p.write_bytes(data)
        return check.dimensions(p)

    def test_webp_vp8x_vp8l_and_vp8(self):
        self.assertEqual(self.dim("a.webp", webp(640, 480)), (640, 480))
        bits = (320 - 1) | ((200 - 1) << 14)
        vp8l = b"VP8L" + struct.pack("<I", 5) + b"\x2f" + struct.pack("<I", bits)
        self.assertEqual(self.dim("b.webp", b"RIFF" + struct.pack("<I", 4 + len(vp8l)) + b"WEBP" + vp8l), (320, 200))
        vp8 = b"VP8 " + struct.pack("<I", 10) + b"\x00\x00\x00\x9d\x01\x2a" + struct.pack("<HH", 800, 600)
        self.assertEqual(self.dim("c.webp", b"RIFF" + struct.pack("<I", 4 + len(vp8)) + b"WEBP" + vp8), (800, 600))

    def test_webp_truncated(self):
        # VP8X needs 30 bytes, VP8L 25; the RIFF size is consistent here, so only the minimum length can catch it
        vp8x = b"WEBPVP8X" + struct.pack("<I", 10) + bytes(4) + b"\x63\x00"
        self.assertIsNone(self.dim("a.webp", b"RIFF" + struct.pack("<I", len(vp8x)) + vp8x))
        vp8l = b"WEBPVP8L" + struct.pack("<I", 5) + b"\x2f" + b"\x01\x02"
        self.assertIsNone(self.dim("b.webp", b"RIFF" + struct.pack("<I", len(vp8l)) + vp8l))

    def test_webp_with_riff_size_larger_than_the_file(self):
        self.assertIsNone(self.dim("a.webp", webp()[:28] + b"\x00\x00"[:0]))
        whole = webp(extra=100)
        self.assertEqual(self.dim("b.webp", whole), (100, 50))
        self.assertIsNone(self.dim("c.webp", whole[:-101]))

    def test_gif(self):
        self.assertEqual(self.dim("a.gif", gif(300, 200)), (300, 200))
        self.assertIsNone(self.dim("b.gif", gif(300, 200)[:8]))

    def test_zero_dimensions_are_not_valid(self):
        self.assertIsNone(self.dim("a.png", png(0, 10)))

    def test_png(self):
        self.assertEqual(self.dim("a.png", png(1200, 630)), (1200, 630))

    def test_jpeg(self):
        sof = b"\xff\xc0" + struct.pack(">HBHH", 11, 8, 480, 640) + b"\x03\x01\x11\x00"
        app = b"\xff\xe0" + struct.pack(">H", 6) + b"JFIF"
        self.assertEqual(self.dim("a.jpg", b"\xff\xd8" + app + sof), (640, 480))

    def test_unknown_format(self):
        self.assertIsNone(self.dim("a.webp", b"not an image"))
        self.assertIsNone(self.dim("b.png", b"\x89PNG"))

    def test_png_and_jpeg_truncated_with_the_full_signature(self):
        self.assertIsNone(self.dim("a.png", png(10, 10)[:20]))
        self.assertIsNone(self.dim("b.png", b"\x89PNG\r\n\x1a\n" + bytes(30)))
        self.assertIsNone(self.dim("a.jpg", jpeg(10, 10)[:16]))
        self.assertIsNone(self.dim("b.jpg", b"\xff\xd8\xff\xe0"))


class Rules(unittest.TestCase):
    def test_each_rule_has_value_mark_source_and_date(self):
        rules = check.load_rules()
        self.assertIn("Single place", rules["_doc"])
        for channel, body in rules.items():
            if channel.startswith("_"):
                continue
            for key, r in body.items():
                with self.subTest(rule=f"{channel}.{key}"):
                    self.assertEqual({"value", "mark", "source", "checked"} - set(r), set())
                    self.assertIn(r["mark"], ("P", "S", "NV", "C"))
                    self.assertRegex(r["checked"], r"^\d{4}-\d{2}-\d{2}$")

    def test_the_keys_the_script_reads_exist(self):
        rules = check.load_rules()
        for key in check.RULE_KEYS:
            channel, k = key.split(".")
            with self.subTest(key=key):
                self.assertIsNotNone(check.rule(rules, channel, k))
                self.assertIn(key, rules["_doc"])

    def test_the_script_reads_no_key_outside_rule_keys(self):
        script = (HERE / "check.py").read_text(encoding="utf-8")
        used_keys = set(re.findall(r"rule\(rules, [\"'](\w+)[\"'], [\"'](\w+)[\"']\)", script))
        self.assertTrue(used_keys)
        for channel, k in used_keys:
            self.assertIn(f"{channel}.{k}", check.RULE_KEYS)

    def test_a_missing_key_fails_closed_and_names_it(self):
        rules = check.load_rules()
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        for key in check.RULE_KEYS:
            channel, k = key.split(".")
            with self.subTest(key=key):
                broken = json.loads(json.dumps(rules))
                del broken[channel][k]
                expected = f"rules.json lacks {key}; restore it"
                with self.assertRaises(check.IncompleteRules) as e:
                    check.validate_rules(broken)
                self.assertEqual(str(e.exception), expected)
                path = tmp / "rules.json"
                path.write_text(json.dumps(broken), encoding="utf-8")
                with self.assertRaises(check.IncompleteRules) as e:
                    check.load_rules(path)
                self.assertEqual(str(e.exception), expected)
                self.assertEqual(check.check(tmp, broken), [expected])

    def test_without_url_weight_no_hidden_23_is_used(self):
        broken = json.loads(json.dumps(check.load_rules()))
        broken["x"]["wide_symbol_weight"]["value"] = None
        self.assertEqual(check.check(Path("."), broken), ["rules.json lacks x.wide_symbol_weight; restore it"])

    def test_cli_with_broken_rules_exits_1_and_says_what_is_missing(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        shutil.copytree(HERE.parent, tmp / "skill", ignore=shutil.ignore_patterns("__pycache__", "template"))
        rules = json.loads((tmp / "skill" / "rules.json").read_text(encoding="utf-8"))
        del rules["discord"]["message"]
        (tmp / "skill" / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
        r = subprocess.run([sys.executable, str(tmp / "skill" / "scripts" / "check.py"), str(tmp)], capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout.strip()), (1, "rules.json lacks discord.message; restore it"))

    def test_reddit_has_no_verified_data(self):
        rules = check.load_rules()
        self.assertEqual({r["mark"] for k, r in rules["reddit"].items() if k in ("title", "rules")}, {"NV"})

    def test_convention_values_of_reddit_and_extra_channels_are_in_rules(self):
        rules = check.load_rules()
        self.assertEqual((rules["reddit"]["rules_days"]["value"], rules["reddit"]["rules_days"]["mark"]), (90, "C"))
        self.assertEqual(rules["reddit"]["rules_min_chars"]["value"], 200)
        self.assertEqual(rules["extra_channel"]["image_formats"]["value"], [".webp", ".png", ".jpg"])


class Languages(Base):
    def test_any_two_letter_iso_code_is_valid(self):
        self.change("sheet.md", "Languages: es, en", "Languages: es, gl, en")
        for c in CHANNELS:
            t = (self.folder / f"{c}.md").read_text(encoding="utf-8")
            self.write(f"{c}.md", t + "\n## gl\n\n" + ("**Title:** Galego\n\n" if c == "reddit" else "")
                          + ("**1/** Galego.\n" if c == "x" else "Galego.\n" if c != "discord" else "### Galego\n"))
        self.change("sheet.md", "Release card | x |", "Release card / gl: Tarxeta | x |")
        self.change("sheet.md", "Release card | linkedin |", "Release card / gl: Tarxeta | linkedin |")
        self.assertEqual(self.problems(), "")

    def test_a_code_that_is_not_two_lowercase_letters_is_an_error(self):
        for bad in ("ESP", "e", "en-US", "e1"):
            with self.subTest(bad):
                self.change("sheet.md", "Languages: es, en", f"Languages: es, en, {bad}")
                self.assertProblem(f"sheet.md: «Languages:» has «{bad}»; use two-letter lowercase ISO 639-1 codes")
                self.change("sheet.md", f"Languages: es, en, {bad}", "Languages: es, en")

    def test_the_section_of_a_free_language_is_recognized(self):
        self.write("linkedin.md", CHANNELS["linkedin"] + "\n## ja\n\nTexto.\n")
        self.assertProblem("linkedin.md: language «ja» is not in the piece")
        self.change("sheet.md", "Languages: es, en", "Languages: es, en, ja")
        self.assertNotIn("language «ja»", self.problems())
        self.assertProblem("x.md: no «## ja» section")


class ImagesPerLanguage(Base):
    """Languages: es, en, gl. The first language uses media/<n>.webp; the others may have media/<n>.<lang>.webp."""

    def setUp(self):
        super().setUp()
        self.change("sheet.md", "Languages: es, en", "Languages: es, en, gl")
        self.change("sheet.md", "| `media/card.webp` | es: Tarjeta de la versión / en: Release card | x |",
                     "| `media/card.webp` | es: Tarjeta / en: Card / gl: Tarxeta | x |")
        self.change("sheet.md", "es: Tarjeta de la versión / en: Release card | linkedin |",
                     "es: Tarjeta / en: Card / gl: Tarxeta | linkedin |")
        self.write("x.md", "## es\n\n**1/** Sale.\nImage: media/card.webp\n\n## en\n\n**1/** Out.\nImage: media/card.webp\n\n"
                      "## gl\n\n**1/** Sae.\nImage: media/card.webp\n")
        t = (self.folder / "linkedin.md").read_text(encoding="utf-8")
        self.write("linkedin.md", t + "\n## gl\n\nTexto longo.\nImage: media/card.png\n")
        self.write("reddit.md", CHANNELS["reddit"] + "\n## gl\n\n**Title:** Sae\n\nTexto.\n")
        self.write("discord.md", CHANNELS["discord"] + "\n## gl\n\n### Novas\n")
        self.assertEqual(self.problems(), "")

    def galician_image(self, ext=".webp", channel="x", channels="x"):
        """The gl section of a channel points to its own render, listed in the table."""
        media = self.folder / "media"
        (media / f"card.gl{ext}").write_bytes(webp() if ext == ".webp" else png(100, 50))
        if ext == ".webp":
            (media / "card.gl-mini.webp").write_bytes(webp(10, 5))
        if ext == ".webp":
            (media / "source" / "card.gl.html").write_text("<p>gl</p>")
        t = (self.folder / f"{channel}.md").read_text(encoding="utf-8")
        i = t.index("## gl")
        self.write(f"{channel}.md", t[:i] + t[i:].replace(f"media/card{ext}", f"media/card.gl{ext}"))
        row = f"| `media/card.gl{ext}` | gl: Tarxeta propia | {channels} |\n"
        f = (self.folder / "sheet.md").read_text(encoding="utf-8")
        self.write("sheet.md", f.replace("\n\n## Internal use", "\n" + row + "\n## Internal use", 1))

    def test_a_languages_own_image_with_its_row_passes(self):
        self.galician_image()
        self.assertEqual(self.problems(), "")

    def test_the_row_of_an_own_image_asks_for_alt_only_in_its_language(self):
        self.galician_image()
        self.change("sheet.md", "gl: Tarxeta propia", "es: Propia")
        self.assertProblem("sheet.md: «media/card.gl.webp» has no alt text in «gl»")
        self.assertNotIn("«media/card.gl.webp» has no alt text in «es»", self.problems())

    def test_an_own_image_needs_its_mini(self):
        self.galician_image()
        (self.folder / "media" / "card.gl-mini.webp").unlink()
        self.assertProblem("sheet.md: «media/card.gl.webp» has no -mini.webp; render it again")

    def test_an_own_image_not_rendered(self):
        self.galician_image()
        (self.folder / "media" / "card.gl.webp").unlink()
        self.assertProblem("x.md: «Image: media/card.gl.webp» does not exist; render it ("
                         f"{RENDER} {self.folder})")

    def test_a_source_with_suffix_is_checked_like_any_source(self):
        self.galician_image()
        (self.folder / "media" / "card.gl.webp").unlink()
        (self.folder / "media" / "card.gl-mini.webp").unlink()
        self.assertProblem("media/source/card.gl.html: not rendered")

    def test_an_own_image_is_checked_with_the_channel_rules(self):
        rules = json.loads(json.dumps(self.rules))
        rules["x"]["image_bytes"]["value"] = 20
        self.galician_image()
        self.assertProblem("media/card.gl.webp: 30 bytes (max 20 for x)", rules=rules)

    def test_linkedin_with_own_png_image_and_webp_is_still_an_error(self):
        self.galician_image(".png", "linkedin", "linkedin")
        self.assertEqual(self.problems(), "")
        self.change("linkedin.md", "Image: media/card.gl.png", "Image: media/card.gl.webp")
        self.change("sheet.md", "`media/card.gl.png`", "`media/card.gl.webp`")
        (self.folder / "media" / "card.gl.webp").write_bytes(webp())
        (self.folder / "media" / "card.gl-mini.webp").write_bytes(webp(10, 5))
        self.assertProblem("linkedin.md: «media/card.gl.webp» is a .webp and linkedin takes .png, .jpg, .gif")

    def test_a_suffix_of_a_language_not_in_languages_is_an_error(self):
        (self.folder / "media" / "card.fr.webp").write_bytes(webp())
        (self.folder / "media" / "card.fr-mini.webp").write_bytes(webp(10, 5))
        self.change("x.md", "## gl\n\n**1/** Sae.\nImage: media/card.webp", "## gl\n\n**1/** Sae.\nImage: media/card.fr.webp")
        self.change("sheet.md", "\n\n## Internal use", "\n| `media/card.fr.webp` | es: a / en: b / gl: c | x |\n\n## Internal use")
        out = self.problems()
        self.assertIn("x.md: «media/card.fr.webp» has the language suffix «.fr.» but «fr» is not in «Languages:» of sheet.md; "
                      "add it there or rename the file", out)
        self.assertIn("sheet.md: «media/card.fr.webp» has the language suffix «.fr.»", out)

    def test_a_source_with_a_suffix_of_a_missing_language_is_an_error(self):
        (self.folder / "media" / "source" / "card.fr.html").write_text("<p>fr</p>")
        self.assertProblem("media/source/card.fr.html: «media/source/card.fr.html» has the language suffix «.fr.» "
                         "but «fr» is not in «Languages:»")

    def test_the_first_language_has_no_suffix(self):
        (self.folder / "media" / "card.es.webp").write_bytes(webp())
        (self.folder / "media" / "card.es-mini.webp").write_bytes(webp(10, 5))
        self.change("x.md", "Sale.\nImage: media/card.webp", "Sale.\nImage: media/card.es.webp")
        self.assertProblem("x.md: «media/card.es.webp» has the suffix «.es.» but «es» is the first language and uses the "
                         "file without suffix; rename it to «media/card.webp»")

    def test_the_image_of_another_language_in_a_section_is_an_error(self):
        self.galician_image()
        self.change("x.md", "## en\n\n**1/** Out.\nImage: media/card.webp", "## en\n\n**1/** Out.\nImage: media/card.gl.webp")
        self.assertProblem("x.md (en): «media/card.gl.webp» is the image of «gl» but sits in the «## en» section; "
                         "move the line to «## gl»")

    def test_the_row_of_an_own_image_asks_for_the_image_line(self):
        self.galician_image()
        self.change("x.md", "Image: media/card.gl.webp", "")
        self.assertProblem("sheet.md: «media/card.gl.webp» lists channel «x» but x.md has no «Image: media/card.gl.webp» line")

    def test_a_name_with_a_dot_that_is_not_a_language_is_not_a_suffix(self):
        self.assertIsNone(check.language_of_file("media/v1.0.webp"))
        self.assertIsNone(check.language_of_file("media/card.webp"))
        self.assertIsNone(check.language_of_file("media/foo.bar.webp"))
        self.assertEqual(check.language_of_file("media/card.gl-mini.webp"), "gl")
        self.assertEqual(check.language_of_file("media/source/card.gl.html"), "gl")


class RedditRules(Base):
    read_on = TODAY.isoformat()

    def move_to(self, day):
        """Rename the date folder of the piece to <day> (a date)."""
        new = self.tmp / day.isoformat()
        self.folder.parent.rename(new)
        self.folder = new / self.folder.name
        self.read_on = TODAY.isoformat()

    def set_rules(self, text):
        f = (self.folder / "sheet.md").read_text(encoding="utf-8")
        self.write("sheet.md", re.sub(r"(### Rules of r/gamedev\n\n).*?(\n\n## Images)",
                                         lambda m: m.group(1) + text + m.group(2), f, flags=re.S))

    def test_without_the_rules_block(self):
        self.set_rules("")
        self.change("sheet.md", "### Rules of r/gamedev\n", "")
        self.assertProblem("sheet.md: no rules block for r/gamedev; paste the rules text (at least 200 characters, copied "
                         "from reddit.com/r/gamedev/about/rules) under a «### Rules of r/gamedev» heading inside «## Reddit» "
                         "of sheet.md")

    def test_block_too_short(self):
        self.set_rules("1. Sé amable.")
        self.assertProblem("sheet.md: the rules block of r/gamedev has 13 characters (min 200); paste the complete rules "
                         "text under «### Rules of r/gamedev» in «## Reddit» of sheet.md")

    def test_spaces_and_line_breaks_do_not_count_for_the_minimum(self):
        self.set_rules("a" + "\n" * 300 + "   " * 100 + "b")
        self.assertProblem("has 3 characters (min 200)")

    def test_exactly_at_the_minimum_passes(self):
        self.set_rules("a" * 200)
        self.assertEqual(self.problems(), "")
        self.set_rules("a" * 199)
        self.assertProblem("has 199 characters (min 200)")

    def test_the_minimum_comes_from_rules_json(self):
        rules = json.loads(json.dumps(self.rules))
        rules["reddit"]["rules_min_chars"]["value"] = 5000
        self.assertProblem("min 5000", rules=rules)

    def test_one_block_per_subreddit(self):
        self.change("sheet.md", "- **Subreddit:** r/gamedev\n", "- **Subreddit:** r/gamedev, r/IndieDev\n- **Subreddit:** r/spain\n")
        out = self.problems()
        self.assertIn("no rules block for r/IndieDev; paste the rules text", out)
        self.assertIn("no rules block for r/spain; paste the rules text", out)
        self.assertNotIn("no rules block for r/gamedev", out)
        f = (self.folder / "sheet.md").read_text(encoding="utf-8")
        self.write("sheet.md", f.replace("## Images", f"### Rules of r/IndieDev\n\n{RULES_TEXT}\n### Rules of r/spain\n\n{RULES_TEXT}\n## Images", 1))
        self.assertEqual(self.problems(), "")

    def test_the_subreddit_name_ignores_case_and_the_r_slash(self):
        self.change("sheet.md", "r/gamedev\n- **Rules read", "GameDev\n- **Rules read")
        self.assertEqual(self.problems(), "")

    def test_a_block_of_an_unlisted_subreddit(self):
        self.change("sheet.md", "### Rules of r/gamedev", "### Rules of r/other")
        out = self.problems()
        self.assertIn("no rules block for r/gamedev", out)
        self.assertIn("«### Rules of r/other» matches no «Subreddit:» line; add r/other to «Subreddit:» or remove the block", out)

    def test_repeated_block(self):
        self.change("sheet.md", "## Images", f"### Rules of r/gamedev\n\n{RULES_TEXT}\n## Images")
        self.assertProblem("«### Rules of r/gamedev» appears more than once; merge the blocks into one")

    def test_a_subreddit_with_an_odd_name(self):
        self.change("sheet.md", "r/gamedev\n- **Rules read", "r/game.dev\n- **Rules read")
        self.assertProblem("sheet.md: «Subreddit:» «r/game.dev» is not a subreddit name; write it as r/<name>")

    def test_pasted_rules_may_contain_hashes_and_lists(self):
        self.set_rules("# Normas\n\n- " + RULES_TEXT + "\n- Más.")
        self.assertEqual(self.problems(), "")

    def test_the_block_of_another_subreddit_does_not_count_for_this_one(self):
        self.set_rules("corto")
        self.change("sheet.md", "- **Subreddit:** r/gamedev\n", "- **Subreddit:** r/gamedev, r/other\n")
        self.change("sheet.md", "## Images", f"### Rules of r/other\n\n{RULES_TEXT}\n## Images")
        out = self.problems()
        self.assertIn("the rules block of r/gamedev has 5 characters", out)
        self.assertNotIn("r/other has", out)

    def test_todays_date_passes_and_tomorrows_is_future(self):
        self.assertEqual(self.problems(), "")
        day = (TODAY + timedelta(days=1)).isoformat()
        self.change("sheet.md", TODAY.isoformat() + "\n- **Self-promotion", day + "\n- **Self-promotion")
        self.assertProblem(f"sheet.md: «Rules read:» «{day}» is in the future; write the day you read the rules")

    def test_date_90_days_ago_passes_and_91_does_not(self):
        for days, ok in ((90, True), (91, False), (400, False)):
            with self.subTest(days=days):
                day = (TODAY - timedelta(days=days)).isoformat()
                self.change("sheet.md", "Rules read:** " + TODAY.isoformat(), "Rules read:** " + day)
                if ok:
                    self.assertEqual(self.problems(), "")
                else:
                    self.assertProblem(f"sheet.md: «Rules read:» «{day}» is {days} days old (max 90); read the rules again, "
                                     "paste them under «### Rules of r/<name>» and write today's date")
                self.change("sheet.md", "Rules read:** " + day, "Rules read:** " + TODAY.isoformat())

    def test_the_days_come_from_rules_json(self):
        rules = json.loads(json.dumps(self.rules))
        rules["reddit"]["rules_days"]["value"] = 7
        day = (TODAY - timedelta(days=8)).isoformat()
        self.change("sheet.md", "Rules read:** " + TODAY.isoformat(), "Rules read:** " + day)
        self.assertProblem("is 8 days old (max 7)", rules=rules)
        self.assertNotIn("days old", self.problems())

    def test_today_only_decides_the_future(self):
        out = check.check(self.folder, self.rules, today=TODAY - timedelta(days=1))
        self.assertIn("is in the future", "\n".join(out))

    def test_the_date_is_measured_against_the_day_of_the_piece_folder(self):
        folder_day = TODAY - timedelta(days=200)
        self.move_to(folder_day)
        for read_on, ok in ((0, True), (90, True), (91, False)):
            with self.subTest(read_on=read_on):
                day = (folder_day - timedelta(days=read_on)).isoformat()
                self.change("sheet.md", "Rules read:** " + self.read_on, "Rules read:** " + day)
                self.read_on = day
                if ok:
                    self.assertEqual(self.problems(), "")
                else:
                    self.assertProblem(f"sheet.md: «Rules read:» «{day}» is 91 days old (max 90); read the rules again, "
                                     "paste them under «### Rules of r/<name>» and write today's date")

    def test_a_future_date_is_rejected_against_today_even_if_the_folder_is_older(self):
        self.move_to(TODAY - timedelta(days=30))
        day = (TODAY + timedelta(days=1)).isoformat()
        self.change("sheet.md", "Rules read:** " + TODAY.isoformat(), "Rules read:** " + day)
        self.assertProblem(f"sheet.md: «Rules read:» «{day}» is in the future; write the day you read the rules")

    def test_outside_a_date_folder_it_is_measured_against_today(self):
        other = self.tmp / "loose" / "01-release"
        other.parent.mkdir()
        self.folder.rename(other)
        self.folder = other
        day = (TODAY - timedelta(days=91)).isoformat()
        self.change("sheet.md", "Rules read:** " + TODAY.isoformat(), "Rules read:** " + day)
        self.assertProblem(f"«Rules read:» «{day}» is 91 days old (max 90)")

    def test_an_empty_subreddit_does_not_take_the_next_line(self):
        self.change("sheet.md", "- **Subreddit:** r/gamedev\n", "- **Subreddit:**\n")
        self.assertProblem("reddit.md needs «Subreddit:» in sheet.md")
        self.assertEqual(check.field("Languages:\n\n## Channels\n", "Idiomas"), "")
        self.assertEqual(check.field("- **Subreddit:**   \n- **Rules read:** 2026-01-01", "Subreddit"), "")

    def test_a_subreddit_without_a_name(self):
        for value in (",", "r/", "/r/ ;"):
            with self.subTest(value):
                self.change("sheet.md", "- **Subreddit:** r/gamedev\n", f"- **Subreddit:** {value}\n")
                self.assertProblem("sheet.md: no subreddit: write «- **Subreddit:** r/<name>» in «## Reddit» before the first «###» block")
                self.change("sheet.md", f"- **Subreddit:** {value}\n", "- **Subreddit:** r/gamedev\n")

    def test_a_later_section_does_not_complete_the_rules(self):
        self.set_rules("corto\n\n### Notas\n\n" + RULES_TEXT)
        self.assertProblem("the rules block of r/gamedev has 5 characters (min 200); paste the complete rules text under "
                         "«### Rules of r/gamedev» in «## Reddit» of sheet.md; the pasted text ends at the next line "
                         "starting with «##», so paste headings as plain lines without «#», and the «Subreddit:» fields go "
                         "before the first «###» block")

    def test_a_heading_inside_the_paste_cuts_the_block(self):
        self.set_rules("corto\n#### Regla 2\n" + RULES_TEXT)
        self.assertProblem("has 5 characters (min 200)")
        self.set_rules(RULES_TEXT + "\n## Otra cosa\n\ntexto")
        self.assertEqual(self.problems(), "")

    def test_fields_after_a_block_are_not_seen(self):
        self.change("sheet.md", "- **Rules read:** " + TODAY.isoformat() + "\n", "")
        self.change("sheet.md", "## Images", "- **Rules read:** " + TODAY.isoformat() + "\n\n## Images")
        self.assertProblem("reddit.md needs «Rules read:» in sheet.md; put the field before the first «###» block of "
                         "«## Reddit», paste the subreddit rules and write the «Rules read:» line")

    def test_without_reddit_no_blocks_are_required(self):
        self.change("sheet.md", "- reddit\n", "")
        (self.folder / "reddit.md").unlink()
        self.change("sheet.md", "### Rules of r/gamedev", "### Notas")
        self.assertEqual(self.problems(), "")


class ExtraChannels(Base):
    def extra(self, name="portal", text=None):
        self.change("sheet.md", "- discord\n", f"- discord\n- {name}\n")
        self.write(f"{name}.md", text if text is not None else "## es\n\nHola.\n\n## en\n\nHello.\n")

    def test_without_options_it_asks_for_sections_and_sets_no_limit(self):
        self.extra(text="## es\n\n" + "a" * 9000 + "\n")
        out = self.problems()
        self.assertIn("portal.md: no «## en» section", out)
        self.assertNotIn("characters (max", out)

    def test_limit_per_language_section(self):
        self.extra(text="## es\n\n" + "a" * 11 + "\n\n## en\n\n" + "b" * 10 + "\n")
        out = "\n".join(check.check(self.folder, self.rules, limits={"portal": 10}))
        self.assertIn("portal.md (es): 11 characters (max 10, set with --limit portal=10); shorten it by 1", out)
        self.assertNotIn("portal.md (en)", out)

    def test_the_limit_does_not_count_image_lines(self):
        self.change("sheet.md", "Release card | x |", "Release card | x, portal |")
        self.extra(text="## es\n\n" + "a" * 10 + "\nImage: media/card.webp\n\n## en\n\nb\nImage: media/card.webp\n")
        self.assertEqual("\n".join(check.check(self.folder, self.rules, limits={"portal": 10})), "")

    def test_the_limit_of_another_channel_does_not_apply(self):
        self.extra(text="## es\n\n" + "a" * 50 + "\n\n## en\n\nb\n")
        self.assertEqual("\n".join(check.check(self.folder, self.rules, limits={"other": 10})), "")

    def test_own_format_requires_a_non_empty_file_and_no_sections(self):
        self.extra(text='{"title": "Hola", "body": "Hello"}\n')
        self.assertEqual("\n".join(check.check(self.folder, self.rules, own_format=["portal"])), "")
        self.write("portal.md", "  \n")
        self.assertIn("portal.md: empty (channel set with --own-format); write the content the other system reads",
                      "\n".join(check.check(self.folder, self.rules, own_format=["portal"])))

    def test_own_format_with_missing_file(self):
        self.extra()
        (self.folder / "portal.md").unlink()
        self.assertIn("portal.md: listed under «## Channels» but missing",
                      "\n".join(check.check(self.folder, self.rules, own_format=["portal"])))

    def test_own_format_still_looks_for_gaps_and_jargon(self):
        self.extra(text='{"t": "WIP: {{title}}"}\n')
        out = "\n".join(check.check(self.folder, self.rules, own_format=["portal"]))
        self.assertIn("portal.md: internal jargon «WIP:»", out)
        self.assertIn("portal.md: template gap «{{title}}»", out)

    def test_own_format_adds_no_deduced_languages(self):
        self.change("sheet.md", "Languages: es, en\n", "")
        self.extra(text='{"es": 1, "zz": 2}\n')
        out = "\n".join(check.check(self.folder, self.rules, own_format=["portal"]))
        self.assertIn('no languages: add "Languages: es, en" to sheet.md', out)

    def test_own_format_accepts_the_image_if_its_path_is_in_the_text(self):
        self.change("sheet.md", "Release card | x |", "Release card | x, portal |")
        self.extra(text='{"image": "media/card.webp", "title": "Hola"}\n')
        self.assertEqual("\n".join(check.check(self.folder, self.rules, own_format=["portal"])), "")

    def test_own_format_without_the_image_path_in_the_text(self):
        self.change("sheet.md", "Release card | x |", "Release card | x, portal |")
        self.extra(text='{"title": "Hola"}\n')
        self.assertIn("sheet.md: «media/card.webp» lists channel «portal» but portal.md does not contain the path "
                      "«media/card.webp» (channel with its own format); write the path in the file or remove «portal» "
                      "from the Channels cell",
                      "\n".join(check.check(self.folder, self.rules, own_format=["portal"])))

    def test_own_format_keeps_the_image_checks(self):
        self.change("sheet.md", "\n\n## Internal use", "\n| `media/anim.gif` | es: a / en: b | portal |\n\n## Internal use")
        (self.folder / "media" / "anim.gif").write_bytes(gif(10, 10))
        self.extra(text='{"image": "media/anim.gif"}\n')
        self.assertIn("portal.md: «media/anim.gif» is a .gif and portal takes .webp, .png, .jpg",
                      "\n".join(check.check(self.folder, self.rules, own_format=["portal"])))
        self.change("sheet.md", "es: a / en: b | portal", "es: a | portal")
        self.assertIn("«media/anim.gif» has no alt text in «en»",
                      "\n".join(check.check(self.folder, self.rules, own_format=["portal"])))

    def test_options_for_channels_no_piece_declares_exit_with_2(self):
        self.extra()
        for args, option in ((["--limit", "portl=5"], "--limit portl=5"), (["--own-format", "site"], "--own-format site")):
            with self.subTest(args):
                r = subprocess.run([sys.executable, str(HERE / "check.py"), *args, str(self.folder.parent)],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 2)
                self.assertIn(f"{option} names a channel that no checked piece declares in «## Channels» (declared: x, reddit, "
                              "linkedin, discord, portal); fix the channel name or drop the option", r.stdout)
        r = subprocess.run([sys.executable, str(HERE / "check.py"), "--limit", "portal=500", "--own-format", "portal",
                            str(self.folder)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("portal is in --limit and --own-format", r.stdout)
        r = subprocess.run([sys.executable, str(HERE / "check.py"), "--limit", "portal=500", str(self.folder)],
                           capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "OK"))

    def test_an_option_used_by_a_single_piece_is_valid(self):
        self.extra()
        other = self.folder.parent / "02-other"
        shutil.copytree(self.folder, other)
        self.change("sheet.md", "- discord\n- portal\n", "- discord\n")
        (self.folder / "portal.md").unlink()
        r = subprocess.run([sys.executable, str(HERE / "check.py"), "--limit", "portal=500", str(self.folder.parent)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_images_of_an_extra_channel_webp_png_and_jpg(self):
        self.extra()
        for ext, data in ((".png", png(100, 50)), (".jpg", jpeg(100, 50))):
            with self.subTest(ext):
                (self.folder / "media" / f"other{ext}").write_bytes(data)
                self.change("sheet.md", "\n\n## Internal use", f"\n| `media/other{ext}` | es: a / en: b | portal |\n\n## Internal use")
                self.write("portal.md", f"## es\n\nHola.\nImage: media/other{ext}\n\n## en\n\nHello.\nImage: media/other{ext}\n")
                self.assertEqual(self.problems(), "")
                (self.folder / "media" / f"other{ext}").unlink()
                self.change("sheet.md", f"\n| `media/other{ext}` | es: a / en: b | portal |", "")

    def test_a_webp_of_the_sheet_is_also_valid_in_an_extra_channel(self):
        self.change("sheet.md", "Release card | x |", "Release card | x, portal |")
        self.extra(text="## es\n\nHola.\nImage: media/card.webp\n\n## en\n\nHello.\nImage: media/card.webp\n")
        self.assertEqual(self.problems(), "")

    def test_a_gif_is_not_valid_in_an_extra_channel(self):
        self.change("sheet.md", "\n\n## Internal use", "\n| `media/anim.gif` | es: a / en: b | portal |\n\n## Internal use")
        (self.folder / "media" / "anim.gif").write_bytes(gif(10, 10))
        self.extra(text="## es\n\nHola.\nImage: media/anim.gif\n\n## en\n\nHello.\nImage: media/anim.gif\n")
        self.assertProblem("portal.md: «media/anim.gif» is a .gif and portal takes .webp, .png, .jpg; point to media/<name>.webp")

    def test_lowercase_channel_names(self):
        for bad in ("Portal", "mi channel", "../x", "web_site", "x (principal)"):
            with self.subTest(bad):
                self.change("sheet.md", "- discord\n", f"- discord\n- {bad}\n")
                self.assertProblem(f"sheet.md: channel «{bad}» under «## Channels» is not a valid name; use lowercase letters, "
                                 "digits and hyphens ([a-z0-9-]+), one channel per line")
                self.change("sheet.md", f"- discord\n- {bad}\n", "- discord\n")

    def test_a_channel_with_hyphen_and_digits_is_valid(self):
        self.extra("web-2", "## es\n\nHola.\n\n## en\n\nHello.\n")
        self.assertEqual(self.problems(), "")

    def test_uppercase_in_x_is_no_longer_forgiven(self):
        self.change("sheet.md", "- x\n", "- X\n")
        self.assertProblem("sheet.md: channel «X» under «## Channels» is not a valid name")


class Web(Base):
    """web.md: one ```json block for the project's website (status, date, text, wall)."""

    def setUp(self):
        super().setUp()
        self.change("sheet.md", "- discord\n", "- discord\n- web\n")
        self.change("sheet.md", "Release card | x |", "Release card | x, web |")
        self.data = {
            "status": "draft",
            "date": TODAY.isoformat(),
            "text": {"es": "Sale la versión.", "en": "Release out."},
            "wall": {
                "title": {"es": "Versión 1.0", "en": "Version 1.0"},
                "body": [{"es": "Primer párrafo.", "en": "First paragraph."}],
                "images": [{"file": "media/card.webp", "alt": {"es": "Tarjeta", "en": "Card"}}],
            },
        }
        self.web()
        self.assertEqual(self.problems(), "")

    def web(self, data=None, before="# Web: release\n\n", after=""):
        body = json.dumps(self.data if data is None else data, ensure_ascii=False, indent=2)
        self.write("web.md", f"{before}```json\n{body}\n```\n{after}")

    def set_key(self, path, value):
        """self.data with the key at path (a list of keys and indexes) set to value, or removed when value is None."""
        d = json.loads(json.dumps(self.data))
        node = d
        for k in path[:-1]:
            node = node[k]
        if value is None:
            del node[path[-1]]
        else:
            node[path[-1]] = value
        self.web(d)

    def test_without_wall_and_ready_is_valid(self):
        del self.data["wall"]
        self.data["status"] = "ready"
        self.web()
        self.change("sheet.md", "Release card | x, web |", "Release card | x |")
        self.assertEqual(self.problems(), "")

    def test_the_unfilled_template_reports_the_gaps_and_filled_is_valid(self):
        template = (HERE.parent / "template" / "web.md").read_text(encoding="utf-8")
        self.write("web.md", template)
        out = self.problems()
        self.assertIn("web.md: template gap «{{…}}» left; write the text", out)
        self.assertIn("web.md: template gap «YYYY-MM-DD» left", out)
        self.assertIn("web.md: template gap «<topic>» left", out)
        self.assertNotIn("«date» is", out)  # the date gap is reported once
        filled = (template.replace("{{…}}", "Texto").replace("YYYY-MM-DD", TODAY.isoformat())
                 .replace("<topic>", "release"))
        self.write("web.md", filled)
        self.assertEqual(self.problems(), "")

    # --- 0.x: web.md carries the English keys and the old Spanish ones, with the same values

    def with_old_keys(self, data=None):
        """self.data with every key also under its old Spanish spelling (the values, copied; status mapped)."""
        data = json.loads(json.dumps(self.data if data is None else data))
        wall = data["wall"]
        both = {"status": data["status"], "estado": {"draft": "borrador", "ready": "listo"}[data["status"]],
                "date": data["date"], "fecha": data["date"], "text": data["text"], "texto": data["text"],
                "wall": wall, "muro": {"titulo": wall["title"], "cuerpo": wall["body"],
                                       "imagenes": [{"archivo": i["file"], "alt": i["alt"]} for i in wall["images"]]}}
        return both

    def problems_and_warnings(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            out = self.problems()
        return out, err.getvalue()

    def test_both_spellings_with_the_same_values_are_valid_without_a_warning(self):
        self.web(self.with_old_keys())
        self.assertEqual(self.problems_and_warnings(), ("", ""))
        self.data["status"] = "ready"
        self.web(self.with_old_keys())
        self.assertEqual(self.problems_and_warnings(), ("", ""))

    def test_only_the_english_keys_pass_without_a_warning(self):
        self.assertEqual(self.problems_and_warnings(), ("", ""))

    def test_only_the_old_keys_pass_with_a_warning_that_asks_for_the_english_ones(self):
        both = self.with_old_keys()
        self.web({k: v for k, v in both.items() if k in ("estado", "fecha", "texto", "muro")})
        out, err = self.problems_and_warnings()
        self.assertEqual(out, "")
        self.assertIn("check.py: warning: ", err)
        self.assertIn("web.md has Spanish keys (estado, fecha, texto, muro...) without the English ones (status, date, "
                      "text, wall...); in 0.x write both with the same values (the old ones go away in 1.0)", err)

    def test_an_old_key_that_stands_alone_inside_a_wall_warns_too(self):
        both = self.with_old_keys()
        both["wall"] = {"title": both["wall"]["title"], "cuerpo": both["wall"]["body"],
                        "images": both["wall"]["images"]}
        del both["muro"]
        self.web(both)
        out, err = self.problems_and_warnings()
        self.assertEqual(out, "")
        self.assertIn("has Spanish keys", err)

    def test_a_status_that_differs_between_the_two_spellings_fails_naming_both_values(self):
        both = self.with_old_keys()
        both["estado"] = "listo"
        self.web(both)
        out, err = self.problems_and_warnings()
        self.assertIn("web.md: «estado» and «status» differ (\"listo\" and \"draft\"); in 0.x both are written with the "
                      "same value (the old keys go away in 1.0): fix «status» and «estado» to match", out)
        self.assertEqual(err, "")

    def test_a_date_and_a_text_that_differ_fail(self):
        both = self.with_old_keys()
        both["fecha"] = "2020-01-01"
        both["texto"] = {"es": "Otro.", "en": "Other."}
        self.web(both)
        out = self.problems()
        self.assertIn("«fecha» and «date» differ (\"2020-01-01\" and \"%s\")" % TODAY.isoformat(), out)
        self.assertIn("«texto» and «text» differ", out)

    def test_a_wall_that_differs_from_its_old_spelling_fails(self):
        both = self.with_old_keys()
        both["muro"]["titulo"] = {"es": "Otro", "en": "Other"}
        self.web(both)
        self.assertProblem("web.md: «muro» and «wall» differ")

    def test_a_pair_inside_the_wall_that_differs_fails_with_its_place(self):
        both = self.with_old_keys()
        both["wall"]["titulo"] = {"es": "Otro", "en": "Other"}
        self.web(both)
        self.assertProblem("web.md: «titulo» and «title» of «wall» differ")

    def test_the_old_spelling_does_not_hide_a_problem_of_the_values(self):
        both = self.with_old_keys()
        both["status"] = both["estado"] = "published"
        self.web(both)
        out, _ = self.problems_and_warnings()
        self.assertIn("web.md: «status» is \"published\"", out)

    def test_the_template_carries_both_spellings_and_checks_clean_once_filled(self):
        template = (HERE.parent / "template" / "web.md").read_text(encoding="utf-8")
        for key in ("status", "estado", "date", "fecha", "text", "texto", "wall", "muro", "title", "titulo", "body",
                    "cuerpo", "images", "imagenes", "file", "archivo"):
            self.assertIn(f'"{key}"', template)
        filled = (template.replace("{{…}}", "Texto").replace("YYYY-MM-DD", TODAY.isoformat())
                  .replace("<topic>", "release"))
        self.write("web.md", filled)
        self.assertEqual(self.problems_and_warnings(), ("", ""))

    def test_a_single_valid_json_block(self):
        self.write("web.md", "# Web\n\nSin bloque.\n")
        self.assertProblem("web.md: no ```json block; keep exactly one, as in the template (template/web.md)")
        self.web(after="\n```json\n{}\n```\n")
        self.assertProblem("web.md: 2 ```json blocks; keep exactly one")
        self.write("web.md", '```json\n{"status": "draft",}\n```\n')
        self.assertProblem("web.md: the ```json block is not valid JSON (")
        self.write("web.md", '```json\n["draft"]\n```\n')
        self.assertProblem("web.md: the ```json block must be an object with status, date, text, wall")

    def test_unknown_and_mandatory_keys(self):
        self.set_key(["slug"], "version-1")
        self.assertProblem("web.md: unknown key «slug»; remove it (keys: status, date, text, wall)")
        for k in ("status", "date", "text"):
            with self.subTest(k):
                self.set_key([k], None)
                self.assertProblem(f"web.md: no «{k}»; add it as in the template")

    def test_status_draft_or_ready(self):
        self.set_key(["status"], "published")
        self.assertProblem('web.md: «status» is "published"; write "draft" (the skill leaves it so) or "ready"')

    def test_valid_date(self):
        for bad in ("2026-13-01", "26-10-2026", 20261026):
            with self.subTest(bad):
                self.set_key(["date"], bad)
                self.assertProblem(f"web.md: «date» is {json.dumps(bad)}; write the publication date as \"YYYY-MM-DD\"")

    def test_text_carries_the_languages_of_the_sheet(self):
        self.set_key(["text"], {"es": "Sale."})
        self.assertProblem("web.md: «text» has no «en» (it is in «Languages:» of sheet.md); add its text")
        self.set_key(["text"], {"es": "Sale.", "en": " "})
        self.assertProblem("web.md: «text.en» is empty; write the text")
        self.set_key(["text"], {"es": "Sale.", "en": "Out.", "GL": "Sae."})
        self.assertProblem("web.md: «text» has the key «GL»; use two-letter lowercase ISO 639-1 codes")
        self.set_key(["text"], "Sale.")
        self.assertProblem("web.md: «text» must be an object with one text per language")

    def test_a_web_only_language_is_required_in_every_text(self):
        self.set_key(["text"], {"es": "Sale.", "en": "Out.", "gl": "Sae."})
        out = self.problems()
        self.assertIn("web.md: «wall.title» has no «gl»; add its text in that language", out)
        self.assertIn("web.md: «wall.body[0]» has no «gl»", out)
        self.assertIn("web.md: «wall.images[0].alt» has no «gl»", out)
        self.assertNotIn("sheet.md", out)
        self.set_key(["wall", "title"], {"es": "V", "en": "V", "fr": "V"})
        self.assertProblem("web.md: «wall.title» has «fr», which is not in «text»; remove it or add «fr» to «text»")

    def test_web_languages_sets_the_exact_languages(self):
        out = "\n".join(check.check(self.folder, self.rules, web_languages=["es", "gl", "en"]))
        self.assertIn("web.md: «text» has no «gl» (set with --web-languages es,gl,en); add its text", out)
        self.set_key(["text"], {"es": "Sale.", "en": "Out.", "fr": "Sort."})
        out = "\n".join(check.check(self.folder, self.rules, web_languages=["es", "en"]))
        self.assertIn("web.md: «text» has «fr», which is not in --web-languages es,en; remove it", out)

    def test_wall(self):
        self.set_key(["wall", "footer"], "x")
        self.assertProblem("web.md: unknown key «wall.footer»; remove it (keys: title, body, images)")
        self.set_key(["wall", "title"], None)
        self.assertProblem("web.md: «wall» has no «title»; add one title per language")
        self.set_key(["wall", "body"], [])
        self.assertProblem("web.md: «wall.body» must be a list of paragraphs")
        self.set_key(["wall", "title"], "Versión 1.0")
        self.assertProblem("web.md: «wall.title» must be an object with one text per language (es, en)")
        self.set_key(["wall"], ["a"])
        self.assertProblem("web.md: «wall» must be an object with title, body and images")

    def test_wall_images(self):
        self.set_key(["wall", "images"], "media/card.webp")
        self.assertProblem("web.md: «wall.images» must be a list of {file, alt}")
        self.set_key(["wall", "images", 0, "alt"], None)
        self.assertProblem("web.md: «wall.images[0]» has no «alt»; add it")
        self.set_key(["wall", "images", 0, "width"], 100)
        self.assertProblem("web.md: unknown key «wall.images[0].width»; remove it (keys: file, alt)")
        self.set_key(["wall", "images", 0, "file"], "card.webp")
        self.assertProblem("web.md: «wall.images[0].file» is «card.webp», not a render; point to media/<name>.webp")
        self.set_key(["wall", "images", 0, "file"], "media/other.webp")
        self.assertProblem(f"web.md: «media/other.webp» does not exist; render it ({RENDER} {self.folder})")

    def test_a_wall_image_without_render_is_reported_once(self):
        (self.folder / "media" / "card.webp").unlink()
        out = self.problems()
        self.assertIn(f"web.md: «media/card.webp» does not exist; render it ({RENDER} {self.folder})", out)
        self.assertNotIn("but no «file» in «wall.images»", out)

    def test_the_table_and_the_wall_match(self):
        self.set_key(["wall", "images"], [])
        self.assertProblem("sheet.md: «media/card.webp» lists channel «web» but no «file» in «wall.images» of web.md "
                         "points to it; add it there or remove «web» from the Channels cell")
        self.set_key(["wall", "images", 0, "file"], "media/card.png")
        out = self.problems()
        self.assertIn("web.md: «media/card.png» is not listed for «web» in «## Images» of sheet.md", out)
        self.assertIn("web.md: «media/card.png» is a .png and web takes .webp", out)

    def test_image_per_language(self):
        media = self.folder / "media"
        (media / "card.en.webp").write_bytes(webp())
        (media / "card.en-mini.webp").write_bytes(webp(10, 5))
        self.change("sheet.md", "| `media/card.png` |", "| `media/card.en.webp` | en: Card | web |\n| `media/card.png` |")
        self.set_key(["wall", "images", 0, "file"], {"es": "media/card.webp", "en": "media/card.en.webp"})
        self.assertEqual(self.problems(), "")
        self.set_key(["wall", "images", 0, "file"], {"es": "media/card.en.webp", "en": "media/card.webp"})
        self.assertProblem("web.md: «media/card.en.webp» is the image of «en» but sits under «es» in "
                         "«wall.images[0].file»; move it")
        self.set_key(["wall", "images", 0, "file"], {"es": "media/card.webp"})
        self.assertProblem("web.md: «wall.images[0].file» has no «en»")

    def test_jargon_in_web(self):
        self.set_key(["text", "es"], "Arreglado en QA-12.")
        self.assertProblem("web.md: internal jargon «QA-12»; move it to «## Internal use»")

    def test_web_not_requested_in_the_sheet(self):
        self.change("sheet.md", "- web\n", "")
        self.assertProblem("web.md: channel not requested; delete the file or list «web» under «## Channels» in sheet.md")

    def test_web_languages_options(self):
        r = check.parse_options(["--web-languages", "es,gl,en", "c"])
        self.assertEqual(r, (["c"], [], {}, [], ["es", "gl", "en"], None))
        for args, reason in (
            (["--web-languages", "es,GL", "c"], "--web-languages needs two-letter lowercase language codes"),
            (["--web-languages=", "c"], "--web-languages needs two-letter lowercase language codes"),
            (["--limit", "web=5", "c"], "--limit is for extra channels; web has its own checks (web.md)"),
            (["--own-format", "web", "c"], "--own-format is for extra channels; web has its own checks"),
        ):
            with self.subTest(args):
                self.assertIn(reason, check.parse_options(args)[-1])

    def test_cli_web_languages(self):
        command = [sys.executable, str(HERE / "check.py"), "--web-languages", "es,en,gl", str(self.folder)]
        r = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("web.md: «text» has no «gl» (set with --web-languages es,en,gl)", r.stdout)
        self.change("sheet.md", "- web\n", "")
        (self.folder / "web.md").unlink()
        r = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--web-languages es,en,gl names a channel that no checked piece declares in «## Channels»", r.stdout)


class Options(unittest.TestCase):
    def test_limit_and_own_format_can_be_repeated(self):
        r = check.parse_options(["--limit", "portal=500", "--limit=blog=900", "--own-format", "site",
                                     "--own-format=api", "--task-prefixes", "INS", "folder"])
        self.assertEqual(r, (["folder"], ["INS"], {"portal": 500, "blog": 900}, ["site", "api"], None, None))

    def test_misspelled_options(self):
        cases = (
            (["--limit", "portal", "c"], "--limit needs channel=N with a lowercase channel name and N >= 1"),
            (["--limit", "portal=0", "c"], "--limit needs channel=N"),
            (["--limit", "portal=diez", "c"], "--limit needs channel=N"),
            (["--limit", "Portal=5", "c"], "--limit needs channel=N"),
            (["--limit"], "--limit needs channel=N"),
            (["--limit", "x=100", "c"], "--limit is for extra channels; the limit of x is in rules.json"),
            (["--own-format", "linkedin", "c"], "--own-format is for extra channels; linkedin has its own checks"),
            (["--own-format", "Web", "c"], "--own-format needs a lowercase channel name"),
            (["--own-format"], "--own-format needs a lowercase channel name"),
            (["--limit", "site=5", "--own-format", "site", "c"], "site is in --limit and --own-format"),
            (["--other", "c"], "unknown option --other"),
            (["--task-prefixes", "A", "--task-prefixes", "", "c"], "--task-prefixes needs prefixes"),
            (["--task-prefixes", "A", "--task-prefixes", " , ", "c"], "--task-prefixes needs prefixes"),
            (["--task-prefixes=", "c"], "--task-prefixes needs prefixes"),
        )
        for args, reason in cases:
            with self.subTest(args=args):
                self.assertIn(reason, check.parse_options(args)[-1])

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(HERE / "check.py"), *args], capture_output=True, text=True)

    def test_cli_with_misspelled_options_exits_2_and_prints_the_usage(self):
        r = self.run_cli("--limit", "x=100", "folder")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--limit is for extra channels; the limit of x is in rules.json. usage: check.py", r.stdout)

    def test_cli_limit_and_own_format_on_a_piece(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        folder = tmp / "2026-10-25" / "01-piece"
        folder.mkdir(parents=True)
        (folder / "media").mkdir()
        (folder / "sheet.md").write_text("Languages: es, en\n\n## Channels\n\n- portal\n- site\n\n## Images\n\n"
                                          "| Image | Alt text | Channels |\n|---|---|---|\n\n## Published\n", encoding="utf-8")
        (folder / "portal.md").write_text("## es\n\n" + "a" * 30 + "\n\n## en\n\nb\n", encoding="utf-8")
        (folder / "site.md").write_text('{"a": 1}\n', encoding="utf-8")
        r = self.run_cli("--limit", "portal=20", "--own-format", "site", str(folder))
        self.assertEqual(r.returncode, 1)
        self.assertIn("portal.md (es): 30 characters (max 20, set with --limit portal=20); shorten it by 10", r.stdout)
        self.assertNotIn("site.md", r.stdout)
        r = self.run_cli("--limit", "portal=30", "--own-format", "site", str(folder))
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "OK"))
        r = self.run_cli(str(folder))
        self.assertIn("site.md: no «## es» section", r.stdout)


class OldNames(Base):
    """0.x compatibility: the Spanish option names and the pre-A8 piece layout are accepted with a warning."""

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(HERE / "check.py"), *args], capture_output=True, text=True)

    def old_layout(self):
        """The Base piece rewritten with the old Spanish names: ficha.md, medios/fuente/, Spanish headings and web keys."""
        sheet = (self.folder / "sheet.md").read_text(encoding="utf-8")
        for new, old in (("## Channels", "## Canales"), ("## Images", "## Imágenes"), ("## Internal use", "## Uso interno"),
                         ("## Published", "## Publicado"), ("Languages:", "Idiomas:"), ("**Rules read:**", "**Normas leídas:**"),
                         ("**Self-promotion:**", "**Autopromoción:**"), ("### Rules of", "### Normas de"),
                         ("| Image |", "| Imagen |"), ("media/", "medios/")):
            sheet = sheet.replace(new, old)
        (self.folder / "sheet.md").unlink()
        (self.folder / "ficha.md").write_text(sheet, encoding="utf-8")
        (self.folder / "media").rename(self.folder / "medios")
        (self.folder / "medios" / "source").rename(self.folder / "medios" / "fuente")
        for name in ("x.md", "linkedin.md"):
            self.write(name, (self.folder / name).read_text(encoding="utf-8").replace("Image: media/", "Imagen: medios/"))

    def test_the_old_options_are_accepted_with_a_warning_that_names_the_new_one(self):
        for old, new in (("--prefijos-tarea", "--task-prefixes"), ("--limite", "--limit"),
                         ("--formato-propio", "--own-format"), ("--idiomas-web", "--web-languages")):
            with self.subTest(old=old):
                r = self.run_cli(old, "es,en" if old == "--idiomas-web" else "x=5000" if old == "--limite" else "x", str(self.folder))
                self.assertIn(f"check.py: warning: {old} is deprecated; use {new}", r.stderr)
                self.assertNotIn("unknown option", r.stdout + r.stderr)

    def test_the_old_option_with_an_equals_sign_keeps_its_value(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(check.rename_old_options(["--limite=site=5", "folder"]), ["--limit=site=5", "folder"])
        self.assertEqual(err.getvalue().strip(), "check.py: warning: --limite is deprecated; use --limit")

    def test_the_new_options_give_no_warning(self):
        r = self.run_cli("--limit", "site=500", str(self.folder))
        self.assertEqual(r.stderr, "")

    def test_a_piece_with_the_old_layout_passes_with_a_warning(self):
        self.old_layout()
        r = self.run_cli(str(self.folder))
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "OK"), r.stdout)
        self.assertIn("uses the old Spanish layout (ficha.md, medios/); rename ficha.md to sheet.md, medios/ to media/ "
                      "and its fuente/ to source/", r.stderr)

    def test_a_piece_with_the_old_layout_still_reports_its_problems(self):
        self.old_layout()
        (self.folder / "medios" / "card.png").unlink()
        self.assertIn("card.png", self.run_cli(str(self.folder)).stdout)

    def test_the_old_web_keys_are_translated(self):
        self.old_layout()
        (self.folder / "ficha.md").write_text((self.folder / "ficha.md").read_text(encoding="utf-8")
                                              .replace("- discord\n", "- discord\n- web\n")
                                              .replace("Release card | x |", "Release card | x, web |"), encoding="utf-8")
        data = {"estado": "borrador", "fecha": TODAY.isoformat(), "texto": {"es": "Sale.", "en": "Out."},
                "muro": {"titulo": {"es": "V", "en": "V"}, "cuerpo": [{"es": "P", "en": "P"}],
                         "imagenes": [{"archivo": "medios/card.webp", "alt": {"es": "T", "en": "C"}}]}}
        self.write("web.md", "# Web\n\n```json\n" + json.dumps(data, ensure_ascii=False) + "\n```\n")
        r = self.run_cli(str(self.folder))
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "OK"), r.stdout)


class Reading(Base):
    def test_invalid_utf8_in_the_sheet_is_a_clean_error(self):
        (self.folder / "sheet.md").write_bytes(b"Languages: es\n\xff\xfe")
        self.assertEqual(check.check(self.folder, self.rules), ["sheet.md: not valid UTF-8 text; open it in an editor and save it as UTF-8"])

    def test_invalid_utf8_in_a_channel_does_not_hide_the_rest(self):
        (self.folder / "x.md").write_bytes(b"## es\n\xe9\n")
        self.change("linkedin.md", "Texto largo.", "WIP: x")
        out = self.problems()
        self.assertIn("x.md: not valid UTF-8 text; open it in an editor and save it as UTF-8", out)
        self.assertIn("linkedin.md: internal jargon «WIP:»", out)
        self.assertNotIn("x.md: listed under", out)

    def test_cli_with_invalid_utf8_gives_no_traceback(self):
        (self.folder / "discord.md").write_bytes(b"\x80\x81")
        r = subprocess.run([sys.executable, str(HERE / "check.py"), str(self.folder)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("discord.md: not valid UTF-8 text", r.stdout)
        self.assertNotIn("Traceback", r.stdout + r.stderr)

    def test_a_leading_bom_does_not_break_the_sections(self):
        t = (self.folder / "linkedin.md").read_text(encoding="utf-8")
        (self.folder / "linkedin.md").write_bytes(b"\xef\xbb\xbf" + t.encode("utf-8"))
        self.assertEqual(self.problems(), "")


class MisnamedPieces(Base):
    def test_a_misnamed_folder_without_a_sheet_is_checked_and_reported(self):
        bad = self.folder.parent / "mi-piece"
        bad.mkdir()
        (bad / "x.md").write_text("## es\n\nHola\n", encoding="utf-8")
        self.assertEqual([p.name for p in check.pieces(self.folder.parent)], ["01-release", "mi-piece"])
        out = "\n".join(check.check(bad, self.rules))
        self.assertIn("folder name: expected <dir>/YYYY-MM-DD/NN-<topic>", out)
        self.assertIn("no sheet.md", out)

    def test_cli_counts_it_as_a_failure(self):
        bad = self.tmp / "2026-10-25" / "no-number"
        (bad / "media").mkdir(parents=True)
        r = subprocess.run([sys.executable, str(HERE / "check.py"), str(self.tmp)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"{bad}: folder name: expected", r.stdout)
        self.assertIn(f"{bad}: no sheet.md", r.stdout)

    def test_folders_that_are_not_pieces_are_left_alone(self):
        (self.tmp / "proposals").mkdir()
        (self.tmp / "proposals" / "2026-10-25.md").write_text("# Proposals\n", encoding="utf-8")
        notes = self.folder.parent / "notes"
        notes.mkdir()
        (notes / "a.txt").write_text("x", encoding="utf-8")
        self.assertEqual([p.name for p in check.pieces(self.tmp)], ["01-release"])

    def test_a_misnamed_folder_with_only_an_extra_channel_is_checked(self):
        bad = self.folder.parent / "site"
        bad.mkdir()
        (bad / "site.md").write_text('{"a": 1}\n', encoding="utf-8")
        self.assertEqual([p.name for p in check.pieces(self.tmp)], ["01-release", "site"])
        r = subprocess.run([sys.executable, str(HERE / "check.py"), str(self.tmp)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"{bad}: folder name: expected <dir>/YYYY-MM-DD/NN-<topic>", r.stdout)
        self.assertIn(f"{bad}: no sheet.md", r.stdout)

    def test_proposals_at_the_root_is_not_a_piece_even_with_md(self):
        (self.tmp / "proposals").mkdir()
        (self.tmp / "proposals" / "portal.md").write_text("# Proposals\n", encoding="utf-8")
        self.assertEqual([p.name for p in check.pieces(self.tmp)], ["01-release"])


if __name__ == "__main__":
    unittest.main()
