#!/usr/bin/env python3
"""
Scrape unit/card stats for *Clash Royale: Merge Tactics* from the Fandom wiki.

Entrypoints we use:
- Hub page: https://clashroyale.fandom.com/wiki/Merge_Tactics
- Unit pages typically like: https://clashroyale.fandom.com/wiki/Archers/Merge_Tactics

Output:
- JSON file with one object per unit containing normalized core fields
  (we collect extra fields if present, but you can ignore them at import time).

Usage:
  python -m scripts.scrape_merge_tactics --out data/merge_tactics_units.json --limit 0
"""
from __future__ import annotations
import argparse, json, re, time, sys, os
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

BASE = "https://clashroyale.fandom.com"
HUB  = "https://clashroyale.fandom.com/wiki/Merge_Tactics"

HEADERS = {
    "User-Agent": "merge-tactics-scraper/1.0 (github.com/yourname) requests",
    "Accept-Language": "en-US,en;q=0.9",
}

# Map many possible wiki labels -> our canonical keys
LABEL_MAP = {
    # costs / economy
    "elixir": "elixir",
    "cost": "elixir",

    # combat basics
    "hitpoints": "hp",
    "hit points": "hp",
    "health": "hp",
    "hp": "hp",
    "damage": "damage",
    "dps": "dps",
    "range": "range",
    "hit speed": "hit_speed",
    "hitspeed": "hit_speed",
    "reload": "hit_speed",
    "projectile speed": "projectile_speed",
    "move speed": "move_speed",
    "movement speed": "move_speed",
    "speed": "move_speed",

    # meta
    "type": "type",
    "rarity": "rarity",
    "targets": "targets",
    "target": "targets",
    "count": "count",
}

# Try to parse numbers like "1.1 sec", "1,200", "2 tiles", "x1.4"
NUM_RE = re.compile(r"[-+]?\d*[\.,]?\d+(?:[eE][-+]?\d+)?")
SEC_RE = re.compile(r"\b(s|sec|secs|second|seconds)\b", re.I)
TILE_RE = re.compile(r"\b(tile|tiles|range)\b", re.I)

def norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def lower(s: str) -> str:
    return (s or "").strip().lower()

def parse_num(raw: str):
    if raw is None:
        return None
    txt = norm_space(raw)
    m = NUM_RE.search(txt.replace(",", ""))
    if not m:
        return None
    val = float(m.group(0))
    # normalize units: seconds -> seconds, tiles -> tiles
    if SEC_RE.search(txt):
        return {"value": val, "unit": "s"}
    if TILE_RE.search(txt) or "tile" in txt or "range" in txt:
        return {"value": val, "unit": "tiles"}
    return val

def fetch(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def is_unit_link(href: str) -> bool:
    # We want pages ending with /Merge_Tactics (e.g., /Archers/Merge_Tactics)
    return bool(href and href.startswith("/wiki/") and href.endswith("/Merge_Tactics"))

def collect_unit_links(hub_soup: BeautifulSoup) -> list[str]:
    links = set()
    for a in hub_soup.select("a[href]"):
        href = a["href"]
        if is_unit_link(href):
            links.add(urljoin(BASE, href))
    return sorted(links)

def parse_infobox(soup: BeautifulSoup) -> dict:
    """
    Parse stats from the side infobox if present.
    Fandom infobox markup varies; we try a few selectors and key/value patterns.
    """
    data = {}
    # common infobox containers
    infobox = soup.select_one(".portable-infobox, .infobox, table.infobox")
    if not infobox:
        return data

    # Key/Value in li rows or table rows
    for row in infobox.select("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) >= 2:
            key = norm_space(cells[0].get_text(" "))
            val = norm_space(cells[1].get_text(" "))
            assign_kv(data, key, val)

    for li in infobox.select("li"):
        # often looks like: <li><b>Elixir</b> 3</li>
        b = li.find("b")
        if b:
            key = norm_space(b.get_text(" "))
            val = norm_space(li.get_text(" ").replace(key, "", 1))
            assign_kv(data, key, val)

    return data

def parse_stat_tables(soup: BeautifulSoup) -> dict:
    """
    Some pages put base stats in a wikitable (e.g., HP, Damage, Hit Speed).
    We scan for likely stat tables and fold first-row or 'Level 1' row values.
    """
    data = {}
    tables = soup.select("table.wikitable, table.article-table")
    for tbl in tables:
        headers = [lower(norm_space(th.get_text(" "))) for th in tbl.select("tr th")]
        if not headers:
            continue
        # detect a stats table if any header matches known stat labels
        if not any(any(k in h for k in LABEL_MAP.keys()) for h in headers):
            continue

        # read first data row or the row containing "1" / "lvl 1"
        rows = tbl.select("tr")
        candidates = rows[1:]  # skip header
        best = None
        for tr in candidates:
            tds = [norm_space(td.get_text(" ")) for td in tr.find_all("td")]
            if not tds:
                continue
            rowtxt = " ".join(tds).lower()
            if "level 1" in rowtxt or rowtxt.startswith("1 ") or rowtxt == "1":
                best = tds
                break
        if best is None and candidates:
            best = [norm_space(td.get_text(" ")) for td in candidates[0].find_all("td")]

        if best:
            # map headers -> values
            for h, v in zip(headers, best):
                assign_kv(data, h, v)

    return data

def assign_kv(store: dict, raw_key: str, raw_val: str):
    k = lower(raw_key)
    vtxt = norm_space(raw_val)

    # unify key
    key = None
    for label, canon in LABEL_MAP.items():
        if label in k:
            key = canon
            break

    # Always store the human string too (for debugging)
    if key is None:
        # unknown key: store under extras
        store.setdefault("extras", {})[raw_key.strip()] = vtxt
        return

    # parse numbers when appropriate
    if key in {"hp", "damage", "dps", "hit_speed", "range", "projectile_speed", "move_speed", "elixir", "count"}:
        store[key] = parse_num(vtxt)
    else:
        store[key] = vtxt

# --- Added: helpers for removed notice and star-table parsing ---
STAR_RE = re.compile(r"★+")

def detect_removed_notice(soup: BeautifulSoup) -> dict:
    """Detect pages that say 'replaced or removed from the game' and return a status field."""
    node = soup.find(string=re.compile(r"replaced or removed from the game", re.I))
    status = {}
    if node:
        parent = node.find_parent(["p", "div"]) or node
        status = {
            "status": "removed",
            "historical_notice": norm_space(parent.get_text(" ") if hasattr(parent, 'get_text') else str(parent))
        }
    return status

def header_to_star_and_stat(h: str):
    """Map a header like 'Hitpoints (★★★)' / 'Damage per second (★)' to (star, stat_key)."""
    h0 = lower(h)
    star = None
    m = STAR_RE.search(h)
    if m:
        star = len(m.group(0))
    if "hitpoints" in h0 or "hitpoint" in h0 or h0.strip() == "hp":
        key = "hp"
    elif "damage per second" in h0 or h0.strip() == "dps":
        key = "dps"
    elif "area damage" in h0:
        key = "area_damage"
    elif h0.strip() == "damage" or "damage" in h0:
        key = "damage"
    elif "hit speed" in h0 or "hitspeed" in h0 or "damage speed" in h0:
        key = "hit_speed"
    elif h0.startswith("level"):
        key = "level"
    else:
        key = None
    return star, key

def parse_star_tables(soup: BeautifulSoup) -> list:
    """Build per-level entries with star buckets {"1":{...},"2":{...},...}."""
    out_levels = {}
    tables = soup.select("table.wikitable, table.article-table")
    for tbl in tables:
        headers = [norm_space(th.get_text(" ")) for th in tbl.select("tr th")]
        if not headers:
            continue
        if not any("level" in lower(h) for h in headers):
            continue
        if not any("★" in h for h in headers):
            continue
        colmap = [header_to_star_and_stat(h) for h in headers]
        for tr in tbl.select("tr")[1:]:
            tds = tr.find_all(["td","th"])
            if not tds:
                continue
            values = [norm_space(td.get_text(" ")) for td in tds]
            if len(values) != len(headers):
                continue
            # locate level column
            lvl_idx = None
            for ci, (st, key) in enumerate(colmap):
                if key == "level":
                    lvl_idx = ci
                    break
            if lvl_idx is None:
                continue
            m = re.search(r"\d+", values[lvl_idx])
            if not m:
                continue
            lvl = int(m.group(0))
            entry = out_levels.setdefault(lvl, {"level": lvl, "stars": {}})
            for ci, (st, key) in enumerate(colmap):
                if ci == lvl_idx or key is None or st is None:
                    continue
                bucket = entry["stars"].setdefault(str(st), {})
                bucket[key] = parse_num(values[ci])
    return [out_levels[k] for k in sorted(out_levels.keys())]

def _split_traits(raw: str) -> list[str]:
    """
    Split a raw trait string like 'Ace and Avenger' or 'Ace, Avenger and Support'
    into ['Ace','Avenger','Support'] with whitespace trimmed and title-cased.
    We also remove emoji/icons and stray punctuation that may appear in the
    wiki text (e.g., trait icons in front of the names).
    """
    if not raw:
        return []
    # normalize separators to comma
    tmp = re.sub(r"\s*(?:and|&|/|\+|\|)\s*", ",", raw, flags=re.I)
    # drop most non-letter characters (keeps spaces and hyphens)
    tmp = re.sub(r"[^A-Za-z0-9,\- ]+", "", tmp)
    parts = [p.strip(" .") for p in tmp.split(",") if p.strip(" .")]
    return [p.strip().title() for p in parts]


def parse_traits(soup: BeautifulSoup) -> dict:
    """
    Detect 'traits/groups' from early article text. Handles variants like
    'belongs in/to the X and Y traits', optional icons, and link markup.
    We scan the first few non-empty <p> blocks in the lead.
    """
    content = soup.select_one("#mw-content-text")
    if not content:
        return {}

    # Gather the first few non-empty paragraphs' text (string-joined) and the tag nodes
    paras = []
    for p in content.select(".mw-parser-output > p, p"):
        t = " ".join(list(p.stripped_strings))
        if t:
            paras.append((p, norm_space(t)))
        if len(paras) >= 4:
            break
    if not paras:
        return {}

    # Regex candidates. We aim to capture the span before the word 'traits'.
    pats = [
        r"\bbelongs\s+in\s+the\s+(?P<traits>.+?)\s+traits?\b",
        r"\bbelongs\s+to\s+the\s+(?P<traits>.+?)\s+traits?\b",
        r"\bis\s+classified\s+under\s+the\s+(?P<traits>.+?)\s+traits?\b",
        r"\bis\s+part\s+of\s+the\s+(?P<traits>.+?)\s+traits?\b",
        r"\bwith\s+the\s+(?P<traits>.+?)\s+traits?\b",
        r"\bthe\s+(?P<traits>[^.]+?)\s+traits?\b",  # generic fallback
    ]

    # 1) Try text-based extraction first
    for _p, txt in paras:
        for pat in pats:
            m = re.search(pat, txt, flags=re.I)
            if m:
                traits = _split_traits(m.group("traits"))
                if traits:
                    return {"traits": traits}

    # 2) Anchor-based heuristic: in a paragraph mentioning 'traits', collect
    #    nearby anchor texts that look like Proper Nouns (the trait names)
    for p, txt in paras:
        if "traits" not in txt.lower():
            continue
        candidates = []
        for a in p.select("a"):
            at = norm_space(a.get_text(" "))
            # skip generic words/links
            if not at or at.lower() in {"card", "traits", "the"}:
                continue
            # proper-ish noun / short phrase is likely a trait label
            if re.match(r"^[A-Z][A-Za-z\- ]{0,24}$", at):
                candidates.append(at)
        if candidates:
            return {"traits": [c.strip().title() for c in candidates]}

    return {}

def parse_unit_page(url: str) -> dict:
    soup = fetch(url)
    title = norm_space(soup.select_one("#firstHeading").get_text(" ")) if soup.select_one("#firstHeading") else url
    data = {"name": title, "url": url}
    # include removed/legacy status if present
    data.update(detect_removed_notice(soup))
    # infobox + base/stat tables (level-1 style)
    data.update(parse_infobox(soup))
    data.update(parse_stat_tables(soup))
    traits_info = parse_traits(soup)
    if traits_info:
        data.update(traits_info)
    # full per-level star tables
    per_level = parse_star_tables(soup)
    if per_level:
        data["per_level"] = per_level
    # simple type heuristic if missing
    if "type" not in data:
        body = soup.select_one("#mw-content-text")
        txt = lower(body.get_text(" ")) if body else ""
        if "ranged" in txt:
            data["type"] = "Ranged"
        elif "melee" in txt:
            data["type"] = "Melee"
    return data

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/merge_tactics_units.json", help="output JSON path")
    ap.add_argument("--sleep", type=float, default=0.8, help="polite delay between requests (sec)")
    ap.add_argument("--limit", type=int, default=0, help="limit number of unit pages (0 = no limit)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    # Collect unit links from hub
    hub = fetch(HUB)
    links = collect_unit_links(hub)
    if args.limit > 0:
        links = links[:args.limit]

    out = []
    for i, url in enumerate(links, 1):
        try:
            data = parse_unit_page(url)
            out.append(data)
            if args.verbose:
                print(f"[{i}/{len(links)}] {data.get('name')}  ->  {url}")
        except Exception as e:
            print(f"[WARN] failed: {url} :: {e}", file=sys.stderr)
        time.sleep(max(0.0, args.sleep))

    # Write JSON
    os.makedirs_safe(args.out)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(out)} units -> {args.out}")

# small helper to create parent dirs
class os:
    @staticmethod
    def makedirs_safe(path: str):
        import os as _os
        _os.makedirs(_os.path.dirname(path) or ".", exist_ok=True)

if __name__ == "__main__":
    main()