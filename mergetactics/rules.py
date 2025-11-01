from dataclasses import dataclass
from typing import Dict, Any, Tuple, Optional, List
import json, os

# =========================
# Catalog loading (cards scraped from wiki)
# =========================
# Default location can be overridden with env var MT_CATALOG
_DEF_CATALOG_REL = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                'data', 'merge_tactics_units.json')
CATALOG_PATH = os.environ.get('MT_CATALOG', _DEF_CATALOG_REL)

def _load_catalog(path: str) -> List[Dict[str, Any]]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
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

CARD_CATALOG: List[Dict[str, Any]] = _load_catalog(CATALOG_PATH)

# Public id space = indices into CARD_CATALOG
TROOP_IDS: List[int] = list(range(len(CARD_CATALOG)))
TROOP_NAMES: Dict[int, str] = {i: CARD_CATALOG[i].get('name', f'ID{i}') for i in TROOP_IDS}
CARD_TRAITS: Dict[int, List[str]] = {i: CARD_CATALOG[i].get('traits', []) for i in TROOP_IDS}

def card_by_id(tid: int) -> Dict[str, Any]:
    return CARD_CATALOG[tid]

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
DEFAULT_PROJECTILE_SPEED = 0.0   # cells per second (0.0 == melee / instant)

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
    if star < 1: star = 1
    if star >= len(lut): star = len(lut) - 1
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
        if dmg is not None and hs: base_dps = dmg / hs
    if base_hp is None: base_hp = 1.0
    if base_dps is None: base_dps = 1.0
    hp  = base_hp  * _get_star_multiplier(card, "hp",  star)
    dps = base_dps * _get_star_multiplier(card, "dps", star)
    return hp, dps

def range_for(card: Dict[str, Any]) -> int:
    r = _num(card.get("range"))
    return int(r) if r is not None else DEFAULT_RANGE

def move_speed_for(card: Dict[str, Any]) -> float:
    mv = _num(card.get("move_speed"))
    return mv if mv is not None else DEFAULT_MOVE_SPEED

def projectile_speed_for(card: Dict[str, Any]) -> float:
    ps = _num(card.get("projectile_speed"))
    return ps if ps is not None else DEFAULT_PROJECTILE_SPEED

def elixir_cost_for(card: Dict[str, Any]) -> int:
    c = _num(card.get("elixir"))
    if c is None: return CARD_COST_DEFAULT
    return int(round(c))

# =========================
# Result struct
# =========================
@dataclass
class DamageResult:
    winner: int  # 0 or 1 or -1 for draw
    p0_units_alive: int
    p1_units_alive: int