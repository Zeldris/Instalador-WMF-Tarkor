# gw-seo references

Each entry says where it comes from and when it was read:
- **read** means the primary source was read on that date (2026-10-30, in the research note of the
  project this skill was born in).
- **via claude-seo** means it comes from claude-seo@6be93f4 (2026-10-22), which cites the source named, and has not
  been re-read here. Re-read it before you rely on it for a decision.

## Indexing

- **One canonical per page**, absolute and self-referencing. `rel=canonical` is a strong signal and the sitemap a
  weak one; don't send different URLs through different methods.
  <https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls> (read 2026-10-30)
- **hreflang:** every version lists itself and all the others, with absolute URLs; if they are not reciprocal "the
  tags will be ignored". Add `x-default` for visitors who match no version. HTML, HTTP header and sitemap are
  equivalent: use only one of them.
  <https://developers.google.com/search/docs/specialty/international/localized-versions> (read 2026-10-30)
- **`lastmod`** is used only "if it's consistently and verifiably" accurate. It reflects the last significant change
  (main content, structured data or links), never the build date. Leave it out when it is unknown. `changefreq` and
  `priority` are ignored.
  <https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap> (read 2026-10-30)
- **There is no ping to Google:** the sitemap ping was retired in June 2023 and now returns 404. Declare the sitemap
  with `Sitemap:` in `robots.txt` and submit it in Search Console.
  <https://developers.google.com/search/blog/2023/06/sitemaps-lastmod-ping> (read through a search result, 2026-10-30)
- **IndexNow** notifies Bing, Yandex, Seznam, Naver, Yep and others, but not Google. A key file `{key}.txt` goes at
  the site root, and you POST up to 10,000 URLs. A 200 response only confirms receipt.
  <https://www.indexnow.org/documentation> (read 2026-10-30)
- **JavaScript sites:** Google renders JavaScript, sometimes with a delay, and "not all bots can run JavaScript". It
  follows only `<a href>` links. Serve real HTML per route, and a real 404 (or `noindex`) for missing pages.
  <https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics> (read 2026-10-30)
- **Googlebot reads only the first 2 MB of an HTML file.** Keep the content and the JSON-LD within that.
  (via claude-seo, `seo-technical`)
- **Title and description lengths:** around 60 and 160 characters are where results usually get cut off. These are
  display limits, not rules, so `check_seo.py` only warns. (via claude-seo, `quality-gates.md`)

## Structured data

Use only types from Google's search gallery, and only for what the page really shows.
<https://developers.google.com/search/docs/appearance/structured-data/search-gallery> (read 2026-10-30)

| Type | Status |
|---|---|
| `Organization` | No required properties. `logo` at least 112×112. `name` matches the site name. Put it on the home page or an "about" page. (read 2026-10-30) |
| `WebSite` (site name) | Must be on the home page of a domain or subdomain: "Google Search does not support site names at the subdirectory level". (read 2026-10-30) |
| `ProfilePage` | For about-me and staff pages. `mainEntity` is a `Person` or `Organization` with a `name`. `dateCreated`, `dateModified`, `sameAs` and `image` are recommended. (read 2026-10-30) |
| `SoftwareApplication` | Needs `offers.price` (0 if free) and `aggregateRating` or `review`. **Without real ratings there is no rich result: never invent them.** `VideoGame` alone shows nothing, so add a second type. (read 2026-10-30) |
| `Article` / `BlogPosting` | No required properties. Only for a post that has its own page. (read 2026-10-30) |
| `FAQPage` | **Retired:** no longer shown since 2026-05-07, and the docs were removed in June 2026. Don't add it. (read 2026-10-30) |
| `HowTo` | Retired in September 2023. (via claude-seo, `deprecated-types-2024-2026.md`) |
| `ClaimReview`, `VehicleListing`, `EstimatedSalary`, `LearningVideo`, Course Info | Retired in June 2025 (<https://developers.google.com/search/blog/2025/06/simplifying-search-results>). Course list (Course + ItemList) is still supported. (via claude-seo) |
| `SpecialAnnouncement` | Retired in July 2025. (via claude-seo) |

`check_seo.py` warns on a retired type (`jsonld-retired-type`). It fails on JSON-LD that does not parse and on
placeholder text (`[Business Name]`, `lorem ipsum`, `TODO`, `example.com`), as claude-seo's schema hook does.

## Link previews

- **Open Graph:** set `og:locale` per language (default `en_US`; the format is `es_ES`), plus `og:locale:alternate`.
  `og:image:width`, `og:image:height` and `og:image:alt` let the image load on the first share. <https://ogp.me/>
  (read 2026-10-30)
- **Facebook** accepts JPEG, GIF or PNG for `og:image:type`, and caches the image by URL ("won't be updated unless
  the URL changes"). <https://developers.facebook.com/docs/sharing/webmasters> (read 2026-10-30)
- **LinkedIn** recommends at least 1200×627 at about 1.91:1, under 5 MB.
  <https://www.linkedin.com/help/linkedin/answer/a521928> (read 2026-10-30)
- **X** `summary_large_image`: 2:1, from 300×157 to 4096×4096, under 5 MB. Source: the X cards documentation as
  cited by claude-seo, with no URL kept: via claude-seo@6be93f4 (2026-10-22), unverified (the page returned 402 when
  read on 2026-10-30, so the figures were only seen in a search result). A 1200×630 JPEG fits Facebook, LinkedIn and X.
- Putting a hash in the image URL (`?v=<hash>`) refreshes the image when it changes. It does not refresh a card that
  was already shared: that needs the manual refresh tools below.

## AI crawlers

This is the user's decision. None of these tokens affects Google Search ranking.

| Token | Owner | What blocking it stops |
|---|---|---|
| `Google-Extended` | Google | Gemini training and grounding. It is not a crawler, and Search inclusion is unaffected. <https://developers.google.com/search/docs/crawling-indexing/google-common-crawlers> (read 2026-10-30) |
| `GPTBot` | OpenAI | Training only. <https://developers.openai.com/api/docs/bots> (read 2026-10-30) |
| `OAI-SearchBot` | OpenAI | Appearing in ChatGPT search. <https://developers.openai.com/api/docs/bots> (read 2026-10-30) |
| `ChatGPT-User` | OpenAI | Fetches a user asked for. OpenAI says `robots.txt` may not apply. <https://developers.openai.com/api/docs/bots> (read 2026-10-30) |
| `ClaudeBot` | Anthropic | Training only. <https://support.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler> (read 2026-10-30) |
| `Claude-SearchBot` | Anthropic | Appearing in Claude's search. <https://support.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler> (read 2026-10-30) |
| `Claude-User` | Anthropic | Fetches a user asked for. All three Anthropic bots honour `robots.txt`. <https://support.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler> (read 2026-10-30) |
| `PerplexityBot` | Perplexity | Perplexity search (via claude-seo) |
| `CCBot` | Common Crawl | Open training dataset (via claude-seo) |
| `Applebot-Extended` | Apple | Apple Intelligence training. It is an opt-out label, not a crawler, and Siri and Spotlight are unaffected. (via claude-seo) |

A common mix is to block the training tokens and allow the search ones. Tell the user what each block stops; never
present a block as an SEO gain.

## llms.txt

Still a proposal (<https://llmstxt.org/>, read 2026-10-30). Google's AI optimization guide says Google Search ignores
such files: they "will neither harm nor help". (via claude-seo, `llmstxt-evidence.md`, citing Google's guide as
updated 2026-07-10.) AI coding agents do read it on developer-docs sites. It costs almost nothing, so keep it if the
project already has one, but never present it as a ranking lever.

## Manual actions

Only the user can do these. List them in the report when they apply.

| When | What | Tool |
|---|---|---|
| A new site, or a sitemap that moved | Submit `sitemap.xml`; read the Pages report | Google Search Console |
| A new or important page | Ask Google to index the URL (daily quota per property; nothing is guaranteed) | Search Console, URL inspection (<https://support.google.com/webmasters/answer/9012289>, read 2026-10-30) |
| Bing and DuckDuckGo | Import the site from Search Console and submit the sitemap | Bing Webmaster Tools |
| A preview's text or image changed after it was shared | Force a new scrape | Facebook Sharing Debugger (<https://developers.facebook.com/tools/debug/>, not re-read; via claude-seo@6be93f4, unverified); LinkedIn Post Inspector (<https://www.linkedin.com/post-inspector/>, not re-read; via claude-seo@6be93f4, unverified); `@WebpageBot` on Telegram and a new `?v=` on the shared URL for Discord and WhatsApp (third-party guides, via claude-seo@6be93f4, unverified, no URL kept) |
