"""
classify.py — decide page_type + site_type from URL + extracted signals.

Returns:
    {
        "site_type": "ecommerce" | "saas",
        "page_type": one of
            ecommerce: homepage, product, collection, article, contact, about, search, cart, other
            saas:     homepage, feature, pricing, integrations, case_study, docs, article, contact, about, other
    }
"""

from __future__ import annotations

import re
from urllib.parse import urlparse


ECOM_URL_HINTS = ("/products/", "/product/", "/collections/", "/category/", "/categories/", "/cart", "/checkout")
SAAS_URL_HINTS = ("/pricing", "/features/", "/feature/", "/integrations", "/integration/", "/docs/", "/documentation", "/case-studies/", "/case-study/", "/customers/")


def _is_homepage(parsed) -> bool:
    return parsed.path in ("", "/") and not parsed.query


def _site_type(url: str, signals: dict) -> str:
    u = url.lower()
    if any(h in u for h in ECOM_URL_HINTS):
        return "ecommerce"
    if any(h in u for h in SAAS_URL_HINTS):
        return "saas"
    if signals.get("has_price") and signals.get("og_type", "").startswith("product"):
        return "ecommerce"
    if signals.get("has_pricing_tiers") or signals.get("has_demo_cta"):
        return "saas"
    if signals.get("has_price"):
        return "ecommerce"
    return "saas"  # marketing-site default; safer than ecommerce for unknown B2B


def classify(url: str, signals: dict) -> dict:
    parsed = urlparse(url.lower())
    path = parsed.path
    site = _site_type(url, signals)

    if _is_homepage(parsed):
        return {"site_type": site, "page_type": "homepage"}

    # Cross-cutting page types — apply regardless of site_type.
    # (Specific patterns first; recipe/podcast/course/webinar/jobs/services
    # show up on both ecom and SaaS sites, e.g. an ecom brand running a recipe blog.)
    if "/recipe/" in path or "/recipes/" in path:
        return {"site_type": site, "page_type": "recipe"}
    if "/podcast/" in path or "/episodes/" in path or "/episode/" in path:
        return {"site_type": site, "page_type": "podcast"}
    if "/course/" in path or "/courses/" in path or "/learn/" in path or "/lessons/" in path:
        return {"site_type": site, "page_type": "course"}
    if "/webinar" in path or "/webinars" in path or "/events/" in path or "/event/" in path:
        return {"site_type": site, "page_type": "webinar"}
    if "/careers/" in path or "/jobs/" in path or "/job/" in path or "/openings/" in path or "/positions/" in path:
        return {"site_type": site, "page_type": "job_posting"}
    if "/services/" in path or "/service/" in path:
        return {"site_type": site, "page_type": "service"}

    if site == "ecommerce":
        if "/products/" in path or "/product/" in path:
            return {"site_type": "ecommerce", "page_type": "product"}
        if "/collections/" in path or "/category/" in path or "/categories/" in path:
            return {"site_type": "ecommerce", "page_type": "collection"}
        if "/blog/" in path or "/articles/" in path or "/news/" in path:
            return {"site_type": "ecommerce", "page_type": "article"}
        if "/contact" in path or "/store-locator" in path or "/stores" in path:
            return {"site_type": "ecommerce", "page_type": "contact"}
        if "/about" in path:
            return {"site_type": "ecommerce", "page_type": "about"}
        if "/search" in path:
            return {"site_type": "ecommerce", "page_type": "search"}
        if "/cart" in path or "/checkout" in path:
            return {"site_type": "ecommerce", "page_type": "cart"}
        return {"site_type": "ecommerce", "page_type": "other"}

    # SaaS-only patterns
    if re.search(r"/pricing/?$", path) or "/pricing/" in path or signals.get("has_pricing_tiers"):
        return {"site_type": "saas", "page_type": "pricing"}
    if "/integrations" in path or "/integration/" in path or signals.get("has_integrations_grid"):
        return {"site_type": "saas", "page_type": "integrations"}
    if "/case-stud" in path or "/customer-stor" in path or "/customers/" in path:
        return {"site_type": "saas", "page_type": "case_study"}
    if "/docs" in path or "/documentation" in path or signals.get("has_code_blocks"):
        return {"site_type": "saas", "page_type": "docs"}
    if "/blog/" in path or "/articles/" in path or "/news/" in path or "/post/" in path:
        return {"site_type": "saas", "page_type": "article"}
    if "/contact" in path:
        return {"site_type": "saas", "page_type": "contact"}
    if "/about" in path or "/company" in path:
        return {"site_type": "saas", "page_type": "about"}
    if "/features" in path or "/feature" in path or "/product/" in path or "/solutions" in path:
        return {"site_type": "saas", "page_type": "feature"}
    return {"site_type": "saas", "page_type": "other"}
