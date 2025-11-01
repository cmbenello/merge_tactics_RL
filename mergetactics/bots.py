from __future__ import annotations
import random
from typing import List, Tuple, Sequence, Any

Action = Tuple[str, tuple]

# ------------- helpers to read obs safely -----------------

def _me(obs) -> int:
    """0 for P0, 1 for P1 (default 0)."""
    try:
        return int(obs.get("turn", 0))
    except Exception:
        return 0

def _my_shop(obs) -> Sequence[Any]:
    """Return current player's shop list (supports 'shop' or 'store')."""
    me = _me(obs)
    key = "p0_shop" if me == 0 else "p1_shop"
    alt = "p0_store" if me == 0 else "p1_store"
    return obs.get(key) or obs.get(alt) or []

def _my_elixir(obs) -> int:
    me = _me(obs)
    key = "p0_elixir" if me == 0 else "p1_elixir"
    try:
        return int(obs.get(key, 0))
    except Exception:
        return 0

def _my_back_row(obs) -> int:
    rows = getattr(obs.get("board"), "shape", (2,))[0]
    return 0 if _me(obs) == 0 else rows - 1

def _my_board_count(obs) -> int:
    """Count units for current player from the encoded board matrix (owner = v // 10)."""
    try:
        me = _me(obs)
        owner_code = 1 if me == 0 else 2
        b = obs["board"]
        return int(((b // 10) == owner_code).sum())
    except Exception:
        return 0

def _unit_cap(obs) -> int:
    """Prefer explicit field if present, else compute from round using rules.unit_cap_for_round."""
    if "unit_cap" in obs:
        try:
            return int(obs["unit_cap"])
        except Exception:
            pass
    try:
        from . import rules  # local import to avoid cyclics on tools
        r = int(obs.get("round", 1))
        return rules.unit_cap_for_round(r)
    except Exception:
        return 6

def _free_cols_on_back_row(obs) -> List[int]:
    """Columns on back row that are empty."""
    b = obs.get("board")
    if b is None:
        return []
    row = _my_back_row(obs)
    W = b.shape[1]
    return [c for c in range(W) if int(b[row, c]) == 0]

# ------------- mask helpers -----------------

def _actions(mask: List[Action], *prefixes: str) -> List[Action]:
    """Return actions whose name starts with any of the given prefixes (case-insensitive)."""
    pref = tuple(p.upper() for p in prefixes)
    out: List[Action] = []
    for a in mask:
        name = a[0].upper()
        if any(name.startswith(p) for p in pref):
            out.append(a)
    return out

def _one(mask: List[Action], *prefixes: str) -> Action | None:
    acts = _actions(mask, *prefixes)
    return acts[0] if acts else None

# ------------- bots -----------------

class RandomBot:
    def act(self, obs, mask: List[Action]) -> Action:
        if not mask:
            return ("END", ())
        # Prefer any non-END action
        non_end = [a for a in mask if a[0].upper() != "END"]
        return random.choice(non_end or mask)

class GreedyBot:
    """
    Robust, name-agnostic heuristic that works with the new store/bench flow.

    Priority each turn:
      1) MERGE (any)
      2) PLACE_FROM_BENCH / PLACE (to any free back-row column)
      3) BUY_FROM_SHOP / BUY_PLACE / BUY (env already enforces affordability)
      4) SELL (only if we're capped or blocked)
      5) END
    """

    def act(self, obs, mask: List[Action]) -> Action:
        if not mask:
            return ("END", ())

        # 1) MERGE
        a = _one(mask, "MERGE")
        if a:
            return a

        free_cols = _free_cols_on_back_row(obs)
        cap = _unit_cap(obs)
        count = _my_board_count(obs)

        # 2) PLACE from bench to any free back-column
        place = _actions(mask, "PLACE_FROM_BENCH", "PLACE")
        if place and free_cols:
            # choose one that lands on a free col
            for a in place:
                try:
                    _, col = a[1]
                    if col in free_cols:
                        return a
                except Exception:
                    continue
            # fallback: first PLACE
            return place[0]

        # 3) BUY from shop (env’s legal mask implies we can afford and have a target col)
        buy = _actions(mask, "BUY_FROM_SHOP", "BUY_PLACE", "BUY")
        if buy and free_cols and count < cap:
            # Prefer buys that target a free col if the env encodes (slot, col)
            for a in buy:
                args = a[1]
                if isinstance(args, tuple) and len(args) == 2:
                    _, col = args
                    if col in free_cols:
                        return a
            return buy[0]

        # 4) SELL only if blocked or at cap
        sell = _actions(mask, "SELL")
        if sell and (count >= cap or not free_cols):
            return random.choice(sell)

        # 5) END
        end = _one(mask, "END")
        return end or mask[0]