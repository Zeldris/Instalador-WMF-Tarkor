"""Tests of render.mjs and of the piece template (template/). render.mjs is run with node as a child process: its
arguments and sizes through `--plan` (no Playwright, no ImageMagick), its fail-closed messages with a folder where
Playwright or ImageMagick are missing, its output names with a stub Playwright and a stub `magick`, and, when
Playwright, Chromium and ImageMagick are installed, with the real ones. The template is checked against
check.py. Run: python3 -m unittest discover -s skills/gw-media-content/scripts"""
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from datetime import date
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check  # noqa: E402

RENDER = HERE / "render.mjs"
TEMPLATE = HERE.parent / "template"
NODE = shutil.which("node")
NO_NODE = "node is not installed; render.mjs is run with node (install it from nodejs.org)"


def webp(width=100, height=50):
    """The same minimal WebP header that test_check.py builds: enough for the size check."""
    body = b"WEBPVP8X" + (10).to_bytes(4, "little") + bytes(4) + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def valid_png(width=8, height=8):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\x00" + b"\x40\x80\xc0" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def make_executable(path: Path, text: str):
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


# A `magick` that says it knows WebP and creates its last argument (the output), logging its arguments.
MAGICK = """#!/bin/sh
if [ "$1" = "-list" ]; then echo "WEBP  rw"; exit 0; fi
echo "$@" >> "$MAGICK_LOG"
for last; do :; done
# the stub only creates the output (the tests run with an empty PATH, so no cp or cat)
: > "$last"
"""
# A Playwright with just what render.mjs calls. The environment makes it misbehave: GW_STUB_BROKEN lists broken images,
# GW_STUB_OVERFLOW overflows, GW_STUB_GAPS leaves {{ in the text, GW_STUB_PAGEERROR throws in the page, GW_STUB_REQFAIL
# fails a request and GW_STUB_PDFPAGES sets the pages of the PDF. The page evaluates three times: images, gaps, overflow.
PLAYWRIGHT = """
const fs = require('fs');
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64');
const record = (obj) => fs.appendFileSync(process.env.GW_STUB_LOG, JSON.stringify(obj) + '\\n');
exports.chromium = { launch: async () => {
  if (process.env.GW_STUB_NO_CHROMIUM) throw new Error('Executable does not exist at /nowhere\\nsecond line');
  return { close: async () => {}, newContext: async (options) => {
    const context = {
      route: async (pattern, handler) => {
        let aborted = false;
        await handler({ abort: async () => { aborted = true; } });
        record({ route: pattern.source, flags: pattern.flags, http: pattern.test('http://a.b/c'), https: pattern.test('https://a.b/c'), file: pattern.test('file:///a'), aborted });
      },
      close: async () => {},
      newPage: async () => {
        let calls = 0;
        const handlers = {};
        return {
          on: (event, f) => { handlers[event] = f; },
          goto: async () => {
            if (process.env.GW_STUB_PAGEERROR) handlers.pageerror(new Error(process.env.GW_STUB_PAGEERROR + '\\n    at x'));
            if (process.env.GW_STUB_REQFAIL) handlers.requestfailed({ url: () => process.env.GW_STUB_REQFAIL });
          },
          evaluate: async () => {
            const n = ++calls;
            if (n === 1) return process.env.GW_STUB_BROKEN ? ['broken.png'] : [];
            if (n === 2) return !!process.env.GW_STUB_GAPS;
            return process.env.GW_STUB_OVERFLOW ? ['div.window has more content than room (9x9 in 1x1)'] : [];
          },
          screenshot: async ({ path, clip }) => {
            fs.writeFileSync(path, png);
            record({ clip, viewport: options.viewport, scale: options.deviceScaleFactor });
          },
          pdf: async (o) => {
            record({ pdf: o });
            const n = Number(process.env.GW_STUB_PDFPAGES ?? process.env.GW_STUB_SLIDES ?? 3);
            fs.writeFileSync(o.path, '%PDF-1.4 ' + o.width + 'x' + o.height + '\\n' + '<</Type /Page /Parent 1 0 R>>\\n'.repeat(n) + '<</Type /Pages /Count ' + n + '>>');
          },
          locator: () => ({ count: async () => Number(process.env.GW_STUB_SLIDES ?? 3) }),
        };
      },
    };
    return context;
  } };
} };
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.day_dir = self.tmp / "2026-10-25"
        self.piece = self.day_dir / "01-test"
        (self.piece / "media" / "source").mkdir(parents=True)
        self.empty = self.tmp / "empty"
        self.empty.mkdir()

    def source(self, name, text="<p>ok</p>", piece=None):
        path = (piece or self.piece) / "media" / "source" / name
        path.write_text(text, encoding="utf-8") if isinstance(text, str) else path.write_bytes(text)

    def render(self, *args, cwd=None, env=None, path=None):
        """Runs render.mjs; PATH holds only `path` (an empty folder by default) and HOME is the tempdir, so what the
        run finds is what the test put there."""
        e = {"PATH": str(path or self.empty), "HOME": str(self.tmp), "MAGICK_LOG": str(self.tmp / "magick.log"),
             "GW_STUB_LOG": str(self.tmp / "stub.log")}
        e.update(env or {})
        return subprocess.run([NODE, str(RENDER), *map(str, args)], capture_output=True, text=True, cwd=cwd or self.tmp, env=e)

    def plan(self, *args):
        r = self.render("--plan", *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def fake_playwright(self):
        folder = self.tmp / "node_modules" / "playwright"
        folder.mkdir(parents=True)
        (folder / "package.json").write_text('{"name": "playwright", "main": "index.js"}')
        (folder / "index.js").write_text(PLAYWRIGHT)

    def fake_magick(self):
        bin_ = self.tmp / "bin"
        bin_.mkdir()
        make_executable(bin_ / "magick", MAGICK)
        return bin_


@unittest.skipUnless(NODE, NO_NODE)
class Arguments(Base):
    def test_no_arguments_is_a_usage_error(self):
        r = self.render()
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage: node render.mjs", r.stderr)

    def test_it_also_runs_through_a_symlink(self):
        # npx and node_modules/.bin run the script through a link: the main guard has to resolve it
        link = self.tmp / "render-link.mjs"
        os.symlink(RENDER, link)
        r = subprocess.run([NODE, str(link)], capture_output=True, text=True, cwd=self.tmp, env={"PATH": str(self.empty)})
        self.assertEqual(r.returncode, 2, "through a symlink the script did nothing")
        self.assertIn("usage: node render.mjs", r.stderr)

    def test_help(self):
        r = self.render("--help")
        self.assertEqual((r.returncode, "usage: node render.mjs" in r.stdout), (0, True))

    def test_unknown_option(self):
        r = self.render("--fast", self.piece)
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown option --fast", r.stderr)

    def test_folder_that_does_not_exist(self):
        r = self.render("--plan", self.tmp / "nothing")
        self.assertEqual(r.returncode, 1)
        self.assertIn("is not a folder", r.stderr)

    def test_folder_without_sources(self):
        r = self.render("--plan", self.empty)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no media/source/", r.stderr)

    def test_empty_source(self):
        r = self.render("--plan", self.piece)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no source (.html, .svg, .png or .jpg)", r.stderr)

    def test_default_size_and_outputs(self):
        self.source("card.html")
        (f,) = self.plan(self.piece)[0]["sources"]
        self.assertEqual((f["source"], f["kind"], f["size"]), ("card.html", "page", {"width": 1200, "height": 675}))
        self.assertEqual([Path(s).name for s in f["outputs"]], ["card.webp", "card-mini.webp", "card.png"])

    def test_old_spanish_folders_are_planned_with_a_warning(self):
        old = self.day_dir / "02-old"
        (old / "medios" / "fuente").mkdir(parents=True)
        (old / "medios" / "fuente" / "card.html").write_text("<p>ok</p>", encoding="utf-8")
        r = self.render("--plan", old)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("warning: ", r.stderr)
        self.assertIn("uses the old folders medios/fuente/; rename them to media/source/", r.stderr)
        (f,) = json.loads(r.stdout)[0]["sources"]
        self.assertEqual([Path(s).parent.name for s in f["outputs"]], ["medios"] * 3)

    def test_the_old_carrusel_prefix_is_a_carousel_with_a_warning(self):
        self.source("carrusel-lanzamiento.html", '<section class="slide">a</section>')
        r = self.render("--plan", self.piece)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('starts with "carrusel"; rename it to start with "carousel"', r.stderr)
        (f,) = json.loads(r.stdout)[0]["sources"]
        self.assertEqual((f["kind"], [Path(s).name for s in f["outputs"]]), ("pdf", ["carrusel-lanzamiento.pdf"]))

    def test_a_carousel_prefix_gives_no_warning(self):
        self.source("carousel-launch.html", '<section class="slide">a</section>')
        r = self.render("--plan", self.piece)
        self.assertEqual((r.returncode, r.stderr), (0, ""))

    def test_size_from_the_gw_size_tag(self):
        self.source("a.html", '<meta charset="utf-8">\n<meta name="gw-size" content="1080x1350">')
        self.assertEqual(self.plan(self.piece)[0]["sources"][0]["size"], {"width": 1080, "height": 1350})

    def test_size_with_swapped_attributes_uppercase_and_times_sign(self):
        for source in ('<meta content="1080x1350" name="gw-size">', "<META NAME='GW-SIZE' CONTENT='1080X1350'>",
                       '<meta name="gw-size" content="1080 \u00d7 1350">', "<meta name=gw-size content=1080x1350>",
                       '<meta\n  name="gw-size"\n  content="1080 x 1350"\n>'):
            with self.subTest(source=source):
                self.source("a.html", source)
                self.assertEqual(self.plan(self.piece)[0]["sources"][0]["size"], {"width": 1080, "height": 1350})

    def test_a_commented_gw_size_tag_does_not_count(self):
        self.source("a.html", '<!-- <meta name="gw-size" content="50x50"> -->\n<meta name="gw-size" content="1080x1350">')
        self.assertEqual(self.plan(self.piece)[0]["sources"][0]["size"], {"width": 1080, "height": 1350})
        self.source("a.html", '<!-- <meta name="gw-size" content="1080x1350"> -->')
        self.assertEqual(self.plan(self.piece)[0]["sources"][0]["size"], {"width": 1200, "height": 675})

    def test_a_gw_size_that_cannot_be_read_fails(self):
        for source in ('<meta name="gw-size" content="grande">', '<meta name="gw-size" content="1080">', '<meta name="gw-size">',
                       '<meta name="gw-size" content="1080x">', "<!-- gw-size: ancho por alto -->"):
            with self.subTest(source=source):
                self.source("a.html", source)
                r = self.render("--plan", self.piece)
                self.assertEqual(r.returncode, 1)
                self.assertIn("cannot be read as WIDTHxHEIGHT", r.stderr)
                self.assertIn('<meta name="gw-size" content="1200x675">', r.stderr)  # the fix

    def test_size_of_an_svg_in_a_comment(self):
        self.source("logo.svg", "<!-- gw-size: 800x400 --><svg xmlns='http://www.w3.org/2000/svg'/>")
        self.assertEqual(self.plan(self.piece)[0]["sources"][0]["size"], {"width": 800, "height": 400})

    def test_size_out_of_range(self):
        self.source("a.html", '<meta name="gw-size" content="50x50">')
        r = self.render("--plan", self.piece)
        self.assertEqual(r.returncode, 1)
        self.assertIn("gw-size 50x50 is out of range", r.stderr)

    def test_the_carousel_comes_out_as_pdf(self):
        self.source("carousel-version.html", '<meta name="gw-size" content="1080x1350">')
        (f,) = self.plan(self.piece)[0]["sources"]
        self.assertEqual((f["kind"], [Path(s).name for s in f["outputs"]]), ("pdf", ["carousel-version.pdf"]))

    def test_a_screenshot_comes_out_as_webp_and_png(self):
        self.source("screen.jpg", b"\xff\xd8\xff")
        (f,) = self.plan(self.piece)[0]["sources"]
        self.assertEqual((f["kind"], f["size"], len(f["outputs"])), ("screenshot", None, 3))

    def test_other_files_are_not_sources(self):
        self.source("card.html")
        self.source("notes.txt", "x")
        self.assertEqual([f["source"] for f in self.plan(self.piece)[0]["sources"]], ["card.html"])

    def test_two_sources_with_the_same_name(self):
        self.source("a.html")
        self.source("a.png", b"x")
        r = self.render("--plan", self.piece)
        self.assertEqual(r.returncode, 1)
        self.assertIn("would both give media/a.*", r.stderr)

    def test_request_one_source(self):
        self.source("a.html")
        self.source("b.html")
        self.assertEqual([f["source"] for f in self.plan(self.piece, "media/source/b.html")[0]["sources"]], ["b.html"])

    def test_request_a_source_that_does_not_exist(self):
        self.source("a.html")
        r = self.render("--plan", self.piece, "z.html")
        self.assertEqual(r.returncode, 1)
        self.assertIn("z.html is not a source", r.stderr)

    def test_the_date_folder_expands_to_its_pieces(self):
        other = self.day_dir / "02-other"
        (other / "media" / "source").mkdir(parents=True)
        self.source("a.html")
        self.source("b.html", piece=other)
        (self.day_dir / "03-no-media").mkdir()
        self.assertEqual([Path(p["piece"]).name for p in self.plan(self.day_dir)], ["01-test", "02-other"])


@unittest.skipUnless(NODE, NO_NODE)
class FailsClosed(Base):
    def test_without_playwright(self):
        self.source("card.html")
        r = self.render(self.piece, path=self.fake_magick())
        self.assertEqual(r.returncode, 1)
        self.assertIn("Playwright not found", r.stderr)
        self.assertIn("npm i -D playwright && npx playwright install chromium", r.stderr)
        self.assertFalse((self.piece / "media" / "card.webp").exists())

    def test_playwright_is_also_looked_up_in_gw_playwright_dir(self):
        self.source("card.html")
        other_dir = self.tmp / "other_dir"
        (other_dir / "node_modules" / "playwright").mkdir(parents=True)
        (other_dir / "node_modules" / "playwright" / "package.json").write_text('{"name": "playwright", "main": "index.js"}')
        (other_dir / "node_modules" / "playwright" / "index.js").write_text(PLAYWRIGHT)
        r = self.render(self.piece, path=self.fake_magick(), env={"GW_PLAYWRIGHT_DIR": str(other_dir)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.piece / "media" / "card.webp").is_file())

    def test_without_imagemagick(self):
        self.source("card.html")
        self.fake_playwright()
        r = self.render(self.piece)
        self.assertEqual(r.returncode, 1)
        self.assertIn("ImageMagick with WebP support not found", r.stderr)
        self.assertIn("apt install imagemagick webp", r.stderr)
        self.assertIn("brew install imagemagick webp", r.stderr)

    def test_imagemagick_without_webp(self):
        self.source("card.html")
        self.fake_playwright()
        bin_ = self.tmp / "bin"
        bin_.mkdir()
        make_executable(bin_ / "magick", '#!/bin/sh\necho "PNG  rw"\n')
        r = self.render(self.piece, path=bin_)
        self.assertEqual(r.returncode, 1)
        self.assertIn("ImageMagick with WebP support not found", r.stderr)

    def test_a_carousel_only_needs_playwright(self):
        self.source("carousel.html")
        self.fake_playwright()
        r = self.render(self.piece)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.piece / "media" / "carousel.pdf").is_file())

    def test_a_screenshot_only_needs_imagemagick(self):
        self.source("screen.png", b"png")
        r = self.render(self.piece, path=self.fake_magick())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(p.name for p in (self.piece / "media").glob("*.*")), ["screen-mini.webp", "screen.png", "screen.webp"])

    def test_chromium_not_installed(self):
        self.source("card.html")
        self.fake_playwright()
        r = self.render(self.piece, path=self.fake_magick(), env={"GW_STUB_NO_CHROMIUM": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot start Chromium (Executable does not exist at /nowhere)", r.stderr)
        self.assertIn("npx playwright install chromium", r.stderr)


@unittest.skipUnless(NODE, NO_NODE)
class WithFakePlaywright(Base):
    """Output names, sizes and error handling with a stub Playwright and a stub magick."""

    def setUp(self):
        super().setUp()
        self.fake_playwright()
        self.bin = self.fake_magick()

    def test_a_page_gives_webp_mini_and_png(self):
        self.source("card.html", '<meta name="gw-size" content="1200x675">')
        r = self.render(self.piece, path=self.bin)
        self.assertEqual(r.returncode, 0, r.stderr)
        media = self.piece / "media"
        for n in ("card.webp", "card-mini.webp", "card.png"):
            self.assertTrue((media / n).is_file(), n)
        log = (self.tmp / "magick.log").read_text().splitlines()
        self.assertEqual([("-resize 1600x>" in l, "-resize 720x>" in l, "-quality" in l) for l in log],
                         [(True, False, True), (False, True, True), (True, False, False)])

    def test_the_size_of_the_tag_reaches_the_capture(self):
        self.source("a.html", '<meta name="gw-size" content="1000x500">')
        r = self.render(self.piece, path=self.bin)
        self.assertEqual(r.returncode, 0, r.stderr)
        (seen,) = [json.loads(l) for l in (self.tmp / "stub.log").read_text().splitlines() if '"clip"' in l]
        size = {"width": 1000, "height": 500}
        self.assertEqual((seen["viewport"], seen["clip"], seen["scale"]), (size, {"x": 0, "y": 0, **size}, 1))

    def test_the_carousel_gives_a_pdf_of_its_size(self):
        self.source("carousel.html", '<meta name="gw-size" content="1080x1350">')
        r = self.render(self.piece, path=self.bin)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.piece / "media" / "carousel.pdf").read_text().startswith("%PDF-1.4 1080pxx1350px"))
        self.assertIn("(3 pages", r.stdout)
        self.assertFalse((self.piece / "media" / "carousel.webp").exists())

    def test_the_pdf_takes_the_gw_size_and_not_the_stylesheet_size(self):
        self.source("carousel.html", '<meta name="gw-size" content="1080x1350"><style>@page { size: 500px 500px }</style>')
        r = self.render(self.piece, path=self.bin)
        self.assertEqual(r.returncode, 0, r.stderr)
        (options,) = [json.loads(l)["pdf"] for l in (self.tmp / "stub.log").read_text().splitlines() if '"pdf"' in l]
        self.assertEqual((options["width"], options["height"]), ("1080px", "1350px"))
        self.assertNotIn("preferCSSPageSize", options)

    def test_a_pdf_with_more_pages_than_slides_fails_and_leaves_no_output(self):
        self.source("carousel.html")
        r = self.render(self.piece, path=self.bin, env={"GW_STUB_SLIDES": "3", "GW_STUB_PDFPAGES": "5"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("the PDF has 5 page(s) and the carousel 3 slide(s)", r.stderr)
        self.assertFalse((self.piece / "media" / "carousel.pdf").exists())

    def test_a_carousel_without_slides_fails(self):
        self.source("carousel.html")
        r = self.render(self.piece, path=self.bin, env={"GW_STUB_SLIDES": "0"})
        self.assertEqual(r.returncode, 1)
        self.assertIn('no <section class="slide">', r.stderr)

    def test_a_broken_image_fails_and_leaves_no_output(self):
        self.source("a.html")
        r = self.render(self.piece, path=self.bin, env={"GW_STUB_BROKEN": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("image(s) that do not load: broken.png", r.stderr)
        self.assertFalse((self.piece / "media" / "a.webp").exists())

    def test_overflowing_content_fails(self):
        self.source("a.html")
        r = self.render(self.piece, path=self.bin, env={"GW_STUB_OVERFLOW": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("the content overflows 1200x675 (div.window has more content than room (9x9 in 1x1))", r.stderr)

    def test_a_page_error_fails(self):
        self.source("a.html")
        r = self.render(self.piece, path=self.bin, env={"GW_STUB_PAGEERROR": "boom is not defined"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("a.html: the page's script fails: boom is not defined; fix the script in the source", r.stderr)
        self.assertNotIn("at x", r.stderr)
        self.assertFalse((self.piece / "media" / "a.webp").exists())

    def test_an_unfilled_gap_fails(self):
        self.source("a.html")
        r = self.render(self.piece, path=self.bin, env={"GW_STUB_GAPS": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("fill the gaps in a.html", r.stderr)
        self.assertFalse((self.piece / "media" / "a.webp").exists())

    def test_the_network_is_blocked(self):
        self.source("a.html")
        r = self.render(self.piece, path=self.bin)
        self.assertEqual(r.returncode, 0, r.stderr)
        (path,) = [json.loads(l) for l in (self.tmp / "stub.log").read_text().splitlines() if '"route"' in l]
        self.assertEqual((path["http"], path["https"], path["file"], path["aborted"]), (True, True, False, True))

    def test_a_failing_request_is_a_resource_that_does_not_load(self):
        self.source("a.html")
        r = self.render(self.piece, path=self.bin, env={"GW_STUB_REQFAIL": "https://example.com/a.css"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("resource(s) that do not load: https://example.com/a.css", r.stderr)
        self.assertIn("the network is blocked", r.stderr)
        self.assertFalse((self.piece / "media" / "a.webp").exists())

    def test_a_failure_does_not_stop_rendering_the_rest(self):
        self.source("a.html")
        self.source("screen.png", b"png")
        r = self.render(self.piece, path=self.bin, env={"GW_STUB_OVERFLOW": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertTrue((self.piece / "media" / "screen.webp").is_file())

    def test_the_date_folder_renders_each_piece(self):
        other = self.day_dir / "02-other"
        (other / "media" / "source").mkdir(parents=True)
        self.source("a.html")
        self.source("b.html", piece=other)
        r = self.render(self.day_dir, path=self.bin)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.piece / "media" / "a.webp").is_file())
        self.assertTrue((other / "media" / "b.webp").is_file())


def has_real_render():
    """(True, '') when Playwright and ImageMagick with WebP are installed; otherwise (False, reason)."""
    if not NODE:
        return False, NO_NODE
    pw_dir = os.environ.get("GW_PLAYWRIGHT_DIR")
    ok = subprocess.run([NODE, "-e", "require(require.resolve('playwright', {paths: [process.cwd(), process.env.GW_PLAYWRIGHT_DIR || '.']}))"],
                        capture_output=True, cwd=pw_dir or os.getcwd())
    if ok.returncode:
        return False, "Playwright is not installed (npm i -D playwright && npx playwright install chromium); the real render needs it"
    for command in ("magick", "convert"):
        if shutil.which(command):
            try:
                if "WEBP" in subprocess.run([command, "-list", "format"], capture_output=True, text=True).stdout:
                    return True, ""
            except OSError:
                pass
    return False, "ImageMagick with WebP support is not installed; the real render needs it"


# What would reach the network: a src, href, poster or srcset with http(s):// or protocol-relative //, a CSS url() the
# same way, @import and <link>.
NETWORK = re.compile(r"""(?ix)
    \b(?:src|href|poster|data|action)\s*=\s*["']?\s*(?:https?:)?//
  | \bsrcset\s*=\s*["'][^"']*?(?:https?:)?//
  | url\(\s*["']?\s*(?:https?:)?//
  | @import | <link\b""")


def fill(text: str) -> str:
    """Fixture filler: the template's placeholders become valid text (a date for YYYY-MM-DD, a number for JSON)."""
    text = text.replace("YYYY-MM-DD", date.today().isoformat()).replace("<topic>", "test")
    text = text.replace("{{paste the subreddit rules here, as they are}}", "texto de prueba " * 15)
    text = text.replace("{{subreddit}}", "prueba")
    text = text.replace("{{número}}", "5").replace("{{before.png}}", "before.png").replace("{{after.png}}", "after.png")
    return re.sub(r"\{\{[^}]*\}\}", "texto de prueba", text)


class Template(Base):
    def copy_template(self):
        target = self.tmp / "content" / "2026-10-25" / "01-test"
        shutil.copytree(TEMPLATE, target)
        return target

    def test_the_template_has_everything(self):
        expected = {"sheet.md", "x.md", "reddit.md", "linkedin.md", "discord.md", "web.md"}
        self.assertEqual({p.name for p in TEMPLATE.glob("*.md")}, expected)
        sources = {p.name for p in (TEMPLATE / "media" / "source").glob("*.html")}
        self.assertEqual(sources, {"card.html", "diagram.html", "metrics.html", "quote.html", "code.html", "before-after.html", "carousel.html"})

    def test_each_source_declares_its_size_and_is_self_contained(self):
        for f in (TEMPLATE / "media" / "source").glob("*.html"):
            t = f.read_text(encoding="utf-8")
            m = re.search(r'<meta name="gw-size" content="(\d+)x(\d+)">', t)
            self.assertTrue(m, f"{f.name}: no gw-size")
            expected = ("1080", "1350") if f.name.startswith("carousel") else ("1200", "675")
            self.assertEqual(m.groups(), expected, f.name)
            self.assertNotRegex(t, NETWORK, f"{f.name}: needs the network")
            if f.name.startswith("carousel"):
                self.assertNotRegex(t, r"@page[^}]*\bsize\b", f"{f.name}: the PDF page size is the gw-size, not an @page size")
            self.assertIn("--background:", t, f"{f.name}: palette variables")
            self.assertNotIn("{{", t.split("</head>")[0], f"{f.name}: a gap in the head (the comments must not hold braces)")

    def test_the_network_regex_sees_what_goes_out_to_the_internet(self):
        for text in ('<img src="https://x.com/a.png">', "<img src='//cdn.x.com/a.png'>", '<img srcset="a.png 1x, //x.com/b.png 2x">',
                      "div { background: url(//x.com/a.png) }", 'div { background: url( "http://x.com/a.png" ) }',
                      "@font-face { src: URL(https://x.com/f.woff2) }", '<a href = "http://x.com">', '<video poster="//x.com/p.png">',
                      "<style>@import 'a.css';</style>", '<link rel="stylesheet" href="a.css">'):
            with self.subTest(text=text):
                self.assertRegex(text, NETWORK)
        for text in ('<svg xmlns="http://www.w3.org/2000/svg">', '<img src="a.png">', "div { background: url(a.png) }",
                      'div { background: url("data:image/png;base64,AAAA") }', '<img srcset="a.png 1x, b.png 2x">', "<a href=\"#x\">"):
            with self.subTest(text=text):
                self.assertNotRegex(text, NETWORK)

    def test_the_raw_template_gaps(self):
        piece = self.copy_template()
        problems = check.check(piece)
        with_gap = {p.split(":")[0] for p in problems if "template gap «" in p}
        self.assertEqual(with_gap, {"sheet.md", "x.md", "reddit.md", "linkedin.md", "discord.md", "web.md"})
        html_gaps = {p.split(":")[0].split("/")[-1] for p in problems if "template gaps {{…}} left" in p}
        self.assertEqual(len(html_gaps), 7, problems)
        # nothing else is wrong with the raw template: the rest is the renders that do not exist yet
        others = [p for p in problems if "template gap" not in p and "does not exist" not in p and "not rendered" not in p]
        # the date line is the same gap seen by the Reddit check
        others = [p for p in others if "«Rules read:» «YYYY-MM-DD»" not in p]
        self.assertEqual(others, [])

    def test_the_filled_template_passes_check(self):
        piece = self.copy_template()
        media = piece / "media"
        for f in list(piece.glob("*.md")) + list((media / "source").glob("*.html")):
            f.write_text(fill(f.read_text(encoding="utf-8")), encoding="utf-8")
        for f in (media / "source").glob("*.html"):  # a user keeps only the sources the piece uses
            if f.name != "card.html":
                f.unlink()
        (media / "card.webp").write_bytes(webp())
        (media / "card-mini.webp").write_bytes(webp(10, 5))
        (media / "card.png").write_bytes(valid_png(100, 50))
        self.assertEqual(check.check(piece), [])

    def test_the_template_alt_asks_for_both_languages(self):
        piece = self.copy_template()
        (piece / "sheet.md").write_text(fill((piece / "sheet.md").read_text(encoding="utf-8")).replace("/ en: texto de prueba", "", 1), encoding="utf-8")
        self.assertIn("has no alt text in «en»", "\n".join(check.check(piece)))


@unittest.skipUnless(*has_real_render())
class RealRender(Base):
    """Playwright's Chromium and ImageMagick for real. CI has neither (adding them costs Actions quota), so these run
    only where they are installed."""

    def real_piece(self):
        piece = self.tmp / "content" / "2026-10-25" / "01-test"
        shutil.copytree(TEMPLATE / "media", piece / "media")
        for f in (piece / "media" / "source").glob("*.html"):
            t = fill(f.read_text(encoding="utf-8").replace("{{cifra}}", "42")).replace("texto de prueba</pre>", "const a = 1; // x</pre>")
            f.write_text(t, encoding="utf-8")
        for n in ("before", "after"):
            (piece / "media" / "source" / f"{n}.png").write_bytes(valid_png())
        return piece

    def run_render(self, piece, *sources):
        r = subprocess.run([NODE, str(RENDER), str(piece), *sources], capture_output=True, text=True, env=dict(os.environ),
                           cwd=os.environ.get("GW_PLAYWRIGHT_DIR") or os.getcwd())
        if "cannot start Chromium" in r.stderr:
            self.skipTest("Chromium is not installed (npx playwright install chromium); the real render needs it")
        return r

    def change(self, piece, source, old, new):
        path = piece / "media" / "source" / source
        t = path.read_text(encoding="utf-8")
        self.assertIn(old, t)
        path.write_text(t.replace(old, new, 1), encoding="utf-8")

    def must_fail(self, piece, source, reason):
        r = self.run_render(piece, source)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(reason, r.stderr)
        self.assertFalse((piece / "media" / (Path(source).stem + ".webp")).exists(), "a failed render leaves no output")

    def loose_source(self, html):
        piece = self.tmp / "content" / "2026-10-25" / "01-test"
        (piece / "media" / "source").mkdir(parents=True)
        (piece / "media" / "source" / "x.html").write_text(html, encoding="utf-8")
        return piece

    def test_the_filled_templates_render(self):
        piece = self.real_piece()
        r = self.run_render(piece)
        self.assertEqual(r.returncode, 0, r.stderr)
        media = piece / "media"
        for n in ("card", "diagram", "metrics", "quote", "code", "before-after"):
            for suffix in (".webp", "-mini.webp", ".png"):
                self.assertTrue((media / f"{n}{suffix}").is_file(), n + suffix)
        self.assertEqual(check.dimensions(media / "card.webp"), (1200, 675))
        self.assertEqual(check.dimensions(media / "card-mini.webp")[0], 720)
        self.assertEqual(check.dimensions(media / "card.png")[0], 1200)
        self.assertEqual(check.pdf_pages(media / "carousel.pdf"), 4)

    def test_a_very_long_headline_in_the_card_overflows(self):
        piece = self.real_piece()
        self.change(piece, "card.html", "<h1>texto de prueba</h1>", "<h1>" + "titular largo " * 40 + "</h1>")
        self.must_fail(piece, "card.html", "card.html: the content overflows 1200x675")

    def test_a_code_line_of_120_characters_overflows(self):
        piece = self.real_piece()
        self.change(piece, "code.html", "const a = 1; // x</pre>", "const resultado = " + "a + " * 28 + "1;</pre>")
        self.must_fail(piece, "code.html", "div.window has more content than room")

    def test_too_many_code_lines_overflow(self):
        piece = self.real_piece()
        self.change(piece, "code.html", "const a = 1; // x</pre>", "\n".join(f"const a{i} = {i};" for i in range(14)) + "</pre>")
        self.must_fail(piece, "code.html", "the content overflows 1200x675")

    def test_ten_code_lines_fit(self):
        piece = self.real_piece()
        self.change(piece, "code.html", "const a = 1; // x</pre>", "\n".join(f"const a{i} = {i};" for i in range(10)) + "</pre>")
        r = self.run_render(piece, "code.html")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_broken_image_fails(self):
        piece = self.real_piece()
        (piece / "media" / "source" / "before.png").unlink()
        self.must_fail(piece, "before-after.html", "before-after.html: image(s) that do not load: before.png")

    def test_an_element_in_the_body_padding_overflows(self):
        # inside the page, so the document does not scroll, but outside the content box of the body
        piece = self.loose_source('<body style="margin:0;padding:60px;width:1200px;height:675px"><div style="margin-left:-40px;background:red">x</div>')
        self.must_fail(piece, "x.html", "div leaves the content box of body")

    def test_a_text_cut_by_its_box_overflows(self):
        piece = self.loose_source('<body style="margin:0"><div style="width:100px;height:24px;overflow:hidden;white-space:nowrap">'
                                   "un texto mucho mas largo que su caja</div>")
        self.must_fail(piece, "x.html", "div has more content than room")

    def test_the_network_is_blocked_for_real(self):
        piece = self.loose_source('<head><link rel="stylesheet" href="https://example.com/a.css"></head><body>hola</body>')
        self.must_fail(piece, "x.html", "resource(s) that do not load: https://example.com/a.css")

    def test_a_script_error_fails(self):
        piece = self.loose_source("<body>hola<script>funcionQueNoExiste()</script></body>")
        self.must_fail(piece, "x.html", "the page's script fails: funcionQueNoExiste is not defined")

    def test_an_unfilled_gap_fails(self):
        piece = self.real_piece()
        self.change(piece, "card.html", "<h1>texto de prueba</h1>", "<h1>{{titular}}</h1>")
        self.must_fail(piece, "card.html", "fill the gaps in card.html")

    def test_the_carousel_has_the_pages_of_its_slides(self):
        piece = self.real_piece()
        r = self.run_render(piece, "carousel.html")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("(4 pages", r.stdout)
        self.assertEqual(check.pdf_pages(piece / "media" / "carousel.pdf"), 4)


if __name__ == "__main__":
    unittest.main()
