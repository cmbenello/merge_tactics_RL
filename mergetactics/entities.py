from __future__ import annotations
from dataclasses import dataclass
from typing import ClassVar, Any
from typing import Tuple, Optional
from .cards import CardCatalog, CardSpec
from . import rules

DEFAULT_LEVEL = 11  # sensible default; override per rules if you like

@dataclass
class Unit:
    card_id: int
    star: int
    pos: Tuple[float, float]
    hp: float
    dps: float
    cooldown: float  # time until next shot (seconds)

    # Catalog is needed for dynamic stats; we keep a process-global cache set by env
    _catalog: ClassVar[Optional[Any]] = None  # CardCatalog OR list/dict of specs
    _level: ClassVar[int] = DEFAULT_LEVEL

    @classmethod
    def bind_catalog(cls, catalog: Any, level: Optional[int] = None):
        """Accept either a real CardCatalog or a plain list/dict of card specs.
        We store as-is; resolution happens in from_card/_resolve_spec."""
        cls._catalog = catalog
        if level is not None:
            cls._level = level

    # --- internal helpers ---
    @classmethod
    def _resolve_spec(cls, card_id: int) -> Any:
        """Return a spec object or dict for card_id.
        Supports:
          - CardCatalog with .get(id)
          - list/tuple of specs (dicts or objects with .id)
          - dict keyed by id (int or str)
        """
        cat = cls._catalog
        if cat is None:
            return None
        # Real catalog
        if hasattr(cat, 'get') and callable(getattr(cat, 'get')):
            try:
                return cat.get(card_id)
            except Exception:
                pass
        # Mapping by id
        if isinstance(cat, dict):
            if card_id in cat:
                return cat[card_id]
            s = str(card_id)
            if s in cat:
                return cat[s]
        # Iterable list/tuple
        if isinstance(cat, (list, tuple)):
            for idx, x in enumerate(cat):
                # object with .id
                if hasattr(x, 'id') and getattr(x, 'id') == card_id:
                    return x
                # dict with 'id'
                if isinstance(x, dict) and str(x.get('id')) == str(card_id):
                    return x
                # fallback: list index is the id
                if idx == card_id:
                    return x
        return None

    @classmethod
    def _spec_level_bounds(cls, spec: Any) -> Tuple[Optional[int], Optional[list]]:
        """Return (best_level, level_list) if available on a CardSpec-like object, else (None, None)."""
        try:
            bl = spec.best_level() if hasattr(spec, 'best_level') else None
            ll = spec.level_list() if hasattr(spec, 'level_list') else None
            return bl, ll
        except Exception:
            return None, None

    @classmethod
    def from_card(cls, card_id: int, star: int, pos: Tuple[int, int]):
        spec = cls._resolve_spec(card_id)
        # If we have a real CardSpec-like object, try that path first
        hp = dps = None
        hit_speed = None
        if spec is not None and not isinstance(spec, dict):
            bl, ll = cls._spec_level_bounds(spec)
            lvl = cls._level if bl is None else min(max(cls._level, min((ll or [cls._level]))), bl)
            try:
                # Prefer direct hp/dps if available
                shp = spec.hp(lvl, star) if hasattr(spec, 'hp') else None
                sdps = spec.dps(lvl, star) if hasattr(spec, 'dps') else None
                sdamage = spec.damage(lvl, star) if hasattr(spec, 'damage') else None
                hit_speed = getattr(spec, 'hit_speed', None)
                if shp is not None:
                    hp = float(shp)
                if sdps is not None:
                    dps = float(sdps)
                elif sdamage is not None and hit_speed not in (None, 0):
                    dps = float(sdamage) / float(hit_speed)
            except Exception:
                hp = dps = None
        
        # Fallback/catalog-as-dicts path using rules helpers
        if hp is None or dps is None or hit_speed is None:
            data = spec if isinstance(spec, dict) else {}  # {} if spec missing
            # Use rules helpers which know how to read the scraper schema
            rhp, rdps = rules.base_stats_for(data, star)
            hp = float(hp if hp is not None else rhp)
            dps = float(dps if dps is not None else rdps)
            hit_speed = float(rules.hit_speed_for(data))

        return cls(
            card_id=card_id,
            star=star,
            pos=(float(pos[0]), float(pos[1])),
            hp=max(1.0, hp),
            dps=max(0.1, dps),
            cooldown=0.0,
        )

    def is_alive(self) -> bool:
        return self.hp > 0.0

    # Dynamic accessors from catalog (dict-friendly)
    def _spec_data(self) -> Optional[dict]:
        s = self._resolve_spec(self.card_id)
        return s if isinstance(s, dict) else None

    def _spec_obj(self) -> Optional[CardSpec]:
        s = self._resolve_spec(self.card_id)
        return s if isinstance(s, CardSpec) else None

    def range(self) -> int:
        sdict = self._spec_data()
        if sdict is not None:
            return int(rules.range_for(sdict))
        sobj = self._spec_obj()
        if sobj is not None and getattr(sobj, 'range', None) is not None:
            return int(sobj.range)
        return 1

    def hit_speed(self) -> float:
        sdict = self._spec_data()
        if sdict is not None:
            return float(rules.hit_speed_for(sdict))
        sobj = self._spec_obj()
        if sobj is not None and getattr(sobj, 'hit_speed', None) is not None:
            return float(sobj.hit_speed)
        return 1.0

    def projectile_speed(self) -> float:
        sdict = self._spec_data()
        if sdict is not None:
            return float(rules.projectile_speed_for(sdict))
        sobj = self._spec_obj()
        if sobj is not None and getattr(sobj, 'projectile_speed', None) is not None:
            return float(sobj.projectile_speed)
        # If ranged type but missing projectile_speed, choose a reasonable default
        # Try to infer type from dict
        if sdict is not None:
            t = str(sdict.get('type', '')).lower()
            if 'ranged' in t:
                return 4.0
        # Try to infer from spec object
        if sobj is not None:
            t = str(getattr(sobj, 'type', '')).lower()
            if 'ranged' in t:
                return 4.0
        return 0.0

    def move_speed(self) -> float:
        sdict = self._spec_data()
        if sdict is not None:
            return float(rules.move_speed_for(sdict))
        sobj = self._spec_obj()
        if sobj is not None and getattr(sobj, 'move_speed', None) is not None:
            return float(sobj.move_speed)
        # fallbacks: melee ~1.0, ranged ~0.5
        if sdict is not None:
            t = str(sdict.get('type', '')).lower()
            return 0.5 if 'ranged' in t else 1.0
        if sobj is not None:
            t = str(getattr(sobj, 'type', '')).lower()
            return 0.5 if 'ranged' in t else 1.0
        return 1.0
