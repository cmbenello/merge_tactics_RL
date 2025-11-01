from __future__ import annotations
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Any
from . import rules
from .entities import Unit

Action = Tuple[str, tuple]  # e.g., ("BUY_PLACE", (slot_idx, col))

# -------------------------
# Catalog-aware helpers
# -------------------------
def _has_from_card() -> bool:
    return hasattr(Unit, "from_card")

def _has_bind_catalog() -> bool:
    return hasattr(Unit, "bind_catalog")

def _unit_make(card_or_troop_id: int, star: int, pos: Tuple[int, int]) -> Unit:
    """
    Instantiate a Unit using from_card if available (data-driven),
    otherwise fall back to from_troop (legacy).
    """
    if _has_from_card():
        return Unit.from_card(card_id=card_or_troop_id, star=star, pos=pos)
    else:
        return Unit.from_troop(troop_id=card_or_troop_id, star=star, pos=pos)

def _unit_id(u: Any) -> int:
    """Return the integer id for a unit for board encoding (card_id or troop_id)."""
    if hasattr(u, "card_id"):
        return int(u.card_id)
    return int(getattr(u, "troop_id"))

def _cost_of(id_: int, env_catalog) -> int:
    """
    Price resolution:
      - if catalog present and card has elixir -> use that (rounded to int)
      - else use rules.CARD_COST_DEFAULT
    """
    if env_catalog is not None:
        try:
            spec = env_catalog.get(id_)
            if spec and spec.elixir is not None:
                return int(round(float(spec.elixir)))
        except Exception:
            pass
    return int(rules.CARD_COST_DEFAULT)

# -------------------------
# Runtime structs
# -------------------------
@dataclass
class Projectile:
    owner: int
    dmg: float
    r: float
    c: float
    target_idx: int
    remaining: float

@dataclass
class PlayerState:
    elixir: int = rules.START_ELIXIR
    # We no longer count actions; we auto-end when no legal action remains
    actions_left: int = 1
    # Store and bench
    shop: List[Optional[int]] = field(default_factory=list)           # len == STORE_SLOTS, frozen; slot refills only when bought
    bench: List[Tuple[int, int]] = field(default_factory=list)        # [(id, star)]
    # Board units
    units: Dict[Tuple[int,int], Unit] = field(default_factory=dict)
    base_hp: int = 10

@dataclass
class BattleEngine:
    units: list
    projectiles: list = field(default_factory=list)

    def nearest_enemy(self, idx: int) -> int | None:
        """
        Hex-grid nearest enemy using odd-r offset coordinates.
        We compute cube distance for tie-breaking stability.
        """
        def rc_to_cube(r: int, c: int):
            # odd-r offset to cube
            x = c - ((r & 1) / 2.0)
            z = r
            y = -x - z
            return (x, y, z)

        def hex_dist(r1: int, c1: int, r2: int, c2: int) -> int:
            x1, y1, z1 = rc_to_cube(r1, c1)
            x2, y2, z2 = rc_to_cube(r2, c2)
            return int((abs(x1 - x2) + abs(y1 - y2) + abs(z1 - z2)) / 2)

        owner_i, ui = self.units[idx]
        best = None
        best_key = None
        ur, uc = round(ui.pos[0]), round(ui.pos[1])
        for j, (owner_j, uj) in enumerate(self.units):
            if owner_j == owner_i or not uj.is_alive():
                continue
            tr, tc = round(uj.pos[0]), round(uj.pos[1])
            d = hex_dist(ur, uc, tr, tc)
            # deterministic tie-breaker
            key = (d, tc, tr, j)
            if best is None or key < best_key:
                best = j
                best_key = key
        return best
    
    def step(self, dt: float):
        """Advance the simulation by dt on an odd‑r hex grid.
        - Movement chooses among the 6 hex neighbours that *strictly* reduce hex distance.
        - A neighbour is legal only if no unit (alive or dead) occupies it this frame.
        - Head‑on swaps are detected and both units are stalled briefly to avoid vibration.
        - Dead units persist on the board and count as blockers.
        """
        # ---------- projectile updates ----------
        alive_mask = [u.is_alive() for _, u in self.units]
        tmp = []
        for p in self.projectiles:
            p.remaining -= dt
            if p.remaining <= 0:
                if 0 <= p.target_idx < len(self.units) and alive_mask[p.target_idx]:
                    self.units[p.target_idx][1].hp -= p.dmg
            else:
                tmp.append(p)
        self.projectiles = tmp

        # ---------- hex helpers ----------
        def rc_to_cube(r: int, c: int):
            x = c - ((r & 1) / 2.0)  # odd‑r horizontal layout
            z = r
            y = -x - z
            return (x, y, z)

        def hex_dist(r1: int, c1: int, r2: int, c2: int) -> int:
            x1, y1, z1 = rc_to_cube(r1, c1)
            x2, y2, z2 = rc_to_cube(r2, c2)
            return int((abs(x1 - x2) + abs(y1 - y2) + abs(z1 - z2)) / 2)

        def hex_neighbors(r: int, c: int):
            # odd‑r offset neighbours
            if (r & 1) == 1:  # odd row -> shifted right
                candidates = [(r-1, c), (r-1, c+1), (r, c-1), (r, c+1), (r+1, c), (r+1, c+1)]
            else:              # even row -> shifted left
                candidates = [(r-1, c-1), (r-1, c), (r, c-1), (r, c+1), (r+1, c-1), (r+1, c)]
            # clamp to board
            out = []
            for rr, cc in candidates:
                if 0 <= rr < rules.BOARD_ROWS and 0 <= cc < rules.BOARD_COLS:
                    out.append((rr, cc))
            return out

        CENTER_EPS = 1e-4
        def is_center(u):
            return (abs(u.pos[0] - round(u.pos[0])) < CENTER_EPS and
                    abs(u.pos[1] - round(u.pos[1])) < CENTER_EPS)
        def snap_to_center(u):
            u.pos = (float(round(u.pos[0])), float(round(u.pos[1])))
        def start_move(u, rc):
            setattr(u, "move_target", (int(rc[0]), int(rc[1])))
        def advance_move(u, dt):
            if not hasattr(u, "move_target") or u.move_target is None:
                return False
            tr, tc = u.move_target
            trf, tcf = float(tr), float(tc)
            sr, sc = u.pos
            dr = trf - sr
            dc = tcf - sc
            # smooth slide towards center (no axis snapping)
            spd = u.move_speed()
            step = min(spd * dt, 0.45)  # cap so we never cross a hex in one frame
            L1 = abs(dr) + abs(dc)
            if L1 < CENTER_EPS:
                u.pos = (trf, tcf)
                u.move_target = None
                return True
            ratio = min(1.0, step / max(L1, 1e-6))
            u.pos = (sr + dr * ratio, sc + dc * ratio)
            # arrived?
            if abs(u.pos[0] - trf) + abs(u.pos[1] - tcf) < CENTER_EPS:
                u.pos = (trf, tcf)
                u.move_target = None
                return True
            return False

        # current occupancy (alive or dead)
        occupied = {tuple(map(round, u.pos)) for _, u in self.units}
        # cells already targeted by in‑flight moves are treated as reserved
        reserved = set()
        for _owner, _u in self.units:
            if hasattr(_u, "move_target") and _u.move_target is not None:
                reserved.add(tuple(_u.move_target))
        occupied |= reserved

        # ---------- plan moves ----------
        # We compute each unit's *intended* neighbour on an odd‑r hex grid.
        # A legal intent must:
        #   (1) strictly reduce hex distance to its current target,
        #   (2) point to a currently unoccupied cell (alive or dead unit blocks),
        #   (3) be stable under tie‑breakers to avoid mirror oscillations.
        #
        # Tie‑breaking has two layers:
        #  - Directional bias: P0 prefers +r (down) then +c (right); P1 prefers -r (up) then -c (left).
        #  - Lexicographic: (dist_after, col, row) to make it deterministic.
        #
        # After all intents are computed, we resolve conflicts:
        #  - If two units want the same target cell, allow exactly one winner
        #    picked by (owner bias, source row, source col, unit index) and stall the rest.
        #  - If two units want to swap cells (A->B and B->A), we stall both briefly.
        def owner_bias(owner: int) -> tuple[int, int]:
            # Prefer forward movement by side to break symmetry.
            # P0 "advances" by increasing row; P1 by decreasing row.
            return (1, 0) if owner == 0 else (-1, 0)

        intents: dict[int, Optional[tuple[int, int]]] = {}
        sources: dict[int, tuple[int, int]] = {}
        ordered_options: dict[int, List[tuple[int,int]]] = {}
        for i, (owner, ui) in enumerate(self.units):
            ur, uc = round(ui.pos[0]), round(ui.pos[1])
            sources[i] = (ur, uc)

            # dead or moving or cooling down -> no new plan
            if (not ui.is_alive()) or (not is_center(ui)) or (hasattr(ui, "move_target") and ui.move_target is not None) or (ui.cooldown > 0):
                intents[i] = None
                continue

            t_idx = self.nearest_enemy(i)
            if t_idx is None:
                intents[i] = None
                continue
            tj = self.units[t_idx][1]
            tr, tc = round(tj.pos[0]), round(tj.pos[1])
            d0 = hex_dist(ur, uc, tr, tc)
            if d0 <= ui.range():
                intents[i] = None
                continue

            rb, cb = owner_bias(owner)
            def bias_key(rc: tuple[int,int]):
                rr, cc = rc
                return (rb * (rr - ur), cb * (cc - uc))

            neigh = [n for n in hex_neighbors(ur, uc) if n not in occupied]
            reducing = [n for n in neigh if hex_dist(n[0], n[1], tr, tc) < d0]
            lateral = [n for n in neigh if hex_dist(n[0], n[1], tr, tc) == d0]
            reducing.sort(key=lambda rc: (hex_dist(rc[0], rc[1], tr, tc), bias_key(rc), rc[1], rc[0]))
            lateral.sort(key=lambda rc: (abs(rc[0]-tr)+abs(rc[1]-tc), bias_key(rc), rc[1], rc[0]))
            ordered = reducing + lateral
            ordered_options[i] = ordered
            intents[i] = ordered[0] if ordered else None

        # head‑on swap detection (based on initial intents)
        blocked: set[int] = set()
        for i, tgt in intents.items():
            if tgt is None:
                continue
            src = sources[i]
            for j, tgt_j in intents.items():
                if j <= i or tgt_j is None:
                    continue
                if tgt == sources[j] and tgt_j == src:
                    blocked.add(i); blocked.add(j)

        # two‑pass allocator: first choose winners per cell, then let losers try next options
        taken: set[tuple[int,int]] = set(occupied)
        # remove none/blocked from consideration
        pending = {i: tgt for i, tgt in intents.items() if (tgt is not None and i not in blocked)}
        winners: dict[int, tuple[int,int]] = {}
        while pending:
            # collect candidates per cell
            cell_to_cands: dict[tuple[int,int], List[int]] = {}
            for i, tgt in list(pending.items()):
                if tgt in taken:
                    # try next option immediately
                    opts = ordered_options.get(i, [])
                    if tgt in opts:
                        k = opts.index(tgt) + 1
                        next_tgt = next((x for x in opts[k:] if x not in taken), None)
                        if next_tgt is not None:
                            pending[i] = next_tgt
                            intents[i] = next_tgt
                            continue
                    # no alternative; drop
                    pending.pop(i, None)
                    continue
                cell_to_cands.setdefault(tgt, []).append(i)
            if not cell_to_cands:
                break
            # decide winners for each contested cell
            decided_any = False
            for cell, cands in cell_to_cands.items():
                if not cands:
                    continue
                if len(cands) == 1:
                    i = cands[0]
                    winners[i] = cell
                    taken.add(cell)
                    pending.pop(i, None)
                    decided_any = True
                    continue
                # deterministic winner
                def cand_key(k: int):
                    owner_k, _uk = self.units[k]
                    sr, sc = sources[k]
                    return (owner_k, sr, sc, k)
                cands.sort(key=cand_key)
                i_win = cands[0]
                winners[i_win] = cell
                taken.add(cell)
                pending.pop(i_win, None)
                decided_any = True
                # losers try their next available targets in the next while‑iteration
                for k in cands[1:]:
                    opts = ordered_options.get(k, [])
                    nxt = None
                    if intents.get(k) in opts:
                        idx = opts.index(intents[k]) + 1
                        nxt = next((x for x in opts[idx:] if x not in taken), None)
                    if nxt is not None:
                        pending[k] = nxt
                        intents[k] = nxt
                    else:
                        pending.pop(k, None)
            if not decided_any:
                break

        # ---------- perform moves and cooldowns ----------
        frame_occupied = set(occupied)
        for i, (owner, ui) in enumerate(self.units):
            # tick cooldown
            if ui.cooldown > 0:
                ui.cooldown = max(0.0, ui.cooldown - dt)

            # keep reservation if any
            if hasattr(ui, "_reserved") and ui._reserved is not None:
                frame_occupied.add(tuple(ui._reserved))

            # continue existing motion if any
            if hasattr(ui, "move_target") and ui.move_target is not None:
                if advance_move(ui, dt):
                    frame_occupied.add(tuple(map(round, ui.pos)))
                    if hasattr(ui, "_reserved"):
                        ui._reserved = None
                continue

            # do not move dead or off‑center units
            if not ui.is_alive() or not is_center(ui):
                continue

            # blocked this frame? small reaction delay to avoid buzzing
            if i in blocked:
                ui.cooldown = max(ui.cooldown, 0.18)
                continue

            tgt = intents.get(i)
            if tgt is not None and tgt not in frame_occupied:
                start_move(ui, tgt)
                setattr(ui, "_reserved", tgt)
                frame_occupied.add(tgt)
                # do not advance on the same frame we set an intent; this avoids visual jumps

        # ---------- attacks ----------
        for i, (owner, ui) in enumerate(self.units):
            if not ui.is_alive() or ui.cooldown > 0:
                continue
            if not is_center(ui) or (hasattr(ui, "move_target") and ui.move_target is not None):
                continue
            t_idx = self.nearest_enemy(i)
            if t_idx is None:
                continue
            tj = self.units[t_idx][1]
            ur, uc = round(ui.pos[0]), round(ui.pos[1])
            tr, tc = round(tj.pos[0]), round(tj.pos[1])
            if hex_dist(ur, uc, tr, tc) <= ui.range():
                dmg = ui.dps * dt
                ps = ui.projectile_speed()
                if rules.USE_PROJECTILES and ps > 0:
                    travel = max(0.0, hex_dist(ur, uc, tr, tc) / ps)
                    self.projectiles.append(Projectile(owner=owner, dmg=dmg, r=ui.pos[0], c=ui.pos[1], target_idx=t_idx, remaining=travel))
                else:
                    tj.hp -= dmg
                ui.cooldown = ui.hit_speed()

        # ---------- projectiles post‑attack ----------
        alive_mask = [u.is_alive() for _, u in self.units]
        tmp = []
        for p in self.projectiles:
            p.remaining -= dt
            if p.remaining <= 0:
                if 0 <= p.target_idx < len(self.units) and alive_mask[p.target_idx]:
                    self.units[p.target_idx][1].hp -= p.dmg
            else:
                tmp.append(p)
        self.projectiles = tmp
        # dead units persist; do not remove them

    def alive_counts(self):
        p0 = sum(1 for o,u in self.units if o==0 and u.is_alive())
        p1 = sum(1 for o,u in self.units if o==1 and u.is_alive())
        return p0, p1

class MTEnv:
    """
    Merge-Tactics environment with:
      - Frozen 3-slot store per player; a slot refills only when bought.
      - 5-slot bench (not yet actively filled here; kept for expansion).
      - Per-round board unit cap: starts 2 (round 1) -> grows by 1 capped at 6.
      - Elixir economy; selling refunds rules.SELL_REFUND.
      - Deploy alternates until both players cannot act, then battle.
    Optional: pass a CardCatalog to make the game fully data-driven.
    """
    seed: int
    rng: np.random.Generator
    round: int
    turn: int
    p0: PlayerState
    p1: PlayerState
    in_battle: bool
    done: bool
    last_info: dict

    def __init__(self, seed: int = 0, catalog: Optional[Any] = None, unit_level: Optional[int] = None):
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        # Prefer an explicit catalog; otherwise fall back to rules.CARD_CATALOG if present
        self.catalog = catalog if catalog is not None else getattr(rules, "CARD_CATALOG", None)
        self.unit_level = unit_level

        # Bind catalog to Units (needed for Unit.from_card) if supported
        self._bind_catalog()
        self.reset()

    def _bind_catalog(self):
        """
        Ensure Unit is bound to the active catalog (and level) whenever we (re)start.
        Safe to call multiple times. If binding fails (e.g., plain list not supported),
        we silently skip—env will still run using ids and legacy fallbacks.
        """
        if _has_bind_catalog() and self.catalog is not None:
            try:
                if self.unit_level is not None:
                    Unit.bind_catalog(self.catalog, level=self.unit_level)
                else:
                    Unit.bind_catalog(self.catalog)
            except TypeError:
                # Older signatures may not accept 'level'
                try:
                    Unit.bind_catalog(self.catalog)
                except Exception:
                    pass
            except Exception:
                # Catalog may be a simple list/dict; ignore binding errors
                pass

    # -------- helpers: store / bench / caps --------
    def _all_offer_ids(self) -> List[int]:
        """Return a list of integer card ids available to offer in the shop.
        Supports several catalog shapes:
          - CardCatalog-like object with `.cards` iterable of specs each having `.id`
          - list/tuple of specs (objects with `.id` or dicts with `'id'`)
          - dict mapping -> spec (object or dict)
        Falls back to rules.TROOP_IDS if no ids are discoverable.
        """
        cat = self.catalog or getattr(rules, "CARD_CATALOG", None)
        ids: List[int] = []

        def push_id(x: Any):
            try:
                if hasattr(x, "id") and x.id is not None:
                    ids.append(int(x.id))
                elif isinstance(x, dict) and x.get("id") is not None:
                    ids.append(int(x["id"]))
            except Exception:
                pass

        if cat is not None:
            try:
                # CardCatalog(cards=[...]) shape
                if hasattr(cat, "cards"):
                    for spec in getattr(cat, "cards"):
                        push_id(spec)
                # list/tuple of specs
                elif isinstance(cat, (list, tuple)):
                    for spec in cat:
                        push_id(spec)
                # dict of specs
                elif isinstance(cat, dict):
                    for spec in cat.values():
                        push_id(spec)
            except Exception:
                pass

        if not ids:
            trops = getattr(rules, "TROOP_IDS", None)
            if trops is not None:
                ids = list(trops)
        return ids

    def _rand_offer(self) -> int:
        ids = self._all_offer_ids()
        if not ids:
            # last-resort fallback to two dummy ids (0,1) to avoid crashes in dev
            ids = [0, 1]
        return int(self.rng.choice(ids))

    def _ensure_shop(self, pl: PlayerState):
        while len(pl.shop) < rules.STORE_SLOTS:
            pl.shop.append(self._rand_offer())

    def _board_count(self, who: int) -> int:
        pl = self.p0 if who == 0 else self.p1
        return len(pl.units)

    def _cap(self) -> int:
        return rules.unit_cap_for_round(self.round)

    def _has_empty_back_cell(self, who: int) -> bool:
        back_row = 0 if who == 0 else rules.BOARD_ROWS - 1
        for c in range(rules.BOARD_COLS):
            pos = (back_row, c)
            if pos not in self.p0.units and pos not in self.p1.units:
                return True
        return False

    def _empty_back_cols(self, who: int) -> List[int]:
        back_row = 0 if who == 0 else rules.BOARD_ROWS - 1
        cols = []
        for c in range(rules.BOARD_COLS):
            pos = (back_row, c)
            if pos not in self.p0.units and pos not in self.p1.units:
                cols.append(c)
        return cols

    def _can_buy_from_slot(self, who: int, slot_idx: int) -> bool:
        pl = self.p0 if who == 0 else self.p1
        if slot_idx < 0 or slot_idx >= len(pl.shop): return False
        if pl.shop[slot_idx] is None: return False
        price = _cost_of(pl.shop[slot_idx], self.catalog)
        if pl.elixir < price: return False
        if self._board_count(who) >= self._cap(): return False
        # Only allow buy if there is a truly empty cell in the back row (not occupied by any unit)
        back_row = 0 if who == 0 else rules.BOARD_ROWS - 1
        for c in range(rules.BOARD_COLS):
            pos = (back_row, c)
            # check both p0 and p1 units for occupation
            if pos not in self.p0.units and pos not in self.p1.units:
                # also check that no other unit occupies this cell (should already be covered by units dicts)
                return True
        return False

    def _can_any_action(self, who: int) -> bool:
        pl = self.p0 if who == 0 else self.p1
        # can buy from any slot?
        for si in range(len(pl.shop)):
            if self._can_buy_from_slot(who, si):
                return True
        # can place from bench?
        if pl.bench and self._board_count(who) < self._cap() and self._has_empty_back_cell(who):
            return True
        # can merge?
        owned = list(pl.units.keys())
        for i in range(len(owned)):
            for j in range(i+1, len(owned)):
                p1 = owned[i]; p2 = owned[j]
                u1 = pl.units[p1]; u2 = pl.units[p2]
                if _unit_id(u1) == _unit_id(u2) and u1.star == u2.star and u1.star < 3:
                    if abs(p1[0]-p2[0]) + abs(p1[1]-p2[1]) == 1:
                        return True
        # can sell?
        if pl.units:
            return True
        return False

    # -------------- gym-like API --------------
    def reset(self, seed: Optional[int]=None):
        if seed is not None:
            self.seed = seed
            self.rng = np.random.default_rng(seed)
        self.round = 1
        self.turn = 0
        self.in_battle = False
        self.done = False
        self.p0 = PlayerState(elixir=rules.START_ELIXIR)
        self.p1 = PlayerState(elixir=rules.START_ELIXIR)
        self.last_info = {}

        # (Re)bind catalog for Unit.from_card safety
        self._bind_catalog()

        self._ensure_shop(self.p0)
        self._ensure_shop(self.p1)
        return self.observe()

    def observe(self):
        board = np.zeros((rules.BOARD_ROWS, rules.BOARD_COLS), dtype=np.int32)
        for pos,u in self.p0.units.items():
            uid = _unit_id(u)
            board[pos] = 1*10 + (uid % 10)*3 + (u.star if hasattr(u, "star") else 1)
        for pos,u in self.p1.units.items():
            uid = _unit_id(u)
            board[pos] = 2*10 + (uid % 10)*3 + (u.star if hasattr(u, "star") else 1)
        obs = {
            "board": board,
            "p0_elixir": self.p0.elixir,
            "p1_elixir": self.p1.elixir,
            "round": self.round,
            "turn": self.turn,
            "in_battle": self.in_battle,
            "p0_actions_left": self.p0.actions_left,
            "p1_actions_left": self.p1.actions_left,
            "p0_shop": list(self.p0.shop),
            "p1_shop": list(self.p1.shop),
            "unit_cap": self._cap(),
        }
        mask = self.legal_actions()
        return obs, mask

    def render(self):
        board = self.observe()[0]["board"]
        H, W = board.shape
        print(f"Round {self.round} | Turn {self.turn} | cap={self._cap()} | in_battle={self.in_battle}")
        print("P0 shop:", self.p0.shop, "  elixir:", self.p0.elixir)
        print("P1 shop:", self.p1.shop, "  elixir:", self.p1.elixir)
        for r in range(H):
            row = []
            for c in range(W):
                v = int(board[r, c])
                row.append(" . " if v == 0 else f"{v//10}{(v%10)//3}{(v%10)%3}")
            print(" ".join(row))

    def legal_actions(self) -> List[Action]:
        if self.done or self.in_battle:
            return [("END", ())]
        who = self.turn
        pl = self.p0 if who == 0 else self.p1
        actions: List[Action] = []

        # BUY from shop -> place directly on back row
        empty_cols = self._empty_back_cols(who)
        for si in range(len(pl.shop)):
            if not self._can_buy_from_slot(who, si):
                continue
            for col in empty_cols:
                actions.append(("BUY_PLACE", (si, col)))  # buy slot si, place at back_row,col

        # PLACE_FROM_BENCH
        if pl.bench and self._board_count(who) < self._cap():
            for col in empty_cols:
                for bi in range(len(pl.bench)):
                    actions.append(("PLACE_FROM_BENCH", (bi, col)))

        # MERGE (adjacent, same type/star)
        owned_positions = list(pl.units.keys())
        for i in range(len(owned_positions)):
            for j in range(i+1, len(owned_positions)):
                p1 = owned_positions[i]; p2 = owned_positions[j]
                u1 = pl.units[p1]; u2 = pl.units[p2]
                if _unit_id(u1) == _unit_id(u2) and u1.star == u2.star and u1.star < 3:
                    if abs(p1[0]-p2[0]) + abs(p1[1]-p2[1]) == 1:
                        actions.append(("MERGE", (p1, p2)))

        # SELL
        for pos in pl.units.keys():
            actions.append(("SELL", (pos,)))

        # END always
        actions.append(("END", ()))
        return actions

    def step(self, action: Action):
        if self.done:
            return self.observe()
        if self.in_battle:
            self.in_battle = False

        atype, args = action
        who = self.turn
        pl = self.p0 if who == 0 else self.p1

        reward = 0.0
        info = {}

        back_row = 0 if who == 0 else rules.BOARD_ROWS - 1

        if atype == "BUY_PLACE":
            si, col = args
            pos = (back_row, col)
            # Only allow if cell is truly empty (not occupied by any unit)
            if self._can_buy_from_slot(who, si) and col in self._empty_back_cols(who):
                if pos not in self.p0.units and pos not in self.p1.units:
                    cid = pl.shop[si]
                    price = _cost_of(cid, self.catalog)
                    pl.elixir -= price
                    pl.units[pos] = _unit_make(card_or_troop_id=cid, star=1, pos=pos)
                    # Replace ONLY this slot with a new random offer (store is otherwise frozen)
                    pl.shop[si] = self._rand_offer()

        elif atype == "PLACE_FROM_BENCH":
            bi, col = args
            pos = (back_row, col)
            if 0 <= bi < len(pl.bench) and self._board_count(who) < self._cap() and col in self._empty_back_cols(who):
                if pos not in self.p0.units and pos not in self.p1.units:
                    cid, star = pl.bench.pop(bi)
                    pl.units[pos] = _unit_make(card_or_troop_id=cid, star=star, pos=pos)

        elif atype == "SELL":
            (pos,) = args
            if pos in pl.units:
                del pl.units[pos]
                pl.elixir += rules.SELL_REFUND

        elif atype == "MERGE":
            p1, p2 = args
            if p1 in pl.units and p2 in pl.units:
                u1, u2 = pl.units[p1], pl.units[p2]
                if _unit_id(u1) == _unit_id(u2) and u1.star == u2.star and u1.star < 3:
                    new_star = u1.star + 1
                    pl.units[p1] = _unit_make(card_or_troop_id=_unit_id(u1), star=new_star, pos=p1)
                    del pl.units[p2]

        # Auto-end logic:
        # If player explicitly chose END, treat it as a pass even if they could still act.
        # Otherwise, auto-end when no legal actions remain.
        if atype == "END":
            pl.actions_left = 0
        else:
            pl.actions_left = 1 if self._can_any_action(who) else 0

        # If both done -> battle
        if self.p0.actions_left == 0 and self.p1.actions_left == 0:
            self._run_battle()
            self._end_round_reset()

        # Turn handoff
        if not self.in_battle and not self.done:
            if self.turn == 0 and self.p0.actions_left == 0 and self.p1.actions_left != 0:
                self.turn = 1
            elif self.turn == 1 and self.p1.actions_left == 0 and self.p0.actions_left != 0:
                self.turn = 0

        obs, mask = self.observe()
        info = {**info, "mask": mask}
        return obs, reward, self.done, info

    def _run_battle(self):
        self.in_battle = True
        units = []
        for pos, u in self.p0.units.items():
            units.append([0, _unit_make(card_or_troop_id=_unit_id(u), star=u.star, pos=(pos[0], pos[1]))])
        for pos, u in self.p1.units.items():
            units.append([1, _unit_make(card_or_troop_id=_unit_id(u), star=u.star, pos=(pos[0], pos[1]))])
        engine = BattleEngine(units=units)

        t = 0.0
        dt = rules.SUB_TICK_DT
        if rules.END_ONLY_ON_WIPE:
            while t < rules.ABSOLUTE_BATTLE_TIME_CAP:
                p0_alive, p1_alive = engine.alive_counts()
                if p0_alive == 0 or p1_alive == 0:
                    break
                engine.step(dt)
                t += dt
        else:
            while t < rules.MAX_BATTLE_TIME:
                p0_alive, p1_alive = engine.alive_counts()
                if p0_alive == 0 or p1_alive == 0:
                    break
                engine.step(dt)
                t += dt

        # Do NOT remove dead units from engine.units; dead units persist into future rounds
        p0_alive, p1_alive = engine.alive_counts()
        winner = -1
        if p0_alive > 0 and p1_alive == 0:
            winner = 0
        elif p1_alive > 0 and p0_alive == 0:
            winner = 1

        if winner == 0:
            self.p1.base_hp -= max(1, p0_alive)
        elif winner == 1:
            self.p0.base_hp -= max(1, p1_alive)

        if self.p0.base_hp <= 0 or self.p1.base_hp <= 0:
            self.done = True

        # Update each player's units dicts with all units (including dead) after battle
        self.p0.units.clear()
        self.p1.units.clear()
        for owner, unit in engine.units:
            pos = (int(round(unit.pos[0])), int(round(unit.pos[1])))
            if owner == 0:
                self.p0.units[pos] = unit
            elif owner == 1:
                self.p1.units[pos] = unit

        self.in_battle = False
        self.p0.base_hp = max(0, self.p0.base_hp)
        self.p1.base_hp = max(0, self.p1.base_hp)
        self.last_info = {"p0_alive": p0_alive, "p1_alive": p1_alive, "winner": winner}

    def _end_round_reset(self):
        self.round += 1
        self.turn = 1 - self.turn
        # Reset “can act” flags; elixir refresh (simple per-round grant)
        self.p0.actions_left = 1
        self.p1.actions_left = 1
        self.p0.elixir = rules.START_ELIXIR
        self.p1.elixir = rules.START_ELIXIR
        # Store remains frozen unless buying; ensure slot list length intact
        self._ensure_shop(self.p0)
        self._ensure_shop(self.p1)
        if self.round > rules.MAX_ROUNDS:
            self.done = True