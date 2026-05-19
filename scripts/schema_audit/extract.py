"""
extract.py — pull every schema block from a URL.

Fast path: requests + BeautifulSoup (no browser, ~5 ms/URL).
Slow path: Playwright/Chromium (only when the fast path finds zero JSON-LD).
          Covers JS-rendered schema (React/Next.js sites that hydrate post-load).

Returns a dict with:
    url
    final_url        (after redirects)
    jsonld_blocks    (list of parsed JSON, one per <script type="application/ld+json">)
    parse_errors     (list of {block_index, error})
    types_present    (sorted list of every distinct @type found, top-level + nested)
    microdata_types  (list of strings from [itemtype])
    rdfa_types       (list of strings from [typeof])
    signals          (dict of HTML signals used by the classifier)
    scraped          (dict of best-effort scraped values for template pre-fill)
    raw_html_excerpt (first 8000 chars of rendered HTML)
    used_playwright  (bool — True when the slow path was triggered)
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


NESTED_KEYS = {
    "@graph", "mainEntity", "mainEntityOfPage", "itemListElement",
    "publisher", "author", "offers", "address", "brand", "review",
    "reviews", "aggregateRating", "hasOfferCatalog", "provider",
    "contactPoint", "department", "subjectOf", "about", "isPartOf",
    "potentialAction", "image",
}

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _walk_types(node: Any, out: list[str]) -> None:
    """Recursively collect every @type value from a parsed JSON-LD object."""
    if isinstance(node, dict):
        t = node.get("@type")
        if isinstance(t, str):
            out.append(t)
        elif isinstance(t, list):
            out.extend([x for x in t if isinstance(x, str)])
        for k, v in node.items():
            if k in NESTED_KEYS or isinstance(v, (dict, list)):
                _walk_types(v, out)
    elif isinstance(node, list):
        for item in node:
            _walk_types(item, out)


def _detect_faq(soup: BeautifulSoup) -> bool:
    if soup.select_one('[itemprop="acceptedAnswer"]'):
        return True
    details = soup.find_all("details")
    if len(details) >= 3 and sum(1 for d in details if d.find("summary")) >= 3:
        return True
    text_lower = soup.get_text(" ", strip=True).lower()
    if "frequently asked questions" in text_lower or text_lower.count("?") >= 4 and "faq" in text_lower:
        return True
    return False


def _detect_pricing_tiers(soup: BeautifulSoup) -> bool:
    text = soup.get_text(" ", strip=True).lower()
    indicators = ["per month", "/month", "per user", "starter", "professional", "enterprise", "free trial", "billed annually"]
    hits = sum(1 for w in indicators if w in text)
    if hits >= 3:
        return True
    cards = soup.select('[class*="pricing"], [class*="tier"], [class*="plan"]')
    return len(cards) >= 2


def _detect_demo_cta(soup: BeautifulSoup) -> bool:
    text = soup.get_text(" ", strip=True).lower()
    return any(p in text for p in ["book a demo", "request a demo", "start free trial", "get a demo", "schedule a demo"])


def _detect_integrations_grid(soup: BeautifulSoup) -> bool:
    if soup.find("section", id=re.compile(r"integrations?", re.I)):
        return True
    if soup.find(class_=re.compile(r"integrations?", re.I)):
        candidates = soup.select('[class*="integration"] img, [class*="integration"] [class*="logo"]')
        return len(candidates) >= 6
    return False


def _detect_breadcrumb(soup: BeautifulSoup) -> bool:
    return bool(
        soup.select_one('[class*="breadcrumb"], nav[aria-label*="breadcrumb" i], ol[itemtype*="BreadcrumbList"]')
    )


def _detect_price_element(soup: BeautifulSoup) -> bool:
    if soup.find(attrs={"itemprop": "price"}):
        return True
    if soup.find(class_=re.compile(r"\bprice\b", re.I)):
        return True
    text = soup.get_text(" ", strip=True)
    return bool(re.search(r"[£$€¥₹]\s?\d", text))


def _scrape_basic(soup: BeautifulSoup, url: str) -> dict:
    out: dict = {"url": url}

    def meta(name=None, prop=None):
        if prop:
            tag = soup.find("meta", property=prop)
        else:
            tag = soup.find("meta", attrs={"name": name})
        return (tag.get("content") or "").strip() if tag and tag.get("content") else ""

    out["title"] = (soup.title.get_text(strip=True) if soup.title else "") or meta(prop="og:title")
    out["description"] = meta(name="description") or meta(prop="og:description")
    out["image"] = meta(prop="og:image")
    h1 = soup.find("h1")
    out["headline"] = h1.get_text(strip=True) if h1 else out["title"]
    out["organization_name"] = meta(prop="og:site_name") or urlparse(url).netloc.replace("www.", "")
    logo = soup.find("link", rel=re.compile(r"icon", re.I))
    out["logo_url"] = (logo.get("href") if logo else "") or out["image"]

    price_match = re.search(r"([£$€¥₹])\s?([\d,]+(?:\.\d{1,2})?)", soup.get_text(" ", strip=True))
    if price_match:
        sym, val = price_match.group(1), price_match.group(2).replace(",", "")
        out["price"] = val
        out["currency"] = {"£": "GBP", "$": "USD", "€": "EUR", "¥": "JPY", "₹": "INR"}.get(sym, "USD")
    else:
        out["price"] = ""
        out["currency"] = ""

    phone_match = re.search(r"\+?\d[\d\s\-().]{7,}\d", soup.get_text(" ", strip=True))
    out["phone"] = phone_match.group(0) if phone_match else ""
    addr_tag = soup.find("address")
    out["address"] = addr_tag.get_text(" ", strip=True) if addr_tag else ""

    pub = soup.find("meta", property="article:published_time") or soup.find("time")
    out["datePublished"] = (pub.get("content") if pub and pub.get("content") else (pub.get("datetime") if pub and pub.get("datetime") else "")) or ""
    auth = soup.find("meta", attrs={"name": "author"}) or soup.find(class_=re.compile(r"author", re.I))
    out["author"] = (auth.get("content") if auth and auth.get("content") else (auth.get_text(strip=True) if auth else ""))

    return out


def _parse_html(html: str, final_url: str) -> dict:
    """Parse an HTML string into a schema result dict. Shared by both fetch paths."""
    result: dict = {
        "final_url": final_url,
        "jsonld_blocks": [],
        "parse_errors": [],
        "types_present": [],
        "microdata_types": [],
        "rdfa_types": [],
        "signals": {},
        "scraped": {},
        "raw_html_excerpt": "",
        "extractor_error": None,
        "used_playwright": False,
    }

    soup = BeautifulSoup(html, "html.parser")
    result["raw_html_excerpt"] = html[:8000]

    types: list[str] = []
    for i, tag in enumerate(soup.find_all("script", type="application/ld+json")):
        raw = (tag.string or tag.get_text() or "").strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            result["parse_errors"].append({"block_index": i, "error": str(e)})
            continue
        result["jsonld_blocks"].append(parsed)
        _walk_types(parsed, types)

    for el in soup.select("[itemtype]"):
        itemtype = el.get("itemtype", "")
        m = re.search(r"/([A-Za-z]+)$", itemtype.strip().rstrip("/"))
        if m:
            result["microdata_types"].append(m.group(1))
            types.append(m.group(1))

    for el in soup.select("[typeof]"):
        for t in el.get("typeof", "").split():
            t = t.split(":")[-1]
            if t:
                result["rdfa_types"].append(t)
                types.append(t)

    result["types_present"] = sorted(set(types))

    og_type_tag = soup.find("meta", property="og:type")
    result["signals"] = {
        "og_type": og_type_tag.get("content", "") if og_type_tag else "",
        "h1_count": len(soup.find_all("h1")),
        "has_price": _detect_price_element(soup),
        "has_breadcrumb_element": _detect_breadcrumb(soup),
        "has_faq_section": _detect_faq(soup),
        "has_pricing_tiers": _detect_pricing_tiers(soup),
        "has_address": bool(soup.find("address")) or "address" in (soup.get_text(" ", strip=True).lower()[:5000]),
        "has_demo_cta": _detect_demo_cta(soup),
        "has_code_blocks": len(soup.find_all("pre")) >= 2 or len(soup.find_all("code")) >= 5,
        "has_integrations_grid": _detect_integrations_grid(soup),
        "card_grid_count": len(soup.select('[class*="grid"] > *, [class*="card"]')),
    }

    result["scraped"] = _scrape_basic(soup, final_url)
    return result


def _fetch_static(url: str, timeout_secs: int = 20) -> tuple[str, str]:
    """Fetch URL with requests; return (html, final_url)."""
    resp = requests.get(
        url,
        timeout=timeout_secs,
        headers={"User-Agent": _DEFAULT_UA},
        allow_redirects=True,
    )
    resp.raise_for_status()
    return resp.text, resp.url


def _extract_with_playwright(url: str, headless: bool, timeout_ms: int) -> tuple[str, str]:
    """Render URL with Playwright; return (html, final_url)."""
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(user_agent=_DEFAULT_UA)
        page = context.new_page()
        page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except PWTimeout:
            pass
        page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        page.wait_for_timeout(1500)
        page.evaluate("window.scrollTo(0, 0);")
        page.wait_for_timeout(2000)
        final_url = page.url
        html = page.content()
        browser.close()

    return html, final_url


def extract(url: str, *, headless: bool = True, timeout_ms: int = 30000) -> dict:
    """
    Extract schema from a URL.

    Tries requests first (fast, no browser).
    Falls back to Playwright only when zero JSON-LD/microdata/RDFa is found
    — covers sites that inject schema client-side via JS frameworks.
    """
    # Fast path
    try:
        html, final_url = _fetch_static(url, timeout_secs=min(timeout_ms // 1000, 20))
        result = _parse_html(html, final_url)
        result["url"] = url
        if result["types_present"]:
            return result
    except Exception:
        pass

    # Slow path: Playwright
    base: dict = {
        "url": url,
        "final_url": url,
        "jsonld_blocks": [],
        "parse_errors": [],
        "types_present": [],
        "microdata_types": [],
        "rdfa_types": [],
        "signals": {},
        "scraped": {},
        "raw_html_excerpt": "",
        "extractor_error": None,
        "used_playwright": False,
    }
    try:
        html, final_url = _extract_with_playwright(url, headless, timeout_ms)
    except Exception as e:
        base["extractor_error"] = f"{type(e).__name__}: {e}"
        return base

    result = _parse_html(html, final_url)
    result["url"] = url
    result["used_playwright"] = True
    return result


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "https://gayatristore.co.uk/"
    out = extract(target)
    print(json.dumps({k: v for k, v in out.items() if k != "raw_html_excerpt"}, indent=2, default=str)[:4000])
