"""
gap_analyze.py — compare schemas present vs schemas expected.

Inputs:
    extraction (from extract.py)
    classification (from classify.py: site_type + page_type)
    expectations (loaded from expectations.yaml)

Output:
    {
        "page_type": "...",
        "site_type": "...",
        "present": ["Organization", "WebSite", ...],
        "issues": [                          # incomplete, parse errors
            {"type": "Product", "status": "INCOMPLETE", "missing_properties": ["offers"]},
            ...
        ],
        "missing": [                         # ordered: high then med
            {"type": "BreadcrumbList", "priority": "high", "reason": "..."},
            ...
        ],
    }
"""

from __future__ import annotations

import re
from typing import Any


REASONS = {
    "Organization": "Confirms brand identity in Google's Knowledge Graph and powers the brand sitelinks panel.",
    "WebSite": "Enables sitelinks search box on SERP for branded queries (homepage only).",
    "ItemList": "Eligible for carousel-style rich results on category and homepage listings.",
    "Product": "Eligible for product rich result with price, availability, and rating.",
    "Offer": "Required by Product schema to power price and availability in SERP.",
    "AggregateRating": "Adds star ratings to product/service rich results.",
    "Review": "Adds individual review snippets to rich results.",
    "Brand": "Reinforces product-to-brand association for Knowledge Graph.",
    "BreadcrumbList": "Replaces the URL with a breadcrumb trail in SERP.",
    "FAQPage": "Eligible for FAQ rich result — Q/A pairs shown directly under the snippet.",
    "LocalBusiness": "Powers local pack rich result with address, phone, and hours.",
    "Article": "Eligible for top-stories carousel and article rich result.",
    "BlogPosting": "Eligible for article rich result with date and author.",
    "TechArticle": "Article subtype optimised for technical/docs content.",
    "HowTo": "Eligible for how-to rich result with step-by-step preview.",
    "SoftwareApplication": "Eligible for software-app rich result with rating and price.",
    "AggregateOffer": "Aggregates multiple pricing tiers into a single price-range result.",
    "WebPage": "Generic page typing — improves Google's understanding of page intent.",
    "CollectionPage": "Specific page-type for category/collection listings.",
    "AboutPage": "Specific page-type for the about page.",
}


def _normalize(t: str) -> str:
    """Strip URL prefix from itemtype values like https://schema.org/Product."""
    return t.rsplit("/", 1)[-1] if "/" in t else t


def _present_set(extraction: dict) -> set[str]:
    return {_normalize(t) for t in extraction.get("types_present", [])}


def _walk_jsonld_for_props(blocks: list, target_type: str) -> list[dict]:
    """Find every node with @type == target_type and return them."""
    found: list[dict] = []

    def visit(node: Any):
        if isinstance(node, dict):
            t = node.get("@type")
            types = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
            if target_type in types:
                found.append(node)
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(blocks)
    return found


def _has_property(nodes: list[dict], prop: str) -> bool:
    """Treat nested keys (e.g. 'offers.price') as path lookup."""
    for node in nodes:
        if "." not in prop:
            if node.get(prop) not in (None, "", [], {}):
                return True
        else:
            head, tail = prop.split(".", 1)
            sub = node.get(head)
            if isinstance(sub, dict) and _has_property([sub], tail):
                return True
            if isinstance(sub, list):
                for item in sub:
                    if isinstance(item, dict) and _has_property([item], tail):
                        return True
    return False


def analyze(extraction: dict, classification: dict, expectations: dict) -> dict:
    site = classification["site_type"]
    page = classification["page_type"]
    present = _present_set(extraction)
    blocks = extraction.get("jsonld_blocks", [])
    signals = extraction.get("signals", {})

    # Lookup order:
    # 1. Specific (site_type, page_type) entry, e.g. ecommerce/product
    # 2. cross_cutting/<page_type> if it exists (recipe, podcast, course, webinar, job_posting, service)
    # 3. universal_minimum as final fallback (page_type unknown / page_type == 'other')
    type_rules = expectations.get(site, {}).get(page, {})
    if not type_rules:
        type_rules = expectations.get("cross_cutting", {}).get(page, {})
    if not type_rules:
        type_rules = expectations.get("universal_minimum", {})
    required = type_rules.get("required", [])
    recommended = type_rules.get("recommended", [])

    missing: list[dict] = []
    issues: list[dict] = []

    # 1. Required schemas
    for r in required:
        ttype = r["type"]
        # Treat Offer as nested-of-Product/SoftwareApplication; if those exist with offers, count as present
        if ttype == "Offer":
            parents = _walk_jsonld_for_props(blocks, "Product") + _walk_jsonld_for_props(blocks, "SoftwareApplication")
            offer_present = any(_has_property([p], "offers") for p in parents) or "Offer" in present
            if not offer_present:
                missing.append({"type": "Offer", "priority": "high",
                                "reason": REASONS.get("Offer", "")})
            continue

        if ttype not in present:
            missing.append({"type": ttype, "priority": "high",
                            "reason": REASONS.get(ttype, "")})
        else:
            # Check required properties
            req_props = r.get("properties", []) or []
            nodes = _walk_jsonld_for_props(blocks, ttype)
            missing_props = [p for p in req_props if not _has_property(nodes, p)]
            if missing_props:
                issues.append({
                    "type": ttype,
                    "status": "INCOMPLETE",
                    "missing_properties": missing_props,
                    "priority": "high",
                    "reason": REASONS.get(ttype, ""),
                })

    # 2. Recommended schemas
    for r in recommended:
        ttype = r["type"]
        if ttype not in present:
            missing.append({"type": ttype, "priority": "med",
                            "reason": REASONS.get(ttype, "")})

    # 3. Apply universal overlay rules
    missing = _apply_overlays(missing, page, signals, present)

    # 4. JSON parse errors → issues
    for pe in extraction.get("parse_errors", []):
        issues.append({
            "type": f"<JSON-LD block #{pe['block_index']}>",
            "status": "PARSE_ERROR",
            "missing_properties": [],
            "priority": "high",
            "reason": f"JSON parse error: {pe['error']}",
        })

    # Sort missing: high first, then med, preserving insertion order within each band
    missing.sort(key=lambda m: 0 if m["priority"] == "high" else 1)

    return {
        "page_type": page,
        "site_type": site,
        "present": sorted(present),
        "issues": issues,
        "missing": missing,
    }


def _apply_overlays(missing: list[dict], page: str, signals: dict, present: set[str]) -> list[dict]:
    # Rule: homepage never needs BreadcrumbList
    if page == "homepage":
        missing = [m for m in missing if m["type"] != "BreadcrumbList"]

    # Rule: SearchAction is homepage-only — already enforced via expectations matrix; nothing to strip here

    # Rule: never recommend Carousel
    missing = [m for m in missing if m["type"] != "Carousel"]

    # Rule: FAQ overlay
    if signals.get("has_faq_section") and "FAQPage" not in present and not any(m["type"] == "FAQPage" for m in missing):
        missing.append({
            "type": "FAQPage",
            "priority": "med",
            "reason": REASONS["FAQPage"],
        })

    # Rule: LocalBusiness only if address signal present
    if not signals.get("has_address"):
        missing = [m for m in missing if m["type"] != "LocalBusiness"]

    return missing
