#!/usr/bin/env python3
"""
Scrape 'Rulers' for *Clash Royale: Merge Tactics* from Fandom:

Category hub:
  https://clashroyale.fandom.com/wiki/Category:Rulers

Output (zero-config):
  data/rulers.json  -> {
      "<Ruler Name>": {
        "url": "<page url>",
        "description": "<first meaningful paragraph>",
        "modifier": {
          "name": "<Ruler Modifier name (if found)>",
          "text": "<modifier effect sentence(s)>",
          "chance": <float percent if parsed, else null>
        }
      }, ...
  }

Run:
  python -m scripts.scrapers.scrape_rulers
"""
from __future__ import annotations
import json, os, re, sys, time
from typing import Dict, List, Tuple, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://clashroyale.fandom.com"
CATEGORY = "https://clashroyale.fandom.com/wiki/Category:Rulers"

HEADERS = {
    "User-Agent": "merge-tactics-rulers-scraper/1.0 (+https://github.com/yourname)",
    "Accept-Language": "en-US,en;q=0.9",
}
OUT_PATH = "data/rulers.json"
SLEEP = 0.4  # polite

NUM_RE = re.compile(r"[-+]?\d*[\.,]?\d+(?:[eE][-+]?\d+)?")
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")

def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def fetch(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def makedirs_safe(path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

# ---------- category crawl ----------

def _category_pages(root: str) -> List[str]:
    pages, seen = [], set()
    url = root
    while url and url not in seen:
        seen.add(url)
        pages.append(url)
        soup = fetch(url)
        nxt = soup.select_one("a[rel='next'], a.category-page__pagination-next")
        url = urljoin(BASE, nxt["href"]) if nxt and nxt.get("href") else None
        time.sleep(SLEEP)
    return pages

def collect_ruler_pages() -> List[Tuple[str, str]]:
    """Return list of (name, url) for all rulers under the category (handles pagination)."""
    out, seen = [], set()
    for page in _category_pages(CATEGORY):
        soup = fetch(page)
        for a in soup.select("a.category-page__member-link[href]"):
            href = a["href"]
            # skip subcategories if any
            if "/wiki/Category:" in href:
                continue
            name = norm_space(a.get_text(" "))
            url = urljoin(BASE, href)
            if url not in seen:
                out.append((name, url))
                seen.add(url)
        time.sleep(SLEEP)
    return out

# ---------- page parsing ----------

def first_meaningful_paragraph(soup: BeautifulSoup) -> Optional[str]:
    content = soup.select_one("#mw-content-text")
    if not content:
        return None
    for p in content.select("p"):
        txt = norm_space(p.get_text(" "))
        if txt and not re.match(r"^\s*(This page|The following)\b", txt, re.I):
            return txt
    # fallback: subtitle
    sub = soup.select_one(".page-header__subtitle")
    if sub:
        t = norm_space(sub.get_text(" "))
        if t:
            return t
    return None

def extract_modifier_block(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
    """
    Try to find the Ruler Modifier name and its text.
    Strategies:
      1) Find a section heading containing 'Ruler Modifier' and read following paragraph(s)/list.
      2) Look into infobox rows for 'Ruler Modifier'.
      3) Grep the body for a bold label 'Ruler Modifier' then take next sibling text.
    Returns (modifier_name, modifier_text).
    """
    content = soup.select_one("#mw-content-text")

    # 1) Section heading approach
    for hdr in soup.select("h2, h3"):
        htxt = norm_space(hdr.get_text(" "))
        if re.search(r"ruler\s*modifier", htxt, re.I):
            # next paragraphs or lists up to the next heading
            texts = []
            name = None
            nxt = hdr.find_next_sibling()
            # sometimes the header itself includes the modifier name: "Ruler Modifier: Greener Grin"
            mname = re.search(r"ruler\s*modifier\s*:\s*(.+)", htxt, re.I)
            if mname:
                name = norm_space(mname.group(1))
            while nxt and nxt.name not in ("h2", "h3"):
                if nxt.name in ("p", "ul", "ol"):
                    txt = norm_space(nxt.get_text(" "))
                    if txt:
                        texts.append(txt)
                nxt = nxt.find_next_sibling()
            block = " ".join(texts).strip() if texts else None
            if name or block:
                # if block starts with something like 'Greener Grin – 33% chance ...', split name
                if not name and block:
                    m = re.match(r"^([A-Z][A-Za-z0-9 ':-]{2,40})\s+[–-]\s+(.*)$", block)
                    if m:
                        name, block = norm_space(m.group(1)), norm_space(m.group(2))
                return name, block

    # 2) Infobox row
    infobox = soup.select_one(".portable-infobox, .infobox, table.infobox")
    if infobox:
        for row in infobox.select("tr"):
            th = row.find("th")
            td = row.find("td")
            if th and td and re.search(r"ruler\s*modifier", th.get_text(" "), re.I):
                # try split 'Name – text' pattern
                raw = norm_space(td.get_text(" "))
                m = re.match(r"^([A-Z][\w ':-]+)\s+[–-]\s+(.*)$", raw)
                if m:
                    return norm_space(m.group(1)), norm_space(m.group(2))
                return None, raw

    # 3) Grep for bold label
    if content:
        for b in content.select("b, strong"):
            if re.search(r"ruler\s*modifier", b.get_text(" "), re.I):
                # look at the parent paragraph
                par = b.find_parent("p")
                if par:
                    txt = norm_space(par.get_text(" "))
                    # remove label
                    txt = re.sub(r"(?i)\bruler\s*modifier\s*:?","", txt).strip(" -–—:")
                    # split possible name – description
                    m = re.match(r"^([A-Z][\w ':-]+)\s+[–-]\s+(.*)$", txt)
                    if m:
                        return norm_space(m.group(1)), norm_space(m.group(2))
                    return None, txt

    return None, None

def parse_chance(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    m = PCT_RE.search(text)
    if m:
        try:
            return float(m.group(1))
        except:
            return None
    return None

def parse_ruler_page(name: str, url: str) -> Dict:
    soup = fetch(url)
    desc = first_meaningful_paragraph(soup) or ""
    mod_name, mod_text = extract_modifier_block(soup)
    return {
        "url": url,
        "description": desc,
        "modifier": {
            "name": mod_name,
            "text": mod_text,
            "chance": parse_chance(mod_text),
        },
    }

# ---------- main ----------

def main():
    print("Scanning Rulers category…", file=sys.stderr)
    rulers = collect_ruler_pages()
    print(f"Found {len(rulers)} ruler pages", file=sys.stderr)

    out: Dict[str, Dict] = {}
    for i, (name, url) in enumerate(rulers, 1):
        try:
            data = parse_ruler_page(name, url)
            out[name] = data
            print(f"[{i}/{len(rulers)}] {name}", file=sys.stderr)
        except Exception as e:
            print(f"[WARN] {name} :: {url} :: {e}", file=sys.stderr)
        time.sleep(SLEEP)

    makedirs_safe(OUT_PATH)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(out)} rulers -> {OUT_PATH}")

if __name__ == "__main__":
    main()