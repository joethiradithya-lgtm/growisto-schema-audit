"""
run.py — main entry point for schema-skill.

Usage:
    python run.py <url>                          # single URL
    python run.py <url1> <url2> <url3>           # batch (space-separated)
    python run.py --file urls.txt                # batch from file (one URL per line)

Output:
    Writes results.json next to this script with a list of per-URL results.
    Each result has: url, page_type, site_type, present, missing, issues, templates.
    'templates' is a dict {SchemaType: rendered_jsonld_string} for every missing/incomplete schema.

This script does NOT touch Google Sheets / Docs directly. Sheet + Doc creation
is performed by Claude Code at runtime using the google-workspace MCP tools,
reading results.json. See SKILL.md "Workflow → Step 4 / Deliverables" for the
exact mapping from results.json to columns A/B/C/D.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

# Local modules
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from extract import extract        # noqa: E402
from classify import classify      # noqa: E402
from gap_analyze import analyze    # noqa: E402
from report import write_report    # noqa: E402


# Map schema @type → template filename
TEMPLATE_MAP = {
    "Organization": "organization.json.j2",
    "WebSite": "website_search.json.j2",
    "Product": "product.json.j2",
    "Offer": "offer.json.j2",
    "ItemList": "item_list.json.j2",
    "BreadcrumbList": "breadcrumb_list.json.j2",
    "Article": "article.json.j2",
    "BlogPosting": "blog_posting.json.j2",
    "TechArticle": "tech_article.json.j2",
    "HowTo": "how_to.json.j2",
    "FAQPage": "faq_page.json.j2",
    "LocalBusiness": "local_business.json.j2",
    "SoftwareApplication": "software_application.json.j2",
    "AggregateOffer": "aggregate_offer.json.j2",
    "AggregateRating": "aggregate_rating.json.j2",
    "Review": "review.json.j2",
    "Brand": "brand.json.j2",
    "WebPage": "web_page.json.j2",
    "CollectionPage": "collection_page.json.j2",
    "AboutPage": "about_page.json.j2",
    "Service": "service.json.j2",
    "Event": "event.json.j2",
    "JobPosting": "job_posting.json.j2",
    "Recipe": "recipe.json.j2",
    "PodcastEpisode": "podcast_episode.json.j2",
    "Course": "course.json.j2",
}


def _slug(url: str) -> str:
    p = urlparse(url)
    s = (p.netloc + p.path).replace("www.", "")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "page"


def _render_template(env: Environment, schema_type: str, scraped: dict) -> str | None:
    fname = TEMPLATE_MAP.get(schema_type)
    if not fname:
        return None
    try:
        tmpl = env.get_template(fname)
        return tmpl.render(scraped=scraped)
    except Exception as e:
        return f"// Could not render template for {schema_type}: {e}"


def audit(url: str, expectations: dict, env: Environment) -> dict:
    extraction = extract(url)

    if extraction.get("extractor_error"):
        return {
            "url": url,
            "error": extraction["extractor_error"],
            "page_type": None,
            "site_type": None,
            "present": [],
            "missing": [],
            "issues": [],
            "templates": {},
        }

    cls = classify(extraction["final_url"], extraction["signals"])
    analysis = analyze(extraction, cls, expectations)

    scraped = extraction.get("scraped", {})
    templates = {}
    # Build a single, ordered list of schemas needing templates: missing + incomplete
    needed_schemas = [m["type"] for m in analysis["missing"]]
    for issue in analysis["issues"]:
        if issue.get("status") == "INCOMPLETE" and issue["type"] not in needed_schemas:
            needed_schemas.append(issue["type"])

    for stype in needed_schemas:
        rendered = _render_template(env, stype, scraped)
        if rendered:
            templates[stype] = rendered

    return {
        "url": extraction["final_url"],
        "input_url": url,
        "page_type": cls["page_type"],
        "site_type": cls["site_type"],
        "present": analysis["present"],
        "missing": analysis["missing"],
        "issues": analysis["issues"],
        "templates": templates,
        "slug": _slug(extraction["final_url"]),
        "scraped_summary": {
            "title": scraped.get("title", ""),
            "headline": scraped.get("headline", ""),
            "description": scraped.get("description", "")[:200],
        },
    }


def parse_args() -> tuple[list[str], Path, Path | None]:
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="*", help="One or more URLs.")
    ap.add_argument("--file", type=Path, help="Path to a .txt or .csv file with one URL per line.")
    ap.add_argument("--out", type=Path, default=HERE / "results.json", help="Output JSON path.")
    ap.add_argument("--xlsx", type=Path, default=None,
                    help="Custom Excel output path (default: schema-audit-<date>.xlsx next to script).")
    args = ap.parse_args()

    urls: list[str] = list(args.urls)
    if args.file:
        for line in args.file.read_text(encoding="utf-8").splitlines():
            line = line.strip().split(",")[0].strip()
            if line and not line.startswith("#"):
                urls.append(line)

    if not urls:
        ap.error("Provide at least one URL or --file.")
    return urls, args.out, args.xlsx


def main() -> int:
    urls, out_path, xlsx_override = parse_args()
    expectations = yaml.safe_load((HERE / "expectations.yaml").read_text(encoding="utf-8"))
    env = Environment(
        loader=FileSystemLoader(str(HERE / "templates")),
        autoescape=select_autoescape(disabled_extensions=("j2",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    results = []
    for i, u in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {u}", file=sys.stderr)
        try:
            results.append(audit(u, expectations, env))
        except Exception as e:
            results.append({
                "url": u,
                "error": f"{type(e).__name__}: {e}",
                "page_type": None, "site_type": None,
                "present": [], "missing": [], "issues": [], "templates": {},
            })

    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out_path} ({len(results)} URL{'s' if len(results) != 1 else ''})", file=sys.stderr)

    xlsx_path = write_report(results, out_path=xlsx_override)
    print(f"Wrote {xlsx_path}", file=sys.stderr)

    # Print a tiny summary to stdout
    for r in results:
        if r.get("error"):
            print(f"ERROR  {r['url']}: {r['error']}")
            continue
        miss = ", ".join(f"{m['type']} [{m['priority']}]" for m in r["missing"]) or "(none)"
        print(f"OK     {r['url']}  type={r['page_type']}  present={len(r['present'])}  missing={miss}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
