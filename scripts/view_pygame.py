import os, sys, time, math
import pygame
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from mergetactics.env import MTEnv, BattleEngine, Projectile
from mergetactics.bots import GreedyBot, RandomBot
from mergetactics import rules
from mergetactics.entities import Unit

# ==============================
# Layout / sizing
# ==============================
CELL = 120                 # board cell size (smaller to make room for UI)
PADDING = 16
BOARD_W, BOARD_H = rules.BOARD_COLS, rules.BOARD_ROWS

# Wider, shorter window – board centered, stores on top/bottom, benches on left/right
TOP_H = 140               # top bar for P0 store
BOT_H = 140               # bottom bar for P1 store
SIDE_W = 240              # left/right columns for benches

#
# approximate board footprint with hex metrics
BOARD_PIXEL_W = math.sqrt(3) * (CELL * 0.42) * (BOARD_W + 0.5) + math.sqrt(3) * (CELL * 0.42) * 0.75
BOARD_PIXEL_H = 1.5 * (CELL * 0.42) * (BOARD_H - 1) + 2 * (CELL * 0.42) * 1.2
W = int(SIDE_W*2 + PADDING*2 + BOARD_PIXEL_W)
H = int(TOP_H + PADDING + BOARD_PIXEL_H + PADDING + BOT_H)

# Colors
BG = (18, 18, 24)
GRID = (55, 60, 72)
WHITE = (230, 230, 235)
SUBTLE = (160, 165, 180)
P0C = (40, 140, 255)
P1C = (255, 90, 90)
TILE_BG = (36, 38, 48)
TILE_BORDER = (70, 75, 90)
BAR_BG = (60, 60, 75)
HP_BAR = (120, 230, 120)
ELIXIR_BAR = (140, 120, 255)

# Trait palette (lightly opinionated; fallback if you haven’t wired real traits yet)
TRAIT_COLORS = {
    'Undead': (120, 240, 160),
    'Ranger': (130, 170, 255),
    'Goblin': (110, 210, 110),
    'Royal': (245, 210, 90),
    'Avenger': (250, 120, 160),
}
DEFAULT_CARD_FG = (200, 200, 210)
DEFAULT_CARD_BG = (50, 54, 70)

# ==== Hex geometry (pointy-top, odd-r offset) ====
HEX_R = CELL * 0.42                         # hex radius (visual)
HEX_W = math.sqrt(3) * HEX_R               # width of a hex
HEX_H = 2 * HEX_R                          # height of a hex
HEX_VSTEP = 1.5 * HEX_R                    # vertical distance between row centers (pointy-top)

def hex_center(rc):
    """Return pixel center (x,y) for grid coords (r,c) using odd-r offset."""
    r, c = rc
    bx, by = board_origin()
    # offset x by half a hex width for odd rows
    x = bx + HEX_W * (c + 0.5 * (r & 1))
    y = by + HEX_VSTEP * r
    # small margins so top-left hex is fully visible
    return int(x + HEX_W * 0.75), int(y + HEX_R * 1.1)

def hex_points(cx, cy, r=HEX_R):
    """6 vertices of a pointy-top hex centered at (cx,cy)."""
    pts = []
    for k in range(6):
        theta = math.radians(60 * k - 30)  # pointy-top
        pts.append((cx + r * math.cos(theta), cy + r * math.sin(theta)))
    return pts

# Safe defaults if rules module lacks these
SUB_TICK_DT = getattr(rules, "SUB_TICK_DT", 0.1)
MAX_BATTLE_TIME = getattr(rules, "MAX_BATTLE_TIME", 30.0)
ABSOLUTE_BATTLE_TIME_CAP = getattr(rules, "ABSOLUTE_BATTLE_TIME_CAP", 300.0)
END_ONLY_ON_WIPE = getattr(rules, "END_ONLY_ON_WIPE", False)

# Runtime speed controls
SPEED_MULT = 1.0
DEPLOY_DELAY_MS_DEFAULT = 250

ARCHER = getattr(rules, 'ARCHER', 1)
TANK = getattr(rules, 'TANK', 0)

# ==============================
# Helpers
# ==============================

def board_origin():
    bx = SIDE_W + PADDING
    by = TOP_H
    return bx, by

def cell_rect(r, c):
    # bounding box around the hex (used rarely)
    cx, cy = hex_center((r, c))
    return pygame.Rect(int(cx - HEX_W/2), int(cy - HEX_H/2), int(HEX_W), int(HEX_H))

def pos_to_px(rf, cf):
    # fractional hex coordinates -> interpolate centers
    # treat rf, cf as continuous in same lattice; use nearest centers for simplicity
    return hex_center((int(round(rf)), int(round(cf))))

def draw_grid(surf):
    for r in range(BOARD_H):
        for c in range(BOARD_W):
            cx, cy = hex_center((r, c))
            pygame.draw.polygon(surf, GRID, hex_points(cx, cy), width=2)

# ---------- Bars / HUD ----------

def draw_text(surf, font, text, x, y, color=WHITE):
    surf.blit(font.render(text, True, color), (x, y))


def draw_bar(surf, x, y, w, h, frac, fg, bg=BAR_BG, border=2):
    pygame.draw.rect(surf, bg, (x, y, w, h), border_radius=5)
    inner_w = max(0, int(w * max(0.0, min(1.0, frac))))
    pygame.draw.rect(surf, fg, (x, y, inner_w, h), border_radius=5)


# ---------- Cards: store/bench tiles ----------

def _traits_for_tid(tid):
    # Try rules.CARD_TRAITS (mapping tid->list[str]); else empty
    traits_map = getattr(rules, 'CARD_TRAITS', {})
    return traits_map.get(tid, [])


def _name_for_tid(tid):
    names = getattr(rules, 'TROOP_NAMES', {})
    return names.get(tid, f"ID{tid}")


def card_chip(surf, rect, tid, font_small, font_big):
    # Background
    pygame.draw.rect(surf, TILE_BG, rect, border_radius=10)
    pygame.draw.rect(surf, TILE_BORDER, rect, width=2, border_radius=10)

    # Trait ribbons (up to two)
    traits = _traits_for_tid(tid)
    sw = max(8, rect.w // 8)
    x0 = rect.x + 6
    for k, t in enumerate(traits[:2]):
        c = TRAIT_COLORS.get(t, DEFAULT_CARD_BG)
        rr = pygame.Rect(x0 + k*(sw+4), rect.y + 6, sw, 16)
        pygame.draw.rect(surf, c, rr, border_radius=3)

    # Name label
    nm = _name_for_tid(tid)
    label = font_small.render(nm, True, DEFAULT_CARD_FG)
    surf.blit(label, (rect.x + 8, rect.y + rect.h//2 - label.get_height()//2))


def draw_store_row(surf, font_small, font_big, items, owner=0):
    # items: list of troop_ids (or data with .troop_id)
    bg = pygame.Rect(SIDE_W, 0 if owner==0 else H-BOT_H, W-2*SIDE_W, TOP_H if owner==0 else BOT_H)
    pygame.draw.rect(surf, (24,24,32), bg)
    pygame.draw.rect(surf, (44,44,58), bg, width=1)

    x = bg.x + 12
    y = bg.y + 12
    draw_text(surf, font_big, f"P{owner} Store", x, y)

    # Render 3 slots
    slot_w = (bg.w - 24 - 2*12) // 3
    slot_h = 72
    sy = y + 28
    for i in range(3):
        rect = pygame.Rect(x + i*(slot_w+12), sy, slot_w, slot_h)
        pygame.draw.rect(surf, TILE_BG, rect, border_radius=10)
        pygame.draw.rect(surf, TILE_BORDER, rect, width=2, border_radius=10)
        if i < len(items):
            itm = items[i]
            # Accept forms: int id, (id, star), {"troop_id": id}
            if isinstance(itm, (list, tuple)) and len(itm) >= 1:
                tid = itm[0]
            elif isinstance(itm, dict) and 'troop_id' in itm:
                tid = itm['troop_id']
            else:
                tid = itm
            card_chip(surf, rect, tid, font_small, font_big)


def draw_bench_column(surf, font_small, font_big, items, owner=0, hp=None, elixir=None):
    # items: list of troop_ids (or data)
    x = 0 if owner==0 else W - SIDE_W
    bg = pygame.Rect(x, 0, SIDE_W, H)
    pygame.draw.rect(surf, (24,24,32), bg)
    pygame.draw.rect(surf, (44,44,58), bg, width=1)

    title = f"P{owner} Bench"
    draw_text(surf, font_big, title, x + 12, 10)

    # Show HP/Elixir bars under title
    if hp is None:
        hp = 10
    if elixir is None:
        elixir = 0
    draw_bar(surf, x+12, 40, SIDE_W-24, 12, hp/10.0, HP_BAR)
    draw_bar(surf, x+12, 58, SIDE_W-24, 10, elixir/max(1, getattr(rules,'START_ELIXIR',4)), ELIXIR_BAR)

    # Slots (vertical list)
    slot_w = SIDE_W - 24
    slot_h = 60
    y0 = 80
    for i in range(5):
        rect = pygame.Rect(x + 12, y0 + i*(slot_h+10), slot_w, slot_h)
        pygame.draw.rect(surf, TILE_BG, rect, border_radius=10)
        pygame.draw.rect(surf, TILE_BORDER, rect, width=2, border_radius=10)
        if i < len(items):
            itm = items[i]
            # Bench entries can be (id, star), dict, or int id
            if isinstance(itm, (list, tuple)) and len(itm) >= 1:
                tid = itm[0]
            elif isinstance(itm, dict) and 'troop_id' in itm:
                tid = itm['troop_id']
            else:
                tid = itm
            card_chip(surf, rect, tid, font_small, font_big)


# ==============================
# Engine mirroring from env
# ==============================

def build_engine_from_env(env):
    units = []
    for pos, u in env.p0.units.items():
        cid = getattr(u, 'card_id', getattr(u, 'troop_id', 0))
        units.append([0, Unit.from_card(card_id=cid, star=getattr(u, 'star', 1), pos=(pos[0], pos[1]))])
    for pos, u in env.p1.units.items():
        cid = getattr(u, 'card_id', getattr(u, 'troop_id', 0))
        units.append([1, Unit.from_card(card_id=cid, star=getattr(u, 'star', 1), pos=(pos[0], pos[1]))])
    return BattleEngine(units=units)


# ==============================
# Env API compatibility shim
# ==============================

def env_step_with_mask(env, action):
    ret = env.step(action)
    if isinstance(ret, tuple):
        if len(ret) == 4:
            obs, reward, done, info = ret
            mask = info.get("mask") if isinstance(info, dict) else None
            if mask is None:
                _, mask = env.observe()
            return obs, mask, reward, done, info
        if len(ret) == 2:
            obs, mask = ret
            reward = 0.0
            done = getattr(env, "done", False)
            info = {}
            return obs, mask, reward, done, info
    obs, mask = env.observe()
    return obs, mask, 0.0, getattr(env, "done", False), {}


# ==============================
# Drawing board units & projectiles
# ==============================

def draw_unit(surf, unit, owner, font_small=None):
    cx, cy = pos_to_px(unit.pos[0], unit.pos[1])
    color = P0C if owner == 0 else P1C

    # Shape: melee = circle, ranged = diamond (based on projectile speed)
    try:
        is_ranged = float(unit.projectile_speed()) > 0.0
    except Exception:
        is_ranged = False
    if not is_ranged:
        pygame.draw.circle(surf, color, (cx, cy), int(HEX_R * 0.71))
    else:
        s = int(HEX_R * 0.66)
        pts = [(cx, cy-s), (cx+s, cy), (cx, cy+s), (cx-s, cy)]
        pygame.draw.polygon(surf, color, pts)

    # star pips
    pip = int(HEX_R * 0.14)
    gap = int(HEX_R * 0.32)
    start_x = cx - gap
    for i in range(int(getattr(unit, 'star', 1))):
        pygame.draw.circle(surf, WHITE, (start_x + i*gap, cy - int(HEX_R * 0.95)), pip)

    # hp bar
    max_hp = (
        getattr(unit, 'max_hp', None)
        or getattr(unit, 'hp_max', None)
        or getattr(unit, '_max_hp', None)
    )
    if max_hp is None:
        try:
            max_hp = max(1.0, float(getattr(unit, 'hp', 1.0)))
        except Exception:
            max_hp = 1.0
    cur_hp = float(getattr(unit, 'hp', 0.0))
    ratio = 0.0 if max_hp <= 0 else (cur_hp / float(max_hp))
    hp_w = int(ratio * (HEX_W * 0.55))
    bar_x = cx - int(HEX_W * 0.275)
    bar_y = cy + int(HEX_R * 0.8)
    pygame.draw.rect(surf, (80,80,90), (bar_x, bar_y, int(HEX_W*0.55), 6), border_radius=3)
    pygame.draw.rect(surf, (80,255,120), (bar_x, bar_y, max(0, hp_w), 6), border_radius=3)


def draw_projectile(surf, p):
    cx, cy = pos_to_px(p.r, p.c)
    color = P0C if p.owner == 0 else P1C
    pygame.draw.circle(surf, color, (cx, cy), max(3, int(HEX_R * 0.15)))


# ==============================
# Deploy visualizer
# ==============================

def visualize_deploy(screen, font_big, font_small, env, b0, b1, delay_ms=DEPLOY_DELAY_MS_DEFAULT):
    obs, mask = env.observe()
    action_text = "Start deploy"
    clock = pygame.time.Clock()

    while not (env.p0.actions_left == 0 and env.p1.actions_left == 0):
        screen.fill(BG)
        # pull fresh obs each frame for UI drawing
        obs, _mask_now = env.observe()
        mask = _mask_now

        # stores & benches
        p0_store = obs.get('p0_shop', [])
        p1_store = obs.get('p1_shop', [])
        p0_bench = getattr(env.p0, 'bench', [])
        p1_bench = getattr(env.p1, 'bench', [])
        draw_store_row(screen, font_small, font_big, p0_store, owner=0)
        draw_store_row(screen, font_small, font_big, p1_store, owner=1)
        draw_bench_column(screen, font_small, font_big, p0_bench, owner=0,
                          hp=getattr(env.p0, 'base_hp', 10),
                          elixir=getattr(env.p0, 'elixir', 0))
        draw_bench_column(screen, font_small, font_big, p1_bench, owner=1,
                          hp=getattr(env.p1, 'base_hp', 10),
                          elixir=getattr(env.p1, 'elixir', 0))

        # board
        draw_grid(screen)
        for (r,c), u in env.p0.units.items():
            draw_unit(screen, u, 0, font_small)
        for (r,c), u in env.p1.units.items():
            draw_unit(screen, u, 1, font_small)

        # footer deploy hint centered over board bottom
        bx, by = board_origin()
        draw_text(screen, font_small, f"Action: {action_text}   (± to change speed, SPACE pause)", bx, by + CELL*BOARD_H + 8)

        pygame.display.flip()

        # hotkeys
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return None
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_MINUS:
                    delay_ms = min(1000, delay_ms + 50)
                elif ev.key in (pygame.K_EQUALS, pygame.K_PLUS):
                    delay_ms = max(0, delay_ms - 50)
                elif ev.key == pygame.K_SPACE:
                    # simple modal pause
                    paused = True
                    while paused:
                        for ev2 in pygame.event.get():
                            if ev2.type == pygame.QUIT:
                                return None
                            if ev2.type == pygame.KEYDOWN and ev2.key == pygame.K_SPACE:
                                paused = False
                        pygame.time.Clock().tick(60)
                elif ev.key == pygame.K_ESCAPE:
                    return None
        clock.tick(60)
        pygame.time.delay(delay_ms)

        # snapshot before stepping so we can animate that battle state
        pre_p0_units = {pos: (getattr(u, 'card_id', getattr(u, 'troop_id', 0)), getattr(u, 'star', 1)) for pos, u in env.p0.units.items()}
        pre_p1_units = {pos: (getattr(u, 'card_id', getattr(u, 'troop_id', 0)), getattr(u, 'star', 1)) for pos, u in env.p1.units.items()}

        # choose & step
        bot = b0 if env.turn == 0 else b1
        action = bot.act(obs, mask)
        action_text = f"P{env.turn} -> {action[0]} {action[1]}"
        prev_round = env.round
        obs, mask, reward, done, info = env_step_with_mask(env, action)

        if (env.p0.actions_left == 0 and env.p1.actions_left == 0) or (env.round > prev_round):
            units = []
            for (r,c), (tid, star) in pre_p0_units.items():
                units.append([0, Unit.from_card(card_id=tid, star=star, pos=(r, c))])
            for (r,c), (tid, star) in pre_p1_units.items():
                units.append([1, Unit.from_card(card_id=tid, star=star, pos=(r, c))])
            return BattleEngine(units=units)

    return None


# ==============================
# Battle visualizer
# ==============================

def visualize_battle(screen, font_big, font_small, env, speed=1.0, engine=None):
    engine = engine or build_engine_from_env(env)
    clock = pygame.time.Clock()
    global SPEED_MULT

    def wrap_step(dt):
        before = len(engine.projectiles)
        engine.step(dt)
        after = len(engine.projectiles)
        for i in range(before, after):
            p = engine.projectiles[i]
            if 0 <= p.target_idx < len(engine.units):
                tgt = engine.units[p.target_idx][1]
                p.tr = float(tgt.pos[0]); p.tc = float(tgt.pos[1])
                p.sr = float(p.r); p.sc = float(p.c)
                p._draw_tremain0 = max(1e-6, p.remaining)
        for p in engine.projectiles:
            if hasattr(p, "_draw_tremain0"):
                frac = 1.0 - (p.remaining / p._draw_tremain0)
                frac = 0.0 if frac < 0.0 else (1.0 if frac > 1.0 else frac)
                p.r = p.sr + (p.tr - p.sr) * frac
                p.c = p.sc + (p.tc - p.sc) * frac

    t = 0.0
    dt = SUB_TICK_DT
    max_t = MAX_BATTLE_TIME
    abs_cap = ABSOLUTE_BATTLE_TIME_CAP
    end_on_wipe = END_ONLY_ON_WIPE

    def time_remaining():
        return (t < abs_cap) if end_on_wipe else (t < max_t)

    while time_remaining():
        obs, _mask_now = env.observe()
        p0_alive = sum(1 for o,u in engine.units if o==0 and u.is_alive())
        p1_alive = sum(1 for o,u in engine.units if o==1 and u.is_alive())
        if p0_alive == 0 or p1_alive == 0:
            break

        substeps = max(1, int(speed * SPEED_MULT))
        for _ in range(substeps):
            wrap_step(dt)
            t += dt

        screen.fill(BG)

        # stores & benches
        p0_store = obs.get('p0_shop', [])
        p1_store = obs.get('p1_shop', [])
        p0_bench = getattr(env.p0, 'bench', [])
        p1_bench = getattr(env.p1, 'bench', [])
        draw_store_row(screen, font_small, font_big, p0_store, owner=0)
        draw_store_row(screen, font_small, font_big, p1_store, owner=1)
        draw_bench_column(screen, font_small, font_big, p0_bench, owner=0,
                          hp=getattr(env.p0, 'base_hp', 10),
                          elixir=getattr(env.p0, 'elixir', 0))
        draw_bench_column(screen, font_small, font_big, p1_bench, owner=1,
                          hp=getattr(env.p1, 'base_hp', 10),
                          elixir=getattr(env.p1, 'elixir', 0))

        # board
        draw_grid(screen)
        for owner, u in engine.units:
            if u.is_alive():
                draw_unit(screen, u, owner)
        for p in engine.projectiles:
            draw_projectile(screen, p)

        # footer status
        bx, by = board_origin()
        draw_text(screen, font_small, f"BATTLE t={t:0.1f}s  Alive P0={p0_alive} P1={p1_alive}  (SPACE pause, 1..5 speed, F ffwd)", bx, by + CELL*BOARD_H + 8)

        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return
                if ev.key == pygame.K_SPACE:
                    paused = True
                    while paused:
                        for ev2 in pygame.event.get():
                            if ev2.type == pygame.KEYDOWN and ev2.key == pygame.K_SPACE:
                                paused = False
                            if ev2.type == pygame.KEYDOWN and ev2.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5):
                                SPEED_MULT = {pygame.K_1:1.0, pygame.K_2:2.0, pygame.K_3:4.0, pygame.K_4:8.0, pygame.K_5:16.0}[ev2.key]
                        pygame.time.Clock().tick(60)
                if ev.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5):
                    SPEED_MULT = {pygame.K_1:1.0, pygame.K_2:2.0, pygame.K_3:4.0, pygame.K_4:8.0, pygame.K_5:16.0}[ev.key]
                if ev.key == pygame.K_f:
                    while time_remaining():
                        p0_alive = sum(1 for o,u in engine.units if o==0 and u.is_alive())
                        p1_alive = sum(1 for o,u in engine.units if o==1 and u.is_alive())
                        if p0_alive == 0 or p1_alive == 0:
                            break
                        wrap_step(dt)
                        t += dt
                    break
        pygame.time.Clock().tick(60)


# ==============================
# Main
# ==============================

def main():
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Merge Tactics – Arena Viewer")
    font_big = pygame.font.SysFont("Menlo,Consolas,monospace", 22)
    font_small = pygame.font.SysFont("Menlo,Consolas,monospace", 18)

    env = MTEnv(seed=42)
    obs, mask = env.reset()
    b0, b1 = GreedyBot(), RandomBot()

    while not env.done and env.round <= rules.MAX_ROUNDS:
        engine = visualize_deploy(screen, font_big, font_small, env, b0, b1)
        if engine is None:
            break
        visualize_battle(screen, font_big, font_small, env, speed=1.0, engine=engine)

    pygame.time.delay(600)
    pygame.quit()

if __name__ == "__main__":
    main()