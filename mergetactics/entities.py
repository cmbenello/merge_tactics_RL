from dataclasses import dataclass
from typing import Tuple
from . import rules

@dataclass
class Unit:
    troop_id: int
    star: int
    hp: float
    dps: float
    pos: Tuple[float, float]  # (r, c) as floats for smooth movement
    cooldown: float = 0.0     # seconds until next attack is allowed

    @staticmethod
    def from_troop(troop_id: int, star: int, pos):
        """Create a Unit from troop_id, star level, and grid position."""
        hp = rules.BASE_HP[troop_id] * rules.STAR_HP_MUL[star]
        dps = rules.BASE_DPS[troop_id] * rules.STAR_DPS_MUL[star]
        r, c = pos
        return Unit(
            troop_id=troop_id,
            star=star,
            hp=hp,
            dps=dps,
            pos=(float(r), float(c)),
            cooldown=0.0,
        )

    def is_alive(self) -> bool:
        return self.hp > 0

    def range(self) -> int:
        """Attack range in grid cells."""
        return rules.RANGE[self.troop_id]

    def move_speed(self) -> float:
        """Movement speed (cells per second)."""
        return rules.MOVE_SPEED[self.troop_id]

    def projectile_speed(self) -> float:
        """Projectile travel speed (cells per second)."""
        return rules.PROJECTILE_SPEED[self.troop_id]

    def hit_speed(self) -> float:
        """Seconds between attacks."""
        return rules.HIT_SPEED[self.troop_id]