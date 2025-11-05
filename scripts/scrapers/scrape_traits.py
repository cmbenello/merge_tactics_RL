#!/usr/bin/env python3
"""
Scrape 'Cards by Trait' and build:
  - data/traits_index.json : {
        "<Trait>": {
            "description": "<what the trait does (best-effort)>",
            "cards": [ { "name": "...", "url": "..." }, ... ]
        },
        ...
    }
  - data/card_to_traits.json : { "<Card Name>": ["TraitA", "TraitB", ...], ... }

Zero-config usage:
    python -m scripts.scrapers.scrape_traits
"""
from __future__ import annotations
import json, os, re, sys, time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://clashroyale.fandom.com"
CATEGORY_ROOT = "https://clashroyale.fandom.com/wiki/Category:Cards_by_Trait"

HEADERS = {
    "User-Agent": "merge-tactics-traits-scraper/1.1 (+https://github.com/yourname)",
    "Accept-Language": "en-US,en;q=0.9",
}

OUT_TRAITS = "data/traits_index.json"
OUT_CARDMAP = "data/card_to_traits.json"
SLEEP = 0.4  # polite delay between requests (sec)

# ------------------------
# utils
# ------------------------
def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def fetch(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def makedirs_safe(path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

# ------------------------
# crawl helpers
# ------------------------
def collect_trait_category_pages(root_url: str) -> List[str]:
    """Follow pagination of the root category."""
    pages, seen = [], set()
    url = root_url
    while url and url not in seen:
        seen.add(url)
        pages.append(url)
        soup = fetch(url)
        nxt = soup.select_one("a[rel='next'], a.category-page__pagination-next")
        url = urljoin(BASE, nxt["href"]) if nxt and nxt.get("href") else None
    return pages

def collect_trait_subcategories(root_url: str) -> List[Tuple[str,str]]:
    """
    Return list of (raw_name, trait_url). These are subcategory pages like
    /wiki/Category:Trait:_Ace or similar.
    """
    trait_pages: List[Tuple[str,str]] = []
    for page in collect_trait_category_pages(root_url):
        soup = fetch(page)
        for a in soup.select("a.category-page__member-link[href]"):
            href = a["href"]
            title = norm_space(a.get_text(" "))
            # only subcategories (traits), skip direct pages
            if "/wiki/Category:" in href:
                trait_pages.append((title, urljoin(BASE, href)))
        time.sleep(SLEEP)
    # de-dup by URL
    seen, out = set(), []
    for name, url in trait_pages:
        if url not in seen:
            out.append((name, url))
            seen.add(url)
    return out

def normalize_trait_name(name: str) -> str:
    n = norm_space(name)
    n = re.sub(r"(?i)^trait:\s*", "", n)
    n = re.sub(r"(?i)^cards by trait:\s*", "", n)
    n = re.sub(r"(?i)^category:\s*", "", n)
    return n.strip().title()

def extract_cards_from_trait_category(trait_cat_url: str, first_soup: Optional[BeautifulSoup] = None) -> List[Tuple[str,str]]:
    """Extract card pages listed under a trait subcategory (with pagination)."""
    cards: List[Tuple[str,str]] = []
    url, seen = trait_cat_url, set()
    soup = first_soup
    while url and url not in seen:
        seen.add(url)
        if soup is None:
            soup = fetch(url)
        for a in soup.select("a.category-page__member-link[href]"):
            href = a["href"]
            if "/wiki/Category:" in href:
                continue  # nested subcategory; ignore
            name = norm_space(a.get_text(" "))
            cards.append((name, urljoin(BASE, href)))
        nxt = soup.select_one("a[rel='next'], a.category-page__pagination-next")
        url = urljoin(BASE, nxt["href"]) if nxt and nxt.get("href") else None
        soup = None
        time.sleep(SLEEP)
    # de-dup by URL
    out, seen2 = [], set()
    for n,u in cards:
        if u not in seen2:
            out.append((n,u)); seen2.add(u)
    return out

# ------------------------
# trait description extraction
# ------------------------
def _first_meaningful_paragraph(soup: BeautifulSoup) -> str | None:
    content = soup.select_one("#mw-content-text")
    if not content:
        return None
    for p in content.select("p"):
        txt = norm_space(p.get_text(" "))
        if txt and not re.match(r"^\s*(This page|The following)\b", txt, re.I):
            return txt
    # fallback to description box if any
    sub = soup.select_one(".page-header__subtitle, .mw-page-title-namespace")
    if sub:
        txt = norm_space(sub.get_text(" "))
        if txt:
            return txt
    return None

def _maybe_follow_trait_page_from_category(soup_cat: BeautifulSoup) -> str | None:
    """
    Some categories link to a canonical 'Trait: X' content page.
    Try to find a link that looks like a non-category 'Trait:' page.
    """
    for a in soup_cat.select("a[href]"):
        href = a.get("href") or ""
        label = norm_space(a.get_text(" "))
        if re.search(r"/wiki/Trait:", href) and "Category:" not in href:
            return urljoin(BASE, href)
        # sometimes the label itself is 'Trait: X'
        if re.match(r"(?i)trait:\s*\w+", label) and "/wiki/" in href and "Category:" not in href:
            return urljoin(BASE, href)
    return None

def _css_color_to_hex(val: str) -> Optional[str]:
    if not val:
        return None
    m = re.search(r"#([0-9a-fA-F]{6})", val)
    if m:
        return f"#{m.group(1).upper()}"
    m = re.search(r"#([0-9a-fA-F]{3})", val)
    if m:
        c = m.group(1).upper()
        return f"#{c[0]*2}{c[1]*2}{c[2]*2}"
    m = re.search(r"rgba?\(([^)]+)\)", val)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        if len(parts) >= 3:
            try:
                r, g, b = [int(float(parts[i])) for i in range(3)]
                r = max(0, min(255, r))
                g = max(0, min(255, g))
                b = max(0, min(255, b))
                return "#{:02X}{:02X}{:02X}".format(r, g, b)
            except Exception:
                return None
    return None

def _extract_trait_color_from_soup(soup: BeautifulSoup) -> Optional[str]:
    for el in soup.select("[style]"):
        style = el.get("style") or ""
        for prop in ("background-color", "color", "border-color"):
            m = re.search(rf"{prop}\s*:\s*([^;]+)", style, re.I)
            if not m:
                continue
            hexcol = _css_color_to_hex(m.group(1))
            if hexcol:
                return hexcol
    # Try looking for css variables stored in data attributes
    for attr in ("data-color", "data-colour", "data-bgcolor", "data-background"):
        for el in soup.select(f"[{attr}]"):
            hexcol = _css_color_to_hex(el.get(attr, ""))
            if hexcol:
                return hexcol
    return None

def extract_trait_description(trait_url: str, soup_cat: Optional[BeautifulSoup] = None) -> str:
    """
    Best-effort: try the trait category page; if that fails, follow to a 'Trait: X' page;
    return first meaningful paragraph.
    """
    # 1) look on the category page itself
    soup_cat = soup_cat or fetch(trait_url)
    text = _first_meaningful_paragraph(soup_cat)
    if text:
        return text

    # 2) follow to dedicated trait page if linked
    linked = _maybe_follow_trait_page_from_category(soup_cat)
    if linked:
        soup_trait = fetch(linked)
        text2 = _first_meaningful_paragraph(soup_trait)
        if text2:
            return text2

    # 3) fallback: page subtitle or title
    head = soup_cat.select_one("#firstHeading")
    heading = norm_space(head.get_text(" ")) if head else ""
    return f"{heading} (no description found)"

def extract_trait_color(trait_url: str, soup_cat: Optional[BeautifulSoup] = None) -> Optional[str]:
    soup_cat = soup_cat or fetch(trait_url)
    color = _extract_trait_color_from_soup(soup_cat)
    if color:
        return color
    linked = _maybe_follow_trait_page_from_category(soup_cat)
    if linked:
        try:
            soup_trait = fetch(linked)
            color = _extract_trait_color_from_soup(soup_trait)
            if color:
                return color
        except Exception:
            pass
    return None

# ------------------------
# main
# ------------------------
def main():
    print("Scanning Cards by Trait…", file=sys.stderr)
    subcats = collect_trait_subcategories(CATEGORY_ROOT)
    print(f"Found {len(subcats)} trait groups", file=sys.stderr)

    traits_index: Dict[str, Dict] = {}
    card_to_traits: Dict[str, set] = {}

    for i, (raw_trait, url) in enumerate(subcats, 1):
        trait = normalize_trait_name(raw_trait)
        try:
            soup_cat = fetch(url)
            desc = extract_trait_description(url, soup_cat=soup_cat)
            color = extract_trait_color(url, soup_cat=soup_cat)
            cards = extract_cards_from_trait_category(url, first_soup=soup_cat)
            entry = {
                "description": desc,
                "cards": [{"name": n, "url": u} for (n, u) in cards],
            }
            if color:
                entry["color"] = color
            traits_index[trait] = entry
            for (n, _u) in cards:
                card_to_traits.setdefault(n, set()).add(trait)
            print(f"[{i}/{len(subcats)}] {trait}: {len(cards)} cards", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] trait={trait} url={url} :: {e}", file=sys.stderr)
        time.sleep(SLEEP)

    # finalize & write
    card_to_traits_json = {k: sorted(list(v)) for k, v in card_to_traits.items()}
    makedirs_safe(OUT_TRAITS)
    with open(OUT_TRAITS, "w", encoding="utf-8") as f:
        json.dump(traits_index, f, ensure_ascii=False, indent=2)
    with open(OUT_CARDMAP, "w", encoding="utf-8") as f:
        json.dump(card_to_traits_json, f, ensure_ascii=False, indent=2)

    print(f"Wrote traits_index -> {OUT_TRAITS}")
    print(f"Wrote card_to_traits -> {OUT_CARDMAP}")

if __name__ == "__main__":
    main()
