"""
Minimal rule config for a two-troop sandbox.
- 1v1 only, 3x3 board (rows x cols), each side places on own back row 
  (row 0 for P0, row 2 for P1).
- Economy: 10 elixir per round, troops cost 3; selling refund 2.
- Round flow: Deploy phase with up to 3 actions, then Battle tick-sim.
- Troops: TANK (melee), ARCHER (ranged). Star levels 1-3 via merge (adjacent & same type/star).
- Damage to base equals surviving enemy unit count when battle ends.
"""
from dataclasses import dataclass

BOARD_ROWS = 6
BOARD_COLS = 6
MAX_ROUNDS = 20
ACTIONS_PER_DEPLOY = 3
START_ELIXIR = 10
COST_PER_TROOP = 3
SELL_REFUND = 2

# troop ids
TANK = 0
ARCHER = 1
TROOP_IDS = [TANK, ARCHER]
TROOP_NAMES = {TANK: "TANK", ARCHER: "ARCHER"}

# base stats at star1
BASE_HP = {TANK: 180, ARCHER: 90}
BASE_DPS = {TANK: 18,  ARCHER: 24}
RANGE    = {TANK: 1,   ARCHER: 3}
HIT_SPEED = {TANK: 1.0, ARCHER: 1.0}

# star scaling
STAR_HP_MUL = [1.0, 1.0, 1.6, 2.56]   # index by star level (1..3)
STAR_DPS_MUL = [1.0, 1.0, 1.4, 1.96]

# battle ticks
TICK_DT = 1.0  # seconds per coarse tick (legacy)
MAX_BATTLE_TICKS = 30

# === Movement and projectile extensions ===
# Movement speed in grid-cells per second (ARCHER is slower)
MOVE_SPEED = {TANK: 1.0, ARCHER: 0.5}

# Projectile travel speed in grid-cells per second
# (0.0 = melee / instant damage)
PROJECTILE_SPEED = {TANK: 0.0, ARCHER: 4.0}

# Enable or disable projectile simulation
USE_PROJECTILES = True

# Subtick step size for finer simulation
SUB_TICK_DT = 0.1  # seconds per physics integration step
MAX_BATTLE_TIME = MAX_BATTLE_TICKS * TICK_DT  # overall time limit (seconds)

# Battle end policy
END_ONLY_ON_WIPE = True                 # only end when one side is wiped
ABSOLUTE_BATTLE_TIME_CAP = 300.0        # hard safety cap in seconds

@dataclass
class DamageResult:
    winner: int  # 0 or 1 or -1 for draw
    p0_units_alive: int
    p1_units_alive: int