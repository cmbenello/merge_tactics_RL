from __future__ import annotations
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from . import rules
from .entities import Unit
from math import copysign

Action = Tuple[str, tuple]

@dataclass
class Projectile:
    owner: int        # 0 or 1
    dmg: float
    r: float
    c: float
    target_idx: int   # index in the units list at creation time
    remaining: float  # seconds of travel left

@dataclass
class PlayerState:
    elixir: int = rules.START_ELIXIR
    actions_left: int = rules.ACTIONS_PER_DEPLOY
    bench: List[int] = field(default_factory=list)
    units: Dict[Tuple[int,int], Unit] = field(default_factory=dict)  # pos -> unit
    base_hp: int = 10

@dataclass
class BattleEngine:
    # shallow runtime container used only inside a single battle
    units: list            # list of [owner, Unit]
    projectiles: list = field(default_factory=list)

    def nearest_enemy(self, idx: int) -> int | None:
        owner_i, ui = self.units[idx]
        best = None
        best_key = None
        for j, (owner_j, uj) in enumerate(self.units):
            if owner_j == owner_i or not uj.is_alive():
                continue
            d = abs(ui.pos[0] - uj.pos[0]) + abs(ui.pos[1] - uj.pos[1])  # Manhattan in float
            key = (d, uj.pos[1], uj.pos[0], j)
            if best is None or key < best_key:
                best = j
                best_key = key
        return best

    def step(self, dt: float):
        # 1) advance projectiles and apply damage on impact
        alive_mask = [u.is_alive() for _, u in self.units]
        new_proj = []
        for p in self.projectiles:
            p.remaining -= dt
            if p.remaining <= 0:
                # impact if target still alive
                if 0 <= p.target_idx < len(self.units) and alive_mask[p.target_idx]:
                    tgt = self.units[p.target_idx][1]
                    tgt.hp -= p.dmg
                # else projectile fizzles (target died)
            else:
                new_proj.append(p)
        self.projectiles = new_proj

        # 2) per-unit action with cell-centered movement:
        #    - Units move from center of one cell to the next center (no mid-cell combat)
        #    - Attacking only allowed when the unit is centered in a cell
        CENTER_EPS = 1e-4

        def is_center(u):
            return (abs(u.pos[0] - round(u.pos[0])) < CENTER_EPS and
                    abs(u.pos[1] - round(u.pos[1])) < CENTER_EPS)

        def snap_to_center(u):
            u.pos = (float(round(u.pos[0])), float(round(u.pos[1])))

        def start_move(u, next_cell):
            # next_cell is (int r, int c)
            setattr(u, 'move_target', (int(next_cell[0]), int(next_cell[1])))

        def advance_move(u, dt):
            # Move toward target cell center by speed*dt (cells per second)
            if not hasattr(u, 'move_target') or u.move_target is None:
                return False  # not moving
            tr, tc = u.move_target
            # absolute target center coordinates (float == ints)
            trf, tcf = float(tr), float(tc)
            sr, sc = u.pos
            dr = trf - sr
            dc = tcf - sc
            dist = abs(dr) + abs(dc)  # axis-aligned (we only move along one axis per step)
            if dist < CENTER_EPS:
                u.pos = (trf, tcf)
                u.move_target = None
                return True
            spd = u.move_speed()  # cells/sec
            step = spd * dt
            # Move along the axis that has non-zero delta; ensure no overshoot
            if abs(dr) > CENTER_EPS:
                step = min(step, abs(dr))
                u.pos = (sr + (1.0 if dr > 0 else -1.0) * step, sc)
            elif abs(dc) > CENTER_EPS:
                step = min(step, abs(dc))
                u.pos = (sr, sc + (1.0 if dc > 0 else -1.0) * step)
            # Re-check arrival
            sr2, sc2 = u.pos
            if abs(trf - sr2) + abs(tcf - sc2) < CENTER_EPS:
                u.pos = (trf, tcf)
                u.move_target = None
                return True
            return False

        for i, (owner, ui) in enumerate(self.units):
            if not ui.is_alive():
                continue

            # Always keep positions snapped when very close to center
            if is_center(ui):
                snap_to_center(ui)

            # Tick down weapon cooldown
            if ui.cooldown > 0:
                ui.cooldown = max(0.0, ui.cooldown - dt)

            # If currently moving, advance movement and skip attacking this tick
            arrived = advance_move(ui, dt)
            if hasattr(ui, 'move_target') and ui.move_target is not None:
                # still en route; cannot attack mid-cell
                continue

            # Choose target (based on cell centers)
            target_idx = self.nearest_enemy(i)
            if target_idx is None:
                continue
            tj = self.units[target_idx][1]

            # Work with integer cell centers for range computation
            ur, uc = round(ui.pos[0]), round(ui.pos[1])
            tr, tc = round(tj.pos[0]), round(tj.pos[1])
            dist_cells = abs(ur - tr) + abs(uc - tc)
            in_range = dist_cells <= ui.range()

            if not in_range:
                # plan a discrete next step toward target: first reduce row delta, else column delta
                dr = tr - ur
                dc = tc - uc
                if dr != 0:
                    step_cell = (ur + (1 if dr > 0 else -1), uc)
                elif dc != 0:
                    step_cell = (ur, uc + (1 if dc > 0 else -1))
                else:
                    step_cell = (ur, uc)  # same cell; should be in range, but safe-guard
                start_move(ui, step_cell)
                # immediately advance a bit this tick to feel responsive
                advance_move(ui, dt)
                continue

            # In range: only attack if centered (so we don't shoot mid-transition)
            if not is_center(ui):
                # snap if very close; else finish movement first
                if abs(ui.pos[0] - ur) + abs(ui.pos[1] - uc) < 0.5:
                    snap_to_center(ui)
                else:
                    # keep moving toward center of current cell
                    start_move(ui, (ur, uc))
                    advance_move(ui, dt)
                    continue

            # Try to attack if off cooldown
            if ui.cooldown == 0.0:
                dmg = ui.dps * dt  # per-tick damage budget
                ps = ui.projectile_speed()
                if rules.USE_PROJECTILES and ps > 0:
                    # projectile travel time based on L1 distance between centers
                    travel = max(0.0, (abs(ui.pos[0]-tj.pos[0]) + abs(ui.pos[1]-tj.pos[1])) / ps)
                    self.projectiles.append(Projectile(owner=owner, dmg=dmg, r=ui.pos[0], c=ui.pos[1], target_idx=target_idx, remaining=travel))
                else:
                    tj.hp -= dmg
                ui.cooldown = ui.hit_speed()

    def alive_counts(self):
        p0 = sum(1 for o,u in self.units if o==0 and u.is_alive())
        p1 = sum(1 for o,u in self.units if o==1 and u.is_alive())
        return p0, p1

@dataclass
class MTEnv:
    seed: int = 0
    rng: np.random.Generator = field(init=False)
    round: int = 1
    turn: int = 0  # 0 or 1 (who acts during deploy)
    p0: PlayerState = field(default_factory=PlayerState)
    p1: PlayerState = field(default_factory=PlayerState)
    in_battle: bool = False
    done: bool = False
    last_info: dict = field(default_factory=dict)

    def __post_init__(self):
        self.rng = np.random.default_rng(self.seed)

    def reset(self, seed: Optional[int]=None):
        if seed is not None:
            self.seed = seed
            self.rng = np.random.default_rng(self.seed)
        self.round = 1
        self.turn = 0
        self.in_battle = False
        self.done = False
        self.p0 = PlayerState()
        self.p1 = PlayerState()
        self.last_info = {}
        return self.observe()

    def observe(self):
        board = np.zeros((rules.BOARD_ROWS, rules.BOARD_COLS), dtype=np.int32)
        for pos,u in self.p0.units.items():
            board[pos] = 1*10 + u.troop_id*3 + u.star
        for pos,u in self.p1.units.items():
            board[pos] = 2*10 + u.troop_id*3 + u.star
        obs = {
            "board": board,
            "p0_elixir": self.p0.elixir,
            "p1_elixir": self.p1.elixir,
            "round": self.round,
            "turn": self.turn,
            "in_battle": self.in_battle,
            "p0_actions_left": self.p0.actions_left,
            "p1_actions_left": self.p1.actions_left,
        }
        mask = self.legal_actions()
        return obs, mask

    def render(self):
        board = self.observe()[0]["board"]  # current board
        H, W = board.shape
        print(f"Round {self.round} | Turn {self.turn} | in_battle={self.in_battle}")
        for r in range(H):
            row = []
            for c in range(W):
                v = int(board[r, c])
                if v == 0:
                    row.append(" . ")
                else:
                    owner = v // 10
                    rem = v % 10
                    troop = rem // 3
                    star = rem % 3
                    row.append(f"{owner}{troop}{star}")
            print(" ".join(row))

    def _can_buy(self, who: int) -> bool:
        pl = self.p0 if who == 0 else self.p1
        if pl.elixir < rules.COST_PER_TROOP:
            return False
        back_row = 0 if who == 0 else rules.BOARD_ROWS - 1
        for c in range(rules.BOARD_COLS):
            pos = (back_row, c)
            if pos not in self.p0.units and pos not in self.p1.units:
                return True
        return False

    def legal_actions(self) -> List[Action]:
        if self.done: return [("END", ())]
        if self.in_battle: return [("END", ())]
        actions: List[Action] = []
        pl = self.p0 if self.turn == 0 else self.p1
        back_row = 0 if self.turn == 0 else rules.BOARD_ROWS-1

        # BUY options only if player can actually buy now
        if self._can_buy(self.turn):
            for c in range(rules.BOARD_COLS):
                pos = (back_row, c)
                if pos not in self.p0.units and pos not in self.p1.units:
                    for troop_id in rules.TROOP_IDS:
                        actions.append(("BUY_PLACE", (troop_id, back_row, c)))

        # MERGE options (always allowed on your turn)
        owned_positions = [p for p in pl.units.keys()]
        for i in range(len(owned_positions)):
            for j in range(i+1, len(owned_positions)):
                p1 = owned_positions[i]; p2 = owned_positions[j]
                u1 = pl.units[p1]; u2 = pl.units[p2]
                if u1.troop_id == u2.troop_id and u1.star == u2.star and u1.star < 3:
                    if abs(p1[0]-p2[0]) + abs(p1[1]-p2[1]) == 1:
                        actions.append(("MERGE", (p1, p2)))

        # SELL options (always allowed on your turn)
        for pos in pl.units.keys():
            actions.append(("SELL", (pos,)))

        # Always allow END
        actions.append(("END", ()))
        return actions

    def step(self, action: Action):
        if self.done: 
            return self.observe()
        if self.in_battle:
            self.in_battle = False

        atype, args = action
        pl = self.p0 if self.turn == 0 else self.p1
        opp = self.p1 if self.turn == 0 else self.p0

        reward = 0.0
        info = {}

        if atype == "BUY_PLACE":
            troop_id, r, c = args
            if pl.elixir >= rules.COST_PER_TROOP and (r,c) not in self.p0.units and (r,c) not in self.p1.units:
                pl.elixir -= rules.COST_PER_TROOP
                pl.units[(r,c)] = Unit.from_troop(troop_id=troop_id, star=1, pos=(r,c))
                # Do not decrement actions_left; buy budget is elixir/slots
        elif atype == "SELL":
            (pos,) = args
            if pos in pl.units:
                del pl.units[pos]
                pl.elixir += rules.SELL_REFUND
                # Do not decrement actions_left
        elif atype == "MERGE":
            p1, p2 = args
            if p1 in pl.units and p2 in pl.units:
                u1, u2 = pl.units[p1], pl.units[p2]
                if u1.troop_id == u2.troop_id and u1.star == u2.star and u1.star < 3:
                    new_star = u1.star + 1
                    pl.units[p1] = Unit.from_troop(u1.troop_id, new_star, p1)
                    del pl.units[p2]
                # Do not decrement actions_left
        elif atype == "END":
            pl.actions_left = 0

        # Auto-end this player's deploy if they cannot buy anything now
        if not self._can_buy(self.turn):
            # mark no-actions-left for deploy gating
            if self.turn == 0:
                self.p0.actions_left = 0
            else:
                self.p1.actions_left = 0
        else:
            # keep a positive flag while they can still buy
            if self.turn == 0:
                self.p0.actions_left = 1
            else:
                self.p1.actions_left = 1

        if self.p0.actions_left == 0 and self.p1.actions_left == 0:
            self._run_battle()
            self._end_round_reset()

        if not self.in_battle and not self.done:
            # if current player cannot buy, pass turn to opponent (if they can buy)
            if self.turn == 0 and self.p0.actions_left == 0 and self.p1.actions_left != 0:
                self.turn = 1
            elif self.turn == 1 and self.p1.actions_left == 0 and self.p0.actions_left != 0:
                self.turn = 0

        obs, mask = self.observe()
        info = {**info, "mask": mask}
        return obs, reward, self.done, info

    def _run_battle(self):
        self.in_battle = True
        # build engine units list from current board
        units = []
        for pos,u in self.p0.units.items():
            units.append([0, Unit.from_troop(u.troop_id, u.star, (pos[0], pos[1]))])
        for pos,u in self.p1.units.items():
            units.append([1, Unit.from_troop(u.troop_id, u.star, (pos[0], pos[1]))])

        engine = BattleEngine(units=units)
        t = 0.0
        dt = rules.SUB_TICK_DT
        max_t = getattr(rules, "MAX_BATTLE_TIME", 30.0)
        abs_cap = getattr(rules, "ABSOLUTE_BATTLE_TIME_CAP", 300.0)
        end_on_wipe = getattr(rules, "END_ONLY_ON_WIPE", False)

        if end_on_wipe:
            # ignore normal time cap; run until one side is wiped (with absolute safety cap)
            while t < abs_cap:
                p0_alive, p1_alive = engine.alive_counts()
                if p0_alive == 0 or p1_alive == 0:
                    break
                engine.step(dt)
                t += dt
        else:
            # legacy: stop at MAX_BATTLE_TIME or a wipe, whichever comes first
            while t < max_t:
                p0_alive, p1_alive = engine.alive_counts()
                if p0_alive == 0 or p1_alive == 0:
                    break
                engine.step(dt)
                t += dt

        # tally
        p0_alive, p1_alive = engine.alive_counts()
        winner = -1
        if p0_alive>0 and p1_alive==0: winner = 0
        elif p1_alive>0 and p0_alive==0: winner = 1

        if winner == 0:
            self.p1.base_hp -= max(1, p0_alive)
        elif winner == 1:
            self.p0.base_hp -= max(1, p1_alive)

        if self.p0.base_hp <= 0 or self.p1.base_hp <= 0:
            self.done = True

        self.in_battle = False
        self.p0.base_hp = max(0, self.p0.base_hp)
        self.p1.base_hp = max(0, self.p1.base_hp)
        self.last_info = {"p0_alive": p0_alive, "p1_alive": p1_alive, "winner": winner}

    def _end_round_reset(self):
        # Prepare next round: alternate starting player, reset actions & elixir
        self.round += 1
        self.turn = 1 - self.turn
        self.p0.actions_left = rules.ACTIONS_PER_DEPLOY
        self.p1.actions_left = rules.ACTIONS_PER_DEPLOY
        self.p0.elixir = rules.START_ELIXIR
        self.p1.elixir = rules.START_ELIXIR
        if self.round > rules.MAX_ROUNDS:
            self.done = True
