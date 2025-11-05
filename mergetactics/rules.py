from dataclasses import dataclass
from typing import Dict, Any, Tuple, Optional, List
import json, os, re

# =========================
# Catalog loading (cards scraped from wiki)
# =========================
# Default location can be overridden with env var MT_CATALOG
_DEF_CATALOG_REL = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                'data', 'merge_tactics_units.json')
_TRAITS_INDEX_REL = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                 'data', 'traits_index.json')

CATALOG_PATH = os.environ.get('MT_CATALOG', _DEF_CATALOG_REL)
TRAITS_INDEX_PATH = os.environ.get('MT_TRAITS_INDEX', _TRAITS_INDEX_REL)

# Debug flag for catalog loading diagnostics
_DEBUG_RULES_LOAD = True  # set False to silence catalog load diagnostics

def _load_catalog(path: str) -> List[Dict[str, Any]]:
    if _DEBUG_RULES_LOAD:
        print(f"[MT RULES] loading catalog from: {path}")
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                if _DEBUG_RULES_LOAD:
                    try:
                        print(f"[MT RULES] catalog entries: {len(data)}")
                        # Try to locate a few known cards by name
                        wanted = {"Baby Dragon", "Bandit", "Wizard"}
                        found = [d for d in data if isinstance(d, dict) and d.get("name") in wanted]
                        for d in found:
                            nm = d.get("name")
                            rg = d.get("range")
                            hs = d.get("hit_speed")
                            ps = d.get("projectile_speed")
                            print(f"[MT RULES] sample {nm}: range={rg} hit_speed={hs} proj_speed={ps}")
                    except Exception as _e:
                        print(f"[MT RULES] debug sample failed: {_e}")
                return data
    except Exception:
        pass
    # Minimal fallback so the app still runs if the JSON is missing
    return [
        {"name": "Tank", "hp": 180, "dps": 18, "range": 1, "hit_speed": 1.0,
         "move_speed": 1.0, "projectile_speed": 0.0, "traits": ["Vanguard"]},
        {"name": "Archer", "hp": 90, "dps": 24, "range": 3, "hit_speed": 1.0,
         "move_speed": 0.5, "projectile_speed": 4.0, "traits": ["Ranger"]},
    ]

def _has_stats(card: Dict[str, Any]) -> bool:
    per_level = card.get("per_level")
    if isinstance(per_level, list) and per_level:
        for row in per_level:
            if not isinstance(row, dict):
                continue
            stars = row.get("stars")
            if not isinstance(stars, dict):
                continue
            for data in stars.values():
                if isinstance(data, dict) and any(k in data for k in ("hp", "damage", "dps")):
                    return True
    hp = card.get("hp")
    dmg = card.get("damage")
    dps = card.get("dps")
    hs = card.get("hit_speed")
    return (hp is not None) and ((dps is not None) or (dmg is not None and hs is not None))

def _filter_catalog(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned = []
    dropped = []
    for card in data:
        if _has_stats(card):
            cleaned.append(card)
        else:
            dropped.append(card.get("name", "?"))
    if _DEBUG_RULES_LOAD and dropped:
        print(f"[MT RULES] dropping {len(dropped)} cards without stats:", dropped)
    return cleaned


CARD_CATALOG: List[Dict[str, Any]] = _filter_catalog(_load_catalog(CATALOG_PATH))

if _DEBUG_RULES_LOAD:
    try:
        print("[MT RULES] first 10 names:", [d.get("name") for d in CARD_CATALOG[:10]])
    except Exception:
        pass

# Public id space = indices into CARD_CATALOG
TROOP_IDS: List[int] = list(range(len(CARD_CATALOG)))
TROOP_NAMES: Dict[int, str] = {i: CARD_CATALOG[i].get('name', f'ID{i}') for i in TROOP_IDS}
CARD_TRAITS: Dict[int, List[str]] = {i: CARD_CATALOG[i].get('traits', []) for i in TROOP_IDS}

def card_by_id(tid: int) -> Dict[str, Any]:
    return CARD_CATALOG[tid]

def _normalize_hex_color(color: str) -> Optional[str]:
    if not color:
        return None
    color = color.strip()
    m = re.match(r"#([0-9a-fA-F]{6})$", color)
    if m:
        return f"#{m.group(1).upper()}"
    m = re.match(r"#([0-9a-fA-F]{3})$", color)
    if m:
        c = m.group(1).upper()
        return f"#{c[0]*2}{c[1]*2}{c[2]*2}"
    m = re.match(r"rgba?\(([^)]+)\)$", color)
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

def _hex_to_rgb(color: str) -> Optional[tuple[int, int, int]]:
    color = _normalize_hex_color(color)
    if not color:
        return None
    try:
        return tuple(int(color[i:i+2], 16) for i in (1, 3, 5))
    except Exception:
        return None

def _load_trait_colors(path: str) -> Dict[str, tuple[int,int,int]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        colors = {}
        for trait, info in data.items():
            col = info.get("color")
            rgb = _hex_to_rgb(col) if isinstance(info, dict) else None
            if rgb:
                def _register(name: str):
                    if not name:
                        return
                    name_norm = re.sub(r"\s+", " ", name.strip())
                    if not name_norm:
                        return
                    colors[name_norm] = rgb
                _register(trait)
                base = re.sub(r"(?i)cards$", "", trait or "").strip()
                base = re.sub(r"(?i)^trait:", "", base).strip()
                base = re.sub(r"\s+", " ", base)
                if base and base.lower() != (trait or "").lower():
                    _register(base)
                # also add title-case version without "Cards"
                short = re.sub(r"(?i)cards$", "", base).strip()
                if short:
                    _register(short)
                # lower-case key for loose lookups
                if trait:
                    colors.setdefault(trait.lower(), rgb)
                if base:
                    colors.setdefault(base.lower(), rgb)

        if _DEBUG_RULES_LOAD and colors:
            sample = dict(list(colors.items())[:5])
            print(f"[MT RULES] loaded trait colors (sample): {sample}")
        return colors
    except FileNotFoundError:
        if _DEBUG_RULES_LOAD:
            print(f"[MT RULES] trait color index not found at {path}")
    except Exception as e:
        if _DEBUG_RULES_LOAD:
            print(f"[MT RULES] trait color load failed: {e}")
    return {}

_DEFAULT_TRAIT_COLORS: Dict[str, tuple[int,int,int]] = {
    'Undead': (120, 240, 160),
    'Ranger': (130, 170, 255),
    'Goblin': (110, 210, 110),
    'Royal': (245, 210, 90),
    'Avenger': (250, 120, 160),
}
TRAIT_COLORS: Dict[str, tuple[int,int,int]] = {
    **_DEFAULT_TRAIT_COLORS,
    **_load_trait_colors(TRAITS_INDEX_PATH)
}

# =========================
# Board & round structure
# =========================
BOARD_ROWS = 8
BOARD_COLS = 5
MAX_ROUNDS = 20

# =========================
# Economy / store / bench
# =========================
START_ELIXIR = 4           # per-round income
CARD_COST_DEFAULT = 3      # fallback if a card has no explicit cost
SELL_REFUND = 2

# We no longer count "actions" explicitly; env will auto-end when a player can no longer buy/merge/place.
ACTIONS_PER_DEPLOY = 1     # kept for compatibility with UI

STORE_SLOTS = 3
BENCH_CAP = 5

def unit_cap_for_round(round_num: int) -> int:
    """Starts at 2 in round 1 and grows by +1 per round until capped at 6."""
    return min(2 + (round_num - 1), 6)

# =========================
# Battle tuning
# =========================
USE_PROJECTILES = True

# Default per-card fallbacks (only used when the catalog lacks a value):
DEFAULT_RANGE = 1
DEFAULT_HIT_SPEED = 1.0          # seconds between attacks
DEFAULT_MOVE_SPEED = 1.0         # cells per second

USE_PROJECTILES = True
DEFAULT_PROJECTILE_SPEED = 6.0  # tiles per second fallback for ranged units without explicit speed
DEBUG_RANGED = True             # set False to silence classification logs

# Physics integration
SUB_TICK_DT = 0.1
MAX_BATTLE_TIME = 30.0           # used only if END_ONLY_ON_WIPE is False
END_ONLY_ON_WIPE = True
ABSOLUTE_BATTLE_TIME_CAP = 300.0

# =========================
# Star scaling (global defaults)
# =========================
STAR_HP_MUL_DEFAULT = [1.0, 1.0, 1.6, 2.56]   # index by star 0..3 (star 1..3 valid)
STAR_DPS_MUL_DEFAULT = [1.0, 1.0, 1.4, 1.96]

# =========================
# Helper utilities for catalog-driven stats
# =========================

def _num(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, dict) and "value" in x:
        try:
            return float(x["value"])
        except Exception:
            return None
    try:
        return float(str(x).replace(",", ""))
    except Exception:
        return None


def _get_star_multiplier(card: Dict[str, Any], stat: str, star: int) -> float:
    lut = STAR_HP_MUL_DEFAULT if stat == "hp" else STAR_DPS_MUL_DEFAULT
    if star < 1:
        star = 1
    if star >= len(lut):
        star = len(lut) - 1
    return lut[star]


def hit_speed_for(card: Dict[str, Any]) -> float:
    hs = _num(card.get("hit_speed"))
    return hs if hs is not None else DEFAULT_HIT_SPEED


def base_stats_for(card: Dict[str, Any], star: int) -> Tuple[float, float]:
    per_level = card.get("per_level")
    if isinstance(per_level, list) and per_level:
        lvl_row = min(per_level, key=lambda r: r.get("level", 999))
        stars = lvl_row.get("stars", {})
        bucket = stars.get(str(star))
        if isinstance(bucket, dict):
            hp = _num(bucket.get("hp"))
            dps = _num(bucket.get("dps"))
            if hp is not None and dps is not None:
                return hp, dps
            dmg = _num(bucket.get("damage"))
            hs = hit_speed_for(card)
            if hp is not None and dmg is not None and hs:
                return hp, (dmg / hs)

    base_hp = _num(card.get("hp"))
    base_dps = _num(card.get("dps"))
    if base_dps is None:
        dmg = _num(card.get("damage")); hs = hit_speed_for(card)
        if dmg is not None and hs:
            base_dps = dmg / hs
    if base_hp is None:
        base_hp = 1.0
    if base_dps is None:
        base_dps = 1.0
    hp = base_hp * _get_star_multiplier(card, "hp", star)
    dps = base_dps * _get_star_multiplier(card, "dps", star)
    return hp, dps


def damage_for(card: Dict[str, Any], star: int) -> float:
    per_level = card.get("per_level")
    if isinstance(per_level, list) and per_level:
        lvl_row = min(per_level, key=lambda r: r.get("level", 999))
        stars = lvl_row.get("stars", {})
        bucket = stars.get(str(star))
        if isinstance(bucket, dict):
            dmg = _num(bucket.get("damage"))
            if dmg is not None:
                return dmg
            dps = _num(bucket.get("dps"))
            hs = hit_speed_for(card)
            if dps is not None and hs:
                return dps * hs
    dmg = _num(card.get("damage"))
    if dmg is not None:
        return dmg
    dps = _num(card.get("dps"))
    hs = hit_speed_for(card)
    if dps is not None and hs:
        return dps * hs
    return 1.0


def range_for(card: Dict[str, Any]) -> int:
    r = _num(card.get("range"))
    return int(r) if r is not None else DEFAULT_RANGE


def move_speed_for(card: Dict[str, Any]) -> float:
    mv = _num(card.get("move_speed"))
    return mv if mv is not None else DEFAULT_MOVE_SPEED



def projectile_speed_for(card: Dict[str, Any]) -> float:
    # Treat range <= 1 as melee regardless of any projectile_speed field present.
    # This avoids mistakenly classifying melee units as ranged when the scraper
    # omits projectile speed.
    r = range_for(card)
    if r <= 1:
        return 0.0
    ps = _num(card.get("projectile_speed"))
    if ps is None or ps <= 0:
        return DEFAULT_PROJECTILE_SPEED
    return ps

def is_ranged(card: Dict[str, Any]) -> bool:
    """A unit is considered ranged iff its effective tile range exceeds 1."""
    return range_for(card) > 1


def elixir_cost_for(card: Dict[str, Any]) -> int:
    c = _num(card.get("elixir"))
    if c is None:
        return CARD_COST_DEFAULT
    return int(round(c))

# =========================
# Result struct
# =========================
@dataclass
class DamageResult:
    winner: int  # 0 or 1 or -1 for draw
    p0_units_alive: int
    p1_units_alive: int
