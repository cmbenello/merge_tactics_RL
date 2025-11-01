# Merge Tactics Mini-Arena (Two Troops)

A minimal 1v1 arena with **TANK** and **ARCHER** only. 3x3 board, deploy phase with 3 actions, then simple tick battle.
Use it to bootstrap self-play and plug in PPO later.

## Layout
- `mergetactics/rules.py` — constants for board, economy, and basic troop stats.
- `mergetactics/entities.py` — `Unit` dataclass and star scaling.
- `mergetactics/env.py` — lightweight environment with `reset()`, `observe()`, `step()`.
- `mergetactics/bots.py` — `RandomBot` and `GreedyBot` baselines.
- `mergetactics/arena.py` — `ArenaManager` with snapshots and a mini-tournament.
- `scripts/play_match.py` — example match: Greedy vs Random.
- `tests/test_env.py` — basic smoke tests.

## Quickstart
```bash
# Run a single match (Greedy vs Random)
python -m scripts.play_match

# Mini tournament (inside Python)
from mergetactics.arena import ArenaManager
from mergetactics.env import MTEnv
am = ArenaManager(env_ctor=lambda: MTEnv(seed=0))
print(am.mini_tournament(n_games=20))
```
