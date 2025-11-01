from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import json
import math

Number = float | int

def _num(x: Any) -> Optional[float]:
    # Parses numbers or {"value": v, "unit": "..."} to a float (seconds/tiles kept as numeric).
    if x is None: return None
    if isinstance(x, (int, float)): return float(x)
    if isinstance(x, dict) and "value" in x: return float(x["value"])
    try:
        return float(str(x).replace(",", ""))
    except Exception:
        return None

@dataclass(frozen=True)
class CardSpec:
    id: int                 # internal id
    name: str               # "Archer (Merge Tactics)"
    url: str
    elixir: Optional[float]
    type: Optional[str]     # "Ranged"/"Melee"/etc
    range: Optional[float]  # tiles
    hit_speed: Optional[float]  # seconds/attack
    projectile_speed: Optional[float]
    move_speed: Optional[float]
    traits: List[str]
    # per_level: [{level:int, stars:{"1":{"hp":..,"damage":..,"dps":..}, ...}}]
    per_level: List[Dict[str, Any]]
    extras: Dict[str, Any]

    def level_list(self) -> List[int]:
        return [int(e["level"]) for e in self.per_level] if self.per_level else []

    def best_level(self) -> Optional[int]:
        return max(self.level_list()) if self.per_level else None

    def stars_at(self, level: int) -> Dict[str, Dict[str, Number]]:
        # returns {"1":{"hp":..,"damage":..,"dps":..}, ...}
        for e in self.per_level:
            if int(e["level"]) == int(level):
                return e.get("stars", {})
        return {}

    def stat_at(self, level: int, star: int, key: str) -> Optional[float]:
        bucket = self.stars_at(level).get(str(star), {})
        val = bucket.get(key)
        return _num(val)

    def hp(self, level: int, star: int) -> Optional[float]:
        return self.stat_at(level, star, "hp")

    def damage(self, level: int, star: int) -> Optional[float]:
        # Some pages use "damage", some "area_damage"; prefer damage, fallback to area_damage.
        val = self.stat_at(level, star, "damage")
        if val is None:
            val = self.stat_at(level, star, "area_damage")
        return val

    def dps(self, level: int, star: int) -> Optional[float]:
        return self.stat_at(level, star, "dps")

@dataclass
class CardCatalog:
    cards: List[CardSpec]
    id_by_name: Dict[str, int]

    @classmethod
    def load(cls, path: str) -> "CardCatalog":
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        cards: List[CardSpec] = []
        id_by_name: Dict[str, int] = {}
        for i, rec in enumerate(raw):
            name = rec.get("name", f"Card{i}")
            spec = CardSpec(
                id=i,
                name=name,
                url=rec.get("url",""),
                elixir=_num(rec.get("elixir")),
                type=rec.get("type"),
                range=_num(rec.get("range")),
                hit_speed=_num(rec.get("hit_speed")),
                projectile_speed=_num(rec.get("projectile_speed")),
                move_speed=_num(rec.get("move_speed")),
                traits=rec.get("traits", []),
                per_level=rec.get("per_level", []),
                extras=rec.get("extras", {}),
            )
            cards.append(spec)
            id_by_name[name] = i
        return cls(cards=cards, id_by_name=id_by_name)

    def all_ids(self) -> List[int]:
        return [c.id for c in self.cards]

    def get(self, card_id: int) -> CardSpec:
        return self.cards[card_id]

    def by_name(self, name: str) -> Optional[CardSpec]:
        idx = self.id_by_name.get(name)
        return None if idx is None else self.cards[idx]