---
name: schema-audit
version: "0.2.0"
description: Audit and generate schema.org markup for one or more URLs. Crawls each page, detects existing JSON-LD / microdata / RDFa, classifies page type, checks against an expectations rulebook (per page type), and produces an Excel report listing schemas present, schemas missing or incomplete with HIGH/MED/LOW priority, and paste-ready JSON-LD code templates for every gap. 26 schema types covered. Use this skill whenever the user asks to audit schema, find missing schema markup, generate schema for a page, check structured data, run a JSON-LD audit, identify rich result opportunities, or get paste-ready schema code. Also trigger when the user provides one or more URLs and mentions schema, structured data, JSON-LD, or rich results.
trigger: "audit schema for"
tags:
  - seo
  - schema
  - structured-data
  - json-ld
category: seo
feedback_path: feedback/
output_format: "Excel (.xlsx) with 4 columns — Page URL, Schemas Present, Schemas Missing/Incomplete (with priority), JSON-LD Templates (paste-ready)"
---

# Schema Audit & Generator

You help the user audit schema.org structured data on one or more pages and produce paste-ready JSON-LD markup for every gap. Works for any kind of site — e-commerce, SaaS, content sites, local business, etc. — by classifying each page type and applying type-specific expectations.

## Inputs you need from the user

1. **One or more URLs** — comma-separated, newline-separated, OR a file path (`.txt` / `.csv` with one URL per line)
2. **Output Excel path** (optional) — where to write the result. **Default: `Outputs/schema-audit-<date>.xlsx`** inside the plugin folder (the `Outputs/` directory exists for this purpose). Only override if the user explicitly asks for a different location.

If only a domain is given (no specific URLs), ask the user which pages they want audited. The plugin works best with a hand-picked list of representative pages (e.g. homepage + 2-3 product pages + 1 category page + 1 article + 1 about page) — not a full site crawl.

## Workflow

### Step 1 — Run the audit

From the plugin root, run:

```bash
python3 scripts/schema_audit/run.py \
  <url1> <url2> ... \
  --out .work/schema_audit_results.json \
  --xlsx "Outputs/<output.xlsx>"
```

OR for a file of URLs:

```bash
python3 scripts/schema_audit/run.py \
  --file <urls.txt> \
  --out .work/schema_audit_results.json \
  --xlsx "Outputs/<output.xlsx>"
```

This will:
- Fetch each URL (fast `requests`-based path first; if Playwright is installed, automatically falls back to it when no JSON-LD is found in the static HTML — JS-rendered SPAs)
- Extract existing schemas (JSON-LD blocks + microdata + RDFa)
- Classify each page (homepage / product / article / pricing / etc.) and site type (ecommerce / saas / content / etc.)
- Apply the expectations rulebook (in `scripts/schema_audit/expectations.yaml`) to determine which schemas the page SHOULD have
- Identify missing schemas with priority (HIGH = required for rich results, MED = recommended, LOW = nice-to-have)
- Detect incomplete schemas (present but missing required properties like `offers` on a Product)
- Render JSON-LD templates for every gap (pre-filled with scraped data — title, headline, price, etc.)
- Write the Excel report

Echo per-URL progress to the user as the script runs (it prints `[1/N] <url>` per URL).

### Step 2 — Report briefly

Once the Excel is written, read the JSON results from `.work/schema_audit_results.json` and tell the user:

- How many URLs were audited
- Aggregate stats: total HIGH-priority gaps across all pages, total INCOMPLETE schemas, any URLs that errored
- For each URL with HIGH-priority gaps: 1 line — `URL: missing [list of types]`
- Path to the Excel

Don't dump full JSON-LD code into the chat — the Excel is for that.

## Output format

Excel with 4 columns:

| Page URL | Schemas Present | Schemas Missing / Incomplete | JSON-LD Template (paste-ready) |
|---|---|---|---|
| https://example.com/p/foo | Product, Offer | AggregateRating [HIGH], Review [MED] | { "@context": "schema.org", "@type": "AggregateRating", ... } ——— { "@type": "Review", ... } |

Multiple schemas in column D are separated by `———` for easy copy-paste.

## Important notes

### Playwright (optional dependency)

For sites that render schema markup via JavaScript (modern React / Next.js / Vue SPAs), `requests` returns no schema blocks. If the user is auditing a JS-heavy site and the results show many "no schemas present" entries that they know aren't right, suggest installing Playwright:

```bash
pip install playwright
playwright install chromium
```

After install, the script automatically uses Playwright as a fallback when the fast path finds no JSON-LD. The first installation is ~300MB (Chromium binary).

For static / SSR sites (most content sites, properly-built e-commerce), the fast path works fine and Playwright is not needed.

### Expectations rulebook

The mapping from page type → required schemas lives in `scripts/schema_audit/expectations.yaml`. It defines per `(site_type, page_type)` which schemas are required (HIGH), recommended (MED), or nice-to-have (LOW). Common combinations:

- `ecommerce/product` → Product (HIGH), Offer (HIGH), BreadcrumbList (HIGH), AggregateRating (MED), Review (MED)
- `ecommerce/collection` → CollectionPage (HIGH), BreadcrumbList (HIGH), ItemList (MED)
- `content/article` → Article (HIGH), BreadcrumbList (HIGH), Organization (HIGH), FAQPage (MED if FAQ section detected)
- `saas/pricing` → SoftwareApplication (HIGH), Offer (HIGH), AggregateRating (MED)

If the user's rule preferences differ (e.g. they always want Review marked HIGH for ecommerce), the YAML can be edited and re-run — no code changes needed.

### Page-type classification

If the classifier gets a page type wrong (e.g. classifies a service page as a product page), the user can tell you and you can re-run the audit treating that URL as the correct type. (Currently a one-off fix; future work could expose a `--page-type` override.)

### No external API calls

This plugin does NOT call Anthropic, OpenAI, Google APIs, or any other service. The "Generator" half uses local Jinja2 templates pre-filled with scraped data (page title, H1, meta description, OG tags, regex-extracted price/phone). All 26 schema types are template-rendered offline.
