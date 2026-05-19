# Growisto Schema Audit — Claude Code Plugin

Audit and generate schema.org markup for any URL. Crawls each page, detects existing JSON-LD / microdata / RDFa, classifies page type, checks against an expectations rulebook, and produces an Excel report listing schemas present, schemas missing or incomplete (with HIGH/MED/LOW priority), and paste-ready JSON-LD code templates for every gap.

This plugin is a Claude Code conversion of the Schema Audit & Generator tool in the [Growisto SEO AI Suite](https://github.com/joethiradithya-lgtm/growisto-seo-ai-suite). The Suite version is mirrored from [yashGrowisto/Schema_audit](https://github.com/yashGrowisto/Schema_audit) — the upstream that Yash maintains.

> **Upstream sync note:** This plugin maintains its own independent copy of the `schema_audit/` package. Once shipped, the plugin diverges from `yashGrowisto/Schema_audit` over time. When Yash ships an upgrade, sync manually by re-copying the relevant files. The skill name (`schema-audit`) is owned by the plugin.

## What it does

Given one or more URLs, the plugin:

1. **Fetches each page** (fast `requests`-based path; optional Playwright fallback for JS-rendered SPAs)
2. **Extracts existing schemas** — JSON-LD blocks (the modern standard), microdata (`itemtype`), and RDFa (`typeof`)
3. **Classifies the page** — site type (ecommerce / saas / content / local / etc.) AND page type (product / article / pricing / homepage / etc.)
4. **Applies the expectations rulebook** — per-page-type required / recommended / nice-to-have schemas
5. **Identifies gaps** — missing schemas with HIGH/MED/LOW priority + incomplete schemas (present but missing required properties)
6. **Renders JSON-LD templates** — Jinja2-pre-filled paste-ready code for every gap, using data scraped from the page (title, H1, meta description, OG tags, price, phone, etc.)
7. **Writes Excel** — 4 columns: URL, Schemas Present, Schemas Missing/Incomplete, Paste-Ready JSON-LD

## Supported schema types (26)

**Commerce:** Product, Offer, AggregateOffer, AggregateRating, Review, Brand, ItemList

**Content / Article:** Article, BlogPosting, TechArticle, HowTo, FAQPage, Recipe, PodcastEpisode

**Organization / Site:** Organization, WebSite (with SearchAction), WebPage, CollectionPage, AboutPage, BreadcrumbList

**Local / Service:** LocalBusiness, Service

**SaaS / Software:** SoftwareApplication

**Other:** Event, JobPosting, Course

## Install

### Option A — From this GitHub repo
```bash
claude plugins install growisto-schema-audit \
  --git https://github.com/joethiradithya-lgtm/growisto-schema-audit
```

### Option B — Org-wide (after pilot phase)
```bash
claude plugins install growisto-schema-audit --marketplace growisto-seo
```

## Use

In Claude Code, just say:
> audit schema for these pages: https://example.com, https://example.com/p/foo, https://example.com/blog/article

…or for a longer list, attach a `.txt` file with one URL per line.

Claude will:
1. Ask which pages you want audited if you only gave a domain
2. Run `python3 scripts/schema_audit/run.py ...`
3. Report aggregate stats + HIGH-priority gaps per URL
4. Hand you the path to the Excel

## Requirements

Python 3.9+ with:
- `requests>=2.31.0`
- `beautifulsoup4>=4.12.0`
- `lxml>=5.0.0`
- `openpyxl>=3.1.0`
- `pyyaml>=6.0`
- `jinja2>=3.1.0`

Install via:
```bash
pip install -r requirements.txt
```

## Optional: Playwright for JS-rendered sites

Sites built with React, Next.js, Vue, or other client-side rendering frameworks often render their schema markup AFTER the initial HTML loads — which means `requests` (a static HTTP client) sees nothing. If you're auditing modern SPAs and the results show many "no schemas present" entries that you know shouldn't be empty, install Playwright:

```bash
pip install playwright
playwright install chromium
```

After install, the script automatically uses Playwright as a fallback when the fast path finds no JSON-LD on a page. The Chromium binary is ~300 MB (one-time download).

For static / SSR sites (most content sites and properly-built e-commerce), the fast path works fine and you don't need Playwright at all.

## CLI usage (without Claude)

```bash
# Single URL
python3 scripts/schema_audit/run.py https://example.com

# Multiple URLs
python3 scripts/schema_audit/run.py \
  https://example.com \
  https://example.com/p/foo \
  https://example.com/blog/post

# From a file of URLs (one per line)
python3 scripts/schema_audit/run.py --file urls.txt

# Custom Excel output path
python3 scripts/schema_audit/run.py https://example.com \
  --xlsx ~/Downloads/example-schema-audit.xlsx

# Custom JSON results path
python3 scripts/schema_audit/run.py https://example.com \
  --out /tmp/results.json \
  --xlsx ~/Downloads/audit.xlsx
```

## The expectations rulebook (tunable)

Schema requirements per page type are defined in [`scripts/schema_audit/expectations.yaml`](scripts/schema_audit/expectations.yaml). If your team has different opinions about what's "required" vs "recommended" for a given page type, edit this YAML — no code changes needed. Run the audit again and the rules update.

Example structure:
```yaml
ecommerce:
  product:
    required: [Product, Offer, BreadcrumbList]
    recommended: [AggregateRating, Review, Brand]
  collection:
    required: [CollectionPage, BreadcrumbList]
    recommended: [ItemList]
content:
  article:
    required: [Article, BreadcrumbList, Organization]
    recommended: [FAQPage]  # only if FAQ section is detected
```

## How it differs from the Render version

| | Render web tool | This plugin |
|---|---|---|
| Trigger | Open URL in browser, paste URLs | "audit schema for X" in Claude |
| Output | Excel download via browser | Excel file written to disk |
| Playwright | Always installed (Render container) | Optional install (lightweight by default) |
| URL list source | Paste / Excel upload | URLs in chat, or `.txt`/`.csv` file |
| Deployment | Render.com | Runs locally on teammate's machine |
| API keys | None | None |

## Related

This is **plugin 5 of 9** being converted from the Growisto SEO AI Suite.

| # | Plugin | Status |
|---|---|---|
| 1 | growisto-keyword-classifier | ✅ shipped |
| 2 | growisto-internal-linking | ✅ shipped |
| 3 | growisto-ai-citation-scraper | ✅ shipped |
| 4 | growisto-blog-content-review | ✅ shipped |
| 5 | growisto-schema-audit | ⬅ this one |
| 6 | growisto-linksift-backlinks | ⏳ |
| 7 | growisto-competitor-analyzer | ⏳ |

(Tech Audit and Page-Level Audit plugins are being built by other Growisto teammates and are not part of this conversion.)

Once all 9 ship, they'll be published to the Growisto org marketplace.
