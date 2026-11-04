#!/usr/bin/env node
// gw-media-content: turns the sources of a piece's media into the files that get published.
//
//   node render.mjs <piece-folder | date-folder> [source...]
//   node render.mjs --plan <piece-folder | date-folder> [source...]    (print what would be rendered, as JSON)
//
// A piece folder is <dir>/YYYY-MM-DD/NN-<topic>/; a date folder holds several pieces and every one with a
// media/source/ is rendered. Sources live in <piece>/media/source/ (the 0.x folders medios/fuente/ are still
// accepted, with a warning, and then the files go to medios/):
//   *.html, *.svg   rendered with Playwright's Chromium at the size they declare, <meta name="gw-size"
//                   content="1200x675"> (an SVG declares it in a comment: <!-- gw-size: 1200x675 -->; default
//                   1200x675; a gw-size that cannot be read is an error), with the network blocked, to media/<name>.webp (1600 px wide at most), media/<name>-mini.webp (720 px) and
//                   media/<name>.png (the same size as the .webp: LinkedIn takes JPG, PNG and GIF, not WebP)
//   carousel*.html  a document carousel (the old carrusel*.html too, with a warning): each
//                   <section class="slide"> becomes a page of media/<name>.pdf, whose
//                   page size is the gw-size (the render fails if the pages are not the number of slides)
//   *.png, *.jpg    screenshots: converted as they are to media/<name>.webp, <name>-mini.webp and <name>.png
// Without [source...] every source is rendered; with them, only those (file names inside media/source/).
//
// Needs, and fails closed without them:
//   Playwright, resolved from the current folder, then from the folder in the env var GW_PLAYWRIGHT_DIR
//     (install: npm i -D playwright && npx playwright install chromium)
//   ImageMagick with WebP support (`magick`, or `convert` in version 6) for the WebP and PNG files
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readdirSync, readFileSync, realpathSync, rmSync, statSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { basename, extname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const USAGE = 'usage: node render.mjs [--plan] <piece-folder | date-folder> [source...]';
// The first layout is the current one; the second is the 0.x Spanish one, accepted with a warning.
const LAYOUTS = [
  { media: 'media', source: 'source' },
  { media: 'medios', source: 'fuente', old: true },
];
const CAROUSEL_PREFIX = /^(carousel|carrusel)/i;
const PAGES = new Set(['.html', '.svg']);
const SCREENSHOTS = new Set(['.png', '.jpg', '.jpeg']);
const DEFAULT_SIZE = { width: 1200, height: 675 };
const MAX_WIDTH = 1600;
const MINI_WIDTH = 720;
const QUALITY = { '': 82, '-mini': 78 };

class Failure extends Error {}

export function parseArguments(argv) {
  const rest = [];
  let plan = false;
  let help = false;
  for (const a of argv) {
    if (a === '--plan') plan = true;
    else if (a === '--help' || a === '-h') help = true;
    else if (a.startsWith('--')) throw new Failure(`unknown option ${a}. ${USAGE}`);
    else rest.push(a);
  }
  if (help) return { help: true };
  if (!rest.length) throw new Failure(USAGE);
  return { folder: rest[0], requested: rest.slice(1).map((p) => basename(p)), plan };
}

const SIZE_HINT = 'write it as <meta name="gw-size" content="1200x675"> (an SVG: <!-- gw-size: 1200x675 -->)';

function readSize(value) {
  const m = /^\s*(\d+)\s*[x\u00d7]\s*(\d+)\s*$/i.exec(value ?? '');
  if (!m) throw new Failure(`gw-size "${String(value ?? '').trim()}" cannot be read as WIDTHxHEIGHT; ${SIZE_HINT}`);
  const size = { width: Number(m[1]), height: Number(m[2]) };
  if (size.width < 100 || size.height < 100 || size.width > 4000 || size.height > 4000) {
    throw new Failure(`gw-size ${m[1]}x${m[2]} is out of range (100 to 4000 px on each side); fix the size in the source`);
  }
  return size;
}

export function parseSize(text) {
  const withoutComments = text.replace(/<!--[\s\S]*?-->/g, '');
  for (const [tag] of withoutComments.matchAll(/<meta\b[^>]*>/gi)) {
    if (!/\bname\s*=\s*["']?\s*gw-size\b/i.test(tag)) continue;
    const c = /\bcontent\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i.exec(tag);
    return readSize(c ? (c[1] ?? c[2] ?? c[3]) : '');
  }
  const comment = /<!--\s*gw-size\s*:([\s\S]*?)-->/i.exec(text);
  if (comment) return readSize(comment[1]);
  return { ...DEFAULT_SIZE };
}

const isSource = (f) => PAGES.has(extname(f).toLowerCase()) || SCREENSHOTS.has(extname(f).toLowerCase());
const isCarousel = (f) => extname(f).toLowerCase() === '.html' && CAROUSEL_PREFIX.test(basename(f, extname(f)));

export function layoutOf(piece) {
  return LAYOUTS.find((l) => existsSync(join(piece, l.media, l.source))) ?? null;
}

export function piecesOf(folder) {
  const base = resolve(folder);
  if (!existsSync(base) || !statSync(base).isDirectory()) throw new Failure(`${base} is not a folder; pass a piece folder (<dir>/YYYY-MM-DD/NN-<topic>)`);
  if (layoutOf(base)) return [base];
  const children = readdirSync(base, { withFileTypes: true })
    .filter((d) => d.isDirectory() && layoutOf(join(base, d.name)))
    .map((d) => join(base, d.name))
    .sort();
  if (!children.length) throw new Failure(`no media/source/ in ${base} or in any folder below it; the sources of the media go in <piece>/media/source/`);
  return children;
}

export function planOf(piece, requested) {
  const layout = layoutOf(piece);
  if (layout.old) {
    console.error(`render.mjs: warning: ${piece} uses the old folders medios/fuente/; rename them to media/source/ (the files are written to medios/ until then)`);
  }
  const sourceDir = join(piece, layout.media, layout.source);
  const all = readdirSync(sourceDir).filter(isSource).sort();
  const byName = new Map();
  for (const f of all) {
    const name = basename(f, extname(f));
    if (byName.has(name)) throw new Failure(`${byName.get(name)} and ${f} would both give ${layout.media}/${name}.*; rename one of them (${sourceDir})`);
    byName.set(name, f);
  }
  for (const p of requested) if (!all.includes(p)) throw new Failure(`${p} is not a source (.html, .svg, .png, .jpg) in ${sourceDir}`);
  const chosen = requested.length ? all.filter((f) => requested.includes(f)) : all;
  if (!chosen.length) throw new Failure(`no source (.html, .svg, .png or .jpg) in ${sourceDir}`);
  const output = join(piece, layout.media);
  return chosen.map((f) => {
    const name = basename(f, extname(f));
    const path = join(sourceDir, f);
    const screenshot = SCREENSHOTS.has(extname(f).toLowerCase());
    const pdf = isCarousel(f);
    if (pdf && /^carrusel/i.test(name)) console.error(`render.mjs: warning: ${f} starts with "carrusel"; rename it to start with "carousel"`);
    const size = screenshot ? null : parseSize(readFileSync(path, 'utf8'));
    return {
      source: f,
      path,
      name,
      kind: screenshot ? 'screenshot' : pdf ? 'pdf' : 'page',
      size,
      outputs: pdf ? [join(output, `${name}.pdf`)] : [join(output, `${name}.webp`), join(output, `${name}-mini.webp`), join(output, `${name}.png`)],
    };
  });
}

function resolvePlaywright() {
  const bases = [process.cwd()];
  if (process.env.GW_PLAYWRIGHT_DIR) bases.push(resolve(process.env.GW_PLAYWRIGHT_DIR));
  for (const base of bases) {
    const req = createRequire(join(base, 'noop.js'));
    for (const name of ['playwright', join(base, 'playwright')]) {
      try {
        return req.resolve(name);
      } catch {}
    }
  }
  return null;
}

function imagemagick() {
  for (const command of ['magick', 'convert']) {
    try {
      const formats = execFileSync(command, ['-list', 'format'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
      if (/\bWEBP\b/.test(formats)) return command;
    } catch {}
  }
  return null;
}

const MISSING_PLAYWRIGHT =
  'ERROR: Playwright not found (looked from the current folder and from GW_PLAYWRIGHT_DIR). ' +
  'Install it in the project and run again from its folder: npm i -D playwright && npx playwright install chromium';
const MISSING_IMAGEMAGICK =
  'ERROR: ImageMagick with WebP support not found (tried `magick` and `convert`). ' +
  'Install it: apt install imagemagick webp (Debian/Ubuntu) or brew install imagemagick webp (macOS)';

function toImages(im, input, name, outputDir) {
  for (const [suffix, extension] of [['', 'webp'], ['-mini', 'webp'], ['', 'png']]) {
    const target = join(outputDir, `${name}${suffix}.${extension}`);
    const width = suffix ? MINI_WIDTH : MAX_WIDTH;
    const quality = extension === 'webp' ? ['-quality', String(QUALITY[suffix])] : [];
    execFileSync(im, [input, '-auto-orient', '-resize', `${width}x>`, '-strip', ...quality, target]);
    console.log(`${target} (${Math.round(statSync(target).size / 1024)} KB)`);
  }
}

// Runs in the page. Returns the places where the content does not fit: an element that scrolls (non-visible
// overflow with more content than room), or an element or a line of text outside the content box (padding
// excluded) of the body, or of the .slide when the page has slides.
function findOverflows([w, h]) {
  const root = document.documentElement;
  const body = document.body;
  const outside = [];
  const name = (el) => el.tagName.toLowerCase() + (el.id ? `#${el.id}` : '') + (typeof el.className === 'string' && el.className.trim() ? `.${el.className.trim().split(/\s+/).join('.')}` : '');
  const withSlides = !!document.querySelector('section.slide'); // a carousel is taller than one page
  if (root.scrollWidth > w + 1 || (!withSlides && root.scrollHeight > h + 1)) outside.push(`the document scrolls (${root.scrollWidth}x${root.scrollHeight})`);
  if (!body) return outside;
  for (const el of body.querySelectorAll('*')) {
    const e = getComputedStyle(el);
    if (e.overflowX === 'visible' && e.overflowY === 'visible') continue;
    if (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1) {
      outside.push(`${name(el)} has more content than room (${el.scrollWidth}x${el.scrollHeight} in ${el.clientWidth}x${el.clientHeight})`);
    }
  }
  const slides = [...document.querySelectorAll('section.slide')];
  for (const container of slides.length ? slides : [body]) {
    const cs = getComputedStyle(container);
    const r = container.getBoundingClientRect();
    const box = {
      left: r.left + container.clientLeft + parseFloat(cs.paddingLeft),
      top: r.top + container.clientTop + parseFloat(cs.paddingTop),
      right: r.left + container.clientLeft + container.clientWidth - parseFloat(cs.paddingRight),
      bottom: r.top + container.clientTop + container.clientHeight - parseFloat(cs.paddingBottom),
    };
    const total = { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
    // vertical slack: the glyph box of a text with a tight line-height is taller than its line
    const leaves = (c, k, v = 1) => c.left < k.left - 1 || c.top < k.top - v || c.right > k.right + 1 || c.bottom > k.bottom + v;
    // placed on purpose (a page number in the padding): it, and what is inside it, only has to stay inside the container
    const placedIn = (el) => {
      for (let x = el; x && x !== container; x = x.parentElement) {
        const p = getComputedStyle(x).position;
        if (p === 'absolute' || p === 'fixed') return true;
      }
      return false;
    };
    for (const el of container.querySelectorAll('*')) {
      if (['SCRIPT', 'STYLE', 'TEMPLATE', 'NOSCRIPT'].includes(el.tagName)) continue;
      const e = getComputedStyle(el);
      if (e.display === 'none' || e.display === 'contents' || e.visibility === 'hidden') continue;
      const c = el.getBoundingClientRect();
      if (!c.width && !c.height) continue;
      const placed = placedIn(el);
      if (leaves(c, placed ? total : box)) outside.push(`${name(el)} leaves the ${placed ? 'box' : 'content box'} of ${name(container)}`);
    }
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    for (let t = walker.nextNode(); t; t = walker.nextNode()) {
      if (!t.data.trim() || ['SCRIPT', 'STYLE'].includes(t.parentElement?.tagName)) continue;
      const range = document.createRange();
      range.selectNodeContents(t);
      const c = range.getBoundingClientRect();
      const placed = placedIn(t.parentElement);
      const slack = Math.max(1, 0.25 * parseFloat(getComputedStyle(t.parentElement).fontSize));
      if ((c.width || c.height) && leaves(c, placed ? total : box, slack)) outside.push(`text "${t.data.trim().slice(0, 30)}" leaves the content box of ${name(container)}`);
    }
  }
  return [...new Set(outside)];
}

async function preparePage(browser, input, sizeMessage) {
  const context = await browser.newContext({ viewport: input.size, deviceScaleFactor: 1 });
  try {
    // the network is blocked: a source has to be self-contained, and a request that is aborted is a resource that does not load
    await context.route(/^https?:/, (r) => r.abort());
    const page = await context.newPage();
    const errors = [];
    const requests = [];
    page.on('pageerror', (err) => errors.push(String(err?.message ?? err).split('\n')[0]));
    page.on('requestfailed', (p) => {
      const url = p.url();
      if (!url.startsWith('data:')) requests.push(url);
    });
    await page.goto(pathToFileURL(input.path).href, { waitUntil: 'load' });
    const broken = await page.evaluate(async () => {
      await document.fonts.ready;
      const failing = [];
      for (const i of document.images ?? []) {
        try {
          await i.decode();
        } catch {
          failing.push(i.getAttribute('src') || '(empty src)');
        }
      }
      return failing;
    });
    const others = [...new Set(requests)].filter((u) => !broken.some((r) => u.endsWith(r) || decodeURI(u).endsWith(r)));
    if (broken.length || others.length) {
      const parts = [];
      if (broken.length) parts.push(`image(s) that do not load: ${broken.join(', ')}`);
      if (others.length) parts.push(`resource(s) that do not load: ${others.join(', ')}`);
      throw new Failure(`${input.source}: ${parts.join('; ')}; fix the path (relative to the source folder, media/source/); the network is blocked, so everything the source uses has to be a file next to it`);
    }
    if (errors.length) throw new Failure(`${input.source}: the page's script fails: ${errors.join(' | ')}; fix the script in the source`);
    const gaps = await page.evaluate(() => {
      const root = document.body ?? document.documentElement;
      return (root.innerText ?? root.textContent ?? '').includes('{{');
    });
    if (gaps) throw new Failure(`fill the gaps in ${input.source}: it still has text between double braces ({{…}}); replace each one with the real text`);
    const { width, height } = input.size;
    const overflowing = await page.evaluate(findOverflows, [width, height]);
    if (overflowing.length) {
      const list = overflowing.slice(0, 5).join('; ') + (overflowing.length > 5 ? `; and ${overflowing.length - 5} more` : '');
      throw new Failure(`${input.source}: the content overflows ${width}x${height} (${list}); ${sizeMessage}`);
    }
    return { page, context };
  } catch (err) {
    await context.close();
    throw err;
  }
}

function countPdfPages(data) {
  return (data.toString('latin1').match(/\/Type\s*\/Page(?![A-Za-z])/g) ?? []).length;
}

async function run(entries, outputDir) {
  const needsBrowser = entries.some((e) => e.kind !== 'screenshot');
  const needsIm = entries.some((e) => e.kind !== 'pdf');
  let playwrightPath = null;
  if (needsBrowser) {
    playwrightPath = resolvePlaywright();
    if (!playwrightPath) throw new Failure(MISSING_PLAYWRIGHT);
  }
  const im = needsIm ? imagemagick() : null;
  if (needsIm && !im) throw new Failure(MISSING_IMAGEMAGICK);

  const tmp = mkdtempSync(join(tmpdir(), 'gw-media-'));
  let browser;
  let failures = 0;
  try {
    if (needsBrowser) {
      const { chromium } = createRequire(import.meta.url)(playwrightPath);
      try {
        browser = await chromium.launch();
      } catch (err) {
        throw new Failure(`Playwright cannot start Chromium (${String(err.message).split('\n')[0]}); run: npx playwright install chromium`);
      }
    }
    for (const e of entries) {
      let context;
      try {
        if (e.kind === 'screenshot') {
          toImages(im, e.path, e.name, outputDir);
          continue;
        }
        if (e.kind === 'pdf') {
          let page;
          ({ page, context } = await preparePage(browser, e, 'shorten the text of the slide or split it in two'));
          const n = await page.locator('section.slide').count();
          if (!n) throw new Failure(`${e.source}: no <section class="slide"> in the carousel; each slide is one <section class="slide">`);
          const { width, height } = e.size;
          // the page size is the gw-size and nothing else (no preferCSSPageSize: an @page size in the source would override it)
          await page.pdf({
            path: e.outputs[0],
            width: `${width}px`,
            height: `${height}px`,
            printBackground: true,
            margin: { top: '0', right: '0', bottom: '0', left: '0' },
          });
          const pages = countPdfPages(readFileSync(e.outputs[0]));
          if (pages !== n) {
            rmSync(e.outputs[0], { force: true });
            throw new Failure(`${e.source}: the PDF has ${pages} page(s) and the carousel ${n} slide(s); a slide taller than ${height}px or a stray element after the last slide splits the pages: fix the slides in the source`);
          }
          console.log(`${e.outputs[0]} (${n} pages, ${Math.round(statSync(e.outputs[0]).size / 1024)} KB)`);
        } else {
          let page;
          ({ page, context } = await preparePage(browser, e, 'shorten the text or lower the font size'));
          const png = join(tmp, `${e.name}.png`);
          await page.screenshot({ path: png, clip: { x: 0, y: 0, ...e.size } });
          toImages(im, png, e.name, outputDir);
        }
      } catch (err) {
        console.error(err instanceof Failure ? `ERROR: ${err.message.replace(/^ERROR: /, '')}` : `ERROR: ${e.source}: ${err.message}`);
        failures++;
      } finally {
        await context?.close();
      }
    }
  } finally {
    await browser?.close();
    rmSync(tmp, { recursive: true, force: true });
  }
  return failures;
}

async function main() {
  const args = parseArguments(process.argv.slice(2));
  if (args.help) {
    console.log(USAGE);
    return 0;
  }
  const pieces = piecesOf(args.folder).map((p) => ({ piece: p, entries: planOf(p, args.requested) }));
  if (args.plan) {
    console.log(JSON.stringify(pieces.map((p) => ({ piece: p.piece, sources: p.entries.map(({ path, name, ...rest }) => rest) })), null, 2));
    return 0;
  }
  let failures = 0;
  for (const p of pieces) failures += await run(p.entries, join(p.piece, layoutOf(p.piece).media));
  return failures ? 1 : 0;
}

// Run as a program, also through a symlink (npx, a link in node_modules/.bin): both paths are resolved first
function isMain() {
  try {
    return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url));
  } catch {
    return false;
  }
}

if (isMain()) {
  try {
    process.exitCode = await main();
  } catch (err) {
    if (!(err instanceof Failure)) throw err;
    console.error(err.message.startsWith('ERROR') || err.message.startsWith('usage') ? err.message : `ERROR: ${err.message}`);
    process.exitCode = err.message.includes('usage:') ? 2 : 1;
  }
}
