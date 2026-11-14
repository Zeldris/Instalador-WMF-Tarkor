#!/usr/bin/env python3
# galivelop-workflow v0.6.0
"""One-page presentation sheets written in Markdown, built to a styled A4 HTML and a PDF (A10).

The sheets live as Markdown (the only place they are edited); the HTML and the PDF are generated from them, so the
three never drift. Configured by `marketingSheets` in .claude/gw.json (read through config.py):
  sources   repo-relative .md paths; the parent folder name is the language (docs/es/x.md -> <outDir>/es/x.html)
  outDir    where the HTML and PDF go (default docs/mkt)
  maxPages  most pages a PDF may have (default 1)
  css       repo-relative stylesheet embedded instead of the built-in one; its relative url(...) are rewritten
            relative to each HTML (default "" = built-in)
  timeout   seconds Chromium may take to print all the sheets (default 120)
No sources means the feature is off: every command says so and exits 0.

  python3 scripts/mkt-sheet.py build   # Markdown -> <outDir>/<lang>/<stem>.html (self-contained, A4 print CSS)
  python3 scripts/mkt-sheet.py pdf     # HTML -> <outDir>/<lang>/<stem>.pdf with Chromium (Playwright, via node)
  python3 scripts/mkt-sheet.py check   # fail when an HTML or PDF is missing or older than its source, the CSS
                                       # or this converter (the HTML is rebuilt in memory and compared)

The HTML starts its body with a comment holding the sha256 of the source; the PDF's sidecar <stem>.pdf.sha holds the
sha256 of the HTML it was printed from. Playwright is resolved from the repo folder, then from GW_PLAYWRIGHT_DIR
(install: npm i -D playwright && npx playwright install chromium). The converter covers the subset sheets need:
#..### headings, paragraphs, one-level - and 1. lists, **bold**, *em*, `code`, [text](url), pipe tables and ---.
Standard library only; the root comes from this script's path, never from the current directory.
"""
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402  (the only reader of .claude/gw.json)

SHA_COMMENT = re.compile(r"<body>\s*<!-- mkt-sheet source-sha256: ([0-9a-f]{64}) -->")
BUILD_CMD = "python3 scripts/mkt-sheet.py build"
PDF_CMD = "python3 scripts/mkt-sheet.py pdf"
MISSING_PLAYWRIGHT = ("Playwright not found (looked from the repo folder and from GW_PLAYWRIGHT_DIR). Install it and "
                      "run again: npm i -D playwright && npx playwright install chromium "
                      "(or point GW_PLAYWRIGHT_DIR at the folder that has it)")

CSS = """
@page { size: A4; margin: 16mm 16mm 14mm; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; font-size: 10pt; line-height: 1.45; color: #1f2933;
  margin: 0 auto; max-width: 178mm; padding: 8mm 0; }
h1 { font-size: 22pt; line-height: 1.15; margin: 0 0 4mm; color: #102a43; letter-spacing: -0.01em; }
h2 { font-size: 13pt; margin: 6mm 0 2mm; color: #243b53; border-bottom: 0.4mm solid #bcccdc; padding-bottom: 1mm; }
h3 { font-size: 10.5pt; margin: 4mm 0 1mm; color: #334e68; }
p { margin: 0 0 2.5mm; }
ul, ol { margin: 0 0 3mm; padding-left: 6mm; }
li { margin: 0 0 1mm; }
code { font-family: Menlo, Consolas, "DejaVu Sans Mono", monospace; font-size: 9pt; background: #f0f4f8;
  padding: 0 1mm; border-radius: 1mm; }
a { color: #0b69a3; text-decoration: none; }
hr { border: 0; border-top: 0.4mm solid #bcccdc; margin: 5mm 0; }
table { border-collapse: collapse; width: 100%; margin: 0 0 3mm; font-size: 9pt; }
th, td { border: 0.3mm solid #bcccdc; padding: 1mm 2mm; vertical-align: top; text-align: left; }
th { background: #f0f4f8; color: #243b53; }
h1, h2, h3, table, li { break-inside: avoid; }
@media print { body { padding: 0; } }
"""


class SheetError(Exception):
    """A problem the user fixes with the command in the message."""


# --- Markdown subset -> HTML -------------------------------------------------------------------------------------

def inline(text):
    """Inline markup of an already-trimmed text: code spans, links, bold, em. Everything else is HTML-escaped."""
    out = []
    for i, part in enumerate(re.split(r"`([^`]+)`", text)):
        if i % 2:
            out.append(f"<code>{html.escape(part, quote=False)}</code>")
            continue
        part = html.escape(part, quote=False)
        part = re.sub(r"\[([^\]]+)\]\(([^()\s]*(?:\([^()\s]*\)[^()\s]*)*)\)", _link, part)
        part = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<strong>\1</strong>", part)
        part = re.sub(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])", r"<em>\1</em>", part)
        out.append(part)
    return "".join(out)


def _link(m):
    url = re.sub(r"[\x00-\x20]", "", m.group(2))  # browsers ignore control characters inside a scheme
    scheme = re.match(r"([A-Za-z][A-Za-z0-9+.-]*):", html.unescape(url))
    if scheme and scheme.group(1).lower() not in ("http", "https", "mailto"):
        return m.group(0)  # not a link we emit: stays as escaped text
    return f'<a href="{url.replace(chr(34), "&quot;")}">{m.group(1)}</a>'


def _cells(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)]


def _is_sep(line):
    cells = _cells(line)
    return "|" in line and all(re.fullmatch(r":?-{1,}:?", c) for c in cells)


def convert(md):
    """The HTML body fragment for the Markdown text `md`, plus the title (first `#` heading, '' if none)."""
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out, title, pending_lines, i = [], "", [], 0

    def flush():
        if pending_lines:
            out.append("<p>" + inline(" ".join(s.strip() for s in pending_lines)) + "</p>")
            pending_lines.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        heading = re.match(r"(#{1,3})\s+(.+?)\s*#*\s*$", stripped)
        item = re.match(r"([-*]|\d+\.)\s+(.*)", stripped)
        if not stripped:
            flush()
        elif heading:
            flush()
            level = len(heading.group(1))
            if level == 1 and not title:
                title = re.sub(r"[`*]", "", heading.group(2))
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
        elif re.fullmatch(r"-{3,}|\*{3,}|_{3,}", stripped):
            flush()
            out.append("<hr>")
        elif "|" in stripped and i + 1 < len(lines) and _is_sep(lines[i + 1]) and len(_cells(stripped)) >= 1:
            flush()
            head, aligns = _cells(stripped), []
            for c in _cells(lines[i + 1]):
                aligns.append("center" if c.startswith(":") and c.endswith(":") else
                              "right" if c.endswith(":") else "left" if c.startswith(":") else "")
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                rows.append(_cells(lines[i]))
                i += 1
            i -= 1

            def cell(tag, text, n):
                style = f' style="text-align:{aligns[n]}"' if n < len(aligns) and aligns[n] else ""
                return f"<{tag}{style}>{inline(text)}</{tag}>"
            out.append("<table><thead><tr>" + "".join(cell("th", c, n) for n, c in enumerate(head))
                       + "</tr></thead><tbody>" + "".join(
                           "<tr>" + "".join(cell("td", c, n) for n, c in enumerate(r)) + "</tr>" for r in rows)
                       + "</tbody></table>")
        elif item:
            flush()
            tag = "ol" if item.group(1)[0].isdigit() else "ul"
            items = []
            while i < len(lines):
                m = re.match(r"\s*([-*]|\d+\.)\s+(.*)", lines[i])
                if m and (("ol" if m.group(1)[0].isdigit() else "ul") == tag) and lines[i].strip():
                    items.append([m.group(2)])
                elif lines[i].strip() and lines[i].startswith((" ", "\t")) and items:
                    items[-1].append(lines[i].strip())  # a wrapped line of the same item
                else:
                    break
                i += 1
            i -= 1
            out.append(f"<{tag}>" + "".join(f"<li>{inline(' '.join(s.strip() for s in it))}</li>" for it in items)
                       + f"</{tag}>")
        else:
            pending_lines.append(line)
        i += 1
    flush()
    return "\n".join(out), title


def sha256(data):
    """sha256 of text bytes with CRLF read as LF, so a checkout with core.autocrlf hashes like the committed file."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def render_page(md_bytes, lang, css=None):
    """The whole self-contained HTML document for the Markdown bytes of one sheet. `css` replaces the built-in
    style. Raises UnicodeDecodeError on a source that is not UTF-8."""
    body, title = convert(md_bytes.decode("utf-8-sig"))
    return (f'<!DOCTYPE html>\n<html lang="{html.escape(lang)}">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{html.escape(title or 'Sheet', quote=False)}</title>\n<style>{CSS if css is None else css}</style>\n"
            f"</head>\n<body>\n<!-- mkt-sheet source-sha256: {sha256(md_bytes)} -->\n{body}\n</body>\n</html>\n")


# --- Config, paths -----------------------------------------------------------------------------------------------

def repo_root():
    # A hook sets GIT_DIR and friends: they would answer the hooked repo, not the one this script lives in.
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    try:
        r = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                           env=env)
    except OSError as exc:
        raise SheetError(f"cannot run git to find the repo root ({exc}); install git and run it inside a checkout "
                         "of the project")
    if r.returncode != 0 or not r.stdout.strip():
        raise SheetError(f"cannot find the repo root from {HERE}: {r.stderr.strip() or 'not a git repo'}; run it "
                         "inside a git checkout of the project")
    return Path(r.stdout.strip())


def sheets(root):
    """(settings dict, list of (source Path, html Path, pdf Path, sha Path, lang)). Raises SheetError."""
    try:
        conf = config.marketing_sheets(config.load(root))
    except config.ConfigError as exc:
        raise SheetError(f"cannot read the config (marketingSheets): {exc}")
    items = []
    for rel in conf["sources"]:
        src = root / rel
        lang = Path(rel).parent.name
        if not lang:
            raise SheetError(f"marketingSheets.sources: {rel} has no language folder; put it in a folder named "
                             "after its language (docs/es/x.md) in .claude/gw.json")
        out = root / conf["outDir"] / lang / Path(rel).stem
        items.append((src, out.with_suffix(".html"), out.with_suffix(".pdf"),
                      out.with_suffix(".pdf.sha"), lang))
    return conf, items


def _need_source(src, root):
    if not src.is_file():
        raise SheetError(f"missing source: {src.relative_to(root).as_posix()} is listed in marketingSheets.sources "
                         "but does not exist; create it or remove it from .claude/gw.json")


def _rel(path, root):
    return path.relative_to(root).as_posix()


CSS_URL = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""")


def stylesheet(root, conf, html_path):
    """The CSS to embed in `html_path`: the configured file with its relative url(...) rewritten to be relative to
    the HTML, or None for the built-in style."""
    if not conf["css"]:
        return None
    css_file = root / conf["css"]
    if not css_file.is_file():
        raise SheetError(f"missing stylesheet: {conf['css']} (marketingSheets.css) does not exist; create it or set "
                         'marketingSheets.css to "" in .claude/gw.json')
    try:
        text = css_file.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SheetError(f"{conf['css']} is not UTF-8 ({exc.reason} at byte {exc.start}); save it as UTF-8")

    def fix(m):
        url = m.group(2).strip()
        if re.match(r"(?i)([a-z][a-z0-9+.-]*:|/|#)", url):
            return m.group(0)
        target = os.path.normpath(os.path.join(os.path.dirname(str(css_file)), url.split("?")[0].split("#")[0]))
        if not os.path.isfile(target):
            raise SheetError(f"missing file in {conf['css']} (marketingSheets.css): url({url}) points to "
                             f"{os.path.relpath(target, str(root))}, which does not exist; restore it or fix the url")
        # The asset's hash goes in the url so that changing a font or an image changes the HTML, and `check`
        # reports both the HTML and the PDF printed from it as stale.
        with open(target, "rb") as fh:
            version = hashlib.sha256(fh.read()).hexdigest()[:12]
        rel = os.path.relpath(target, str(html_path.parent)).replace(os.sep, "/")
        return f'url("{rel}?v={version}")'
    return CSS_URL.sub(fix, text)


def expected_html(root, conf, src, html_path, lang):
    """The HTML that `build` would write for `src`."""
    try:
        return render_page(src.read_bytes(), lang, stylesheet(root, conf, html_path))
    except UnicodeDecodeError as exc:
        raise SheetError(f"{_rel(src, root)} is not UTF-8 ({exc.reason} at byte {exc.start}); save it as UTF-8")


# --- Commands ----------------------------------------------------------------------------------------------------

def cmd_build(root, conf, items):
    for src, html_path, _pdf, _sha, lang in items:
        _need_source(src, root)
        page = expected_html(root, conf, src, html_path, lang)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_bytes(page.encode("utf-8"))
        print(f"built {_rel(html_path, root)}")
    return []


def html_problem(root, conf, src, html_path, lang):
    """Why the HTML of `src` is not usable (None when it is exactly what `build` would write now)."""
    if not html_path.is_file():
        return f"missing {_rel(html_path, root)}; run: {BUILD_CMD}"
    text = html_path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    m = SHA_COMMENT.search(text)
    if not m or m.group(1) != sha256(src.read_bytes()):
        return (f"stale {_rel(html_path, root)}: it was not built from the current "
                f"{_rel(src, root)}; run: {BUILD_CMD}")
    if text != expected_html(root, conf, src, html_path, lang):
        return (f"stale {_rel(html_path, root)}: the stylesheet (marketingSheets.css) or the converter changed since "
                f"it was built; run: {BUILD_CMD}")
    return None


def cmd_check(root, conf, items):
    problems = []
    for src, html_path, pdf, sidecar, lang in items:
        if not src.is_file():
            problems.append(f"missing source {_rel(src, root)} (marketingSheets.sources); create it or remove it "
                            "from .claude/gw.json")
            continue
        try:
            bad = html_problem(root, conf, src, html_path, lang)
        except SheetError as exc:
            bad = str(exc)
        if bad:
            problems.append(bad)
            continue
        if not pdf.is_file():
            problems.append(f"missing {_rel(pdf, root)}; run: {PDF_CMD}")
        elif not sidecar.is_file():
            problems.append(f"missing {_rel(sidecar, root)} (which HTML the PDF was printed from); run: {PDF_CMD}")
        elif sidecar.read_bytes().strip() != sha256(html_path.read_bytes()).encode():
            problems.append(f"stale {_rel(pdf, root)}: it was not printed from the current {_rel(html_path, root)}; "
                            f"run: {PDF_CMD}")
    if not problems:
        print(f"presentation sheets ok ({len(items)} sheet(s))")
    return problems


def count_pages(pdf_bytes):
    """Pages of a PDF: its `/Type /Page` objects, not `/Type /Pages`."""
    return len(re.findall(rb"/Type\s*/Page(?![A-Za-z])", pdf_bytes))


NODE_PRINT = r"""
const path = require('path');
const jobs = JSON.parse(process.argv[1]);
function resolvePlaywright() {
  const bases = [process.cwd()];
  if (process.env.GW_PLAYWRIGHT_DIR) bases.push(path.resolve(process.env.GW_PLAYWRIGHT_DIR));
  for (const base of bases) {
    for (const name of ['playwright', path.join(base, 'playwright')]) {
      try { return require.resolve(name, { paths: [base] }); } catch (e) {}
    }
  }
  return null;
}
(async () => {
  const found = resolvePlaywright();
  if (!found) { console.error('PLAYWRIGHT_NOT_FOUND'); process.exit(3); }
  const { chromium } = require(found);
  const browser = await chromium.launch();
  try {
    for (const [htmlFile, pdfFile] of jobs) {
      const page = await browser.newPage();
      await page.goto(require('url').pathToFileURL(htmlFile).href);
      await page.evaluate(() => document.fonts.ready);
      await page.pdf({ path: pdfFile, preferCSSPageSize: true, printBackground: true });
      await page.close();
    }
  } finally { await browser.close(); }
})().catch((e) => { console.error(String(e && e.stack || e)); process.exit(1); });
"""


def cmd_pdf(root, conf, items):
    problems = []
    for src, html_path, _pdf, _sha, lang in items:
        _need_source(src, root)
        bad = html_problem(root, conf, src, html_path, lang)
        if bad:
            raise SheetError(bad)
    if not items:
        return problems
    node = shutil.which("node")
    if not node:
        raise SheetError("node not found; install Node.js, then: npm i -D playwright && npx playwright install chromium")
    tmp = Path(tempfile.mkdtemp(prefix="mkt-sheet-"))
    try:
        jobs = [[str(h), str(tmp / f"{n}.pdf")] for n, (_s, h, _p, _q, _l) in enumerate(items)]
        try:
            r = subprocess.run([node, "-e", NODE_PRINT, json.dumps(jobs)], cwd=str(root), capture_output=True,
                               text=True, timeout=conf["timeout"])
        except subprocess.TimeoutExpired:
            raise SheetError(f"printing took over {conf['timeout']} s and was stopped; raise marketingSheets.timeout "
                             "in .claude/gw.json or check that Chromium starts (npx playwright install chromium)")
        except OSError as exc:
            raise SheetError(f"cannot run node ({exc}); install Node.js, then: npm i -D playwright && "
                             "npx playwright install chromium")
        if r.returncode == 3 and "PLAYWRIGHT_NOT_FOUND" in r.stderr:
            raise SheetError(MISSING_PLAYWRIGHT)
        if r.returncode != 0:
            raise SheetError("printing with Chromium failed (if the browser is missing: npx playwright install "
                             f"chromium):\n{r.stderr.strip()}")
        for n, (_s, html_path, pdf, sidecar, _l) in enumerate(items):
            data = (tmp / f"{n}.pdf").read_bytes()
            pages = count_pages(data)
            if pages < 1:
                raise SheetError(f"could not count pages in the printed {_rel(pdf, root)}; run: {PDF_CMD} again, "
                                 "and if it repeats update Playwright (npm i -D playwright@latest)")
            if pages > conf["maxPages"]:
                problems.append(f"{_rel(pdf, root)} would have {pages} pages, over maxPages {conf['maxPages']}; "
                                f"shorten {_rel(_s, root)} (or raise marketingSheets.maxPages) and run: "
                                f"{BUILD_CMD} && {PDF_CMD}")
                continue
            pdf.parent.mkdir(parents=True, exist_ok=True)
            pdf.write_bytes(data)
            sidecar.write_text(sha256(html_path.read_bytes()) + "\n", encoding="utf-8")
            print(f"printed {_rel(pdf, root)} ({pages} page(s))")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return problems


COMMANDS = {"build": cmd_build, "pdf": cmd_pdf, "check": cmd_check}


def main(argv=None, root=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in COMMANDS:
        print("usage: python3 scripts/mkt-sheet.py build|pdf|check", file=sys.stderr)
        return 2
    try:
        root = Path(root) if root else repo_root()
        conf, items = sheets(root)
        if not items:
            print("presentation sheets are off: marketingSheets.sources is empty in .claude/gw.json")
            return 0
        problems = COMMANDS[args[0]](root, conf, items)
    except SheetError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    for p in problems:
        print(f"ERROR: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
