import os, sys, time, math
import pygame
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from mergetactics.env import MTEnv, BattleEngine, Projectile
from mergetactics.bots import GreedyBot, RandomBot
from mergetactics import rules
from mergetactics.entities import Unit

# ------------------------------
# Basic rendering config
# ------------------------------
CELL = 180              # px per grid cell (larger)
PADDING = 20            # window padding
BOARD_W, BOARD_H = rules.BOARD_COLS, rules.BOARD_ROWS
HUD_H = 180            # extra-tall HUD at the TOP (prevents overlap)

# Board is drawn below the HUD; define its top-left Y
BOARD_Y0 = PADDING + HUD_H

MIN_WINDOW_W = 1200  # enforce a wide HUD panel so bars never overlap
W = max(PADDING*2 + CELL*BOARD_W, MIN_WINDOW_W)
H = BOARD_Y0 + CELL*BOARD_H + PADDING

BG = (18, 18, 24)
GRID = (50, 55, 68)
WHITE = (230, 230, 235)
#
# owners
P0C = (40, 140, 255)    # Player 0 color
P1C = (255, 90, 90)     # Player 1 color

# HUD & bars
HUD_BG = (28, 28, 36)
BAR_BG = (60, 60, 75)
HP_BAR = (120, 230, 120)
ELIXIR_BAR = (140, 120, 255)

HP_BAR_W = 420
HP_BAR_H = 20
ELIXIR_BAR_W = 260
ELIXIR_BAR_H = 14

# Safe defaults if rules module lacks these
SUB_TICK_DT = getattr(rules, "SUB_TICK_DT", 0.1)
MAX_BATTLE_TIME = getattr(rules, "MAX_BATTLE_TIME", 30.0)
ABSOLUTE_BATTLE_TIME_CAP = getattr(rules, "ABSOLUTE_BATTLE_TIME_CAP", 300.0)
END_ONLY_ON_WIPE = getattr(rules, "END_ONLY_ON_WIPE", False)

# ------------------------------
# runtime speed controls
SPEED_MULT = 1.0         # adjustable at runtime with number keys (1..5)
DEPLOY_DELAY_MS_DEFAULT = 250
# troops
ARCHER = rules.ARCHER
TANK = rules.TANK

# ------------------------------
# Helpers
# ------------------------------
def cell_rect(r, c):
    x = PADDING + c * CELL
    y = BOARD_Y0 + r * CELL
    return pygame.Rect(x, y, CELL, CELL)

def pos_to_px(rf, cf):
    """float grid (r,c) -> pixel center"""
    x = PADDING + cf * CELL + CELL/2
    y = BOARD_Y0 + rf * CELL + CELL/2
    return (int(x), int(y))

def draw_grid(surf):
    for r in range(BOARD_H):
        for c in range(BOARD_W):
            pygame.draw.rect(surf, GRID, cell_rect(r,c), width=2, border_radius=8)

def draw_text(surf, font, text, x, y, color=WHITE):
    surf.blit(font.render(text, True, color), (x, y))

# ----------- HUD/bar helpers -----------
def draw_bar(surf, x, y, w, h, frac, fg, bg=BAR_BG, border=2, label=None, font=None, color=WHITE):
    pygame.draw.rect(surf, bg, (x, y, w, h), border_radius=4)
    inner_w = max(0, int(w * max(0.0, min(1.0, frac))))
    pygame.draw.rect(surf, fg, (x, y, inner_w, h), border_radius=4)
    if label and font:
        draw_text(surf, font, label, x + 6, y - 2, color)

def draw_hud(surf, font, env, speed_text=None, mode_text=None):
    # background strip
    pygame.draw.rect(surf, HUD_BG, (0, 0, W, HUD_H))

    # round/turn header
    left_x = 16
    draw_text(surf, font, f"Round {env.round} | Turn {env.turn} | in_battle={env.in_battle}", left_x, 10)

    # move center hints to the bottom rows of the HUD
    center_x = max(16, (W // 2) - 300)
    if speed_text:
        draw_text(surf, font, speed_text, center_x, HUD_H - 48)
    if mode_text:
        draw_text(surf, font, mode_text, center_x, HUD_H - 24)

    # reserve top two lines for centered texts; place player HUD below
    p0_hp = max(0, getattr(env.p0, 'base_hp', 10))
    p1_hp = max(0, getattr(env.p1, 'base_hp', 10))
    hp_max = 10.0
    y1 = 68
    draw_text(surf, font, "P0", left_x, y1)
    draw_bar(surf, left_x + 36, y1 + 2, HP_BAR_W, HP_BAR_H, p0_hp / max(1.0, hp_max), HP_BAR, label="King HP", font=font)

    p0_elix = getattr(env.p0, 'elixir', 0)
    y2 = y1 + 26
    draw_bar(surf, left_x + 36, y2 + 2, ELIXIR_BAR_W, ELIXIR_BAR_H, p0_elix / max(1, rules.START_ELIXIR), ELIXIR_BAR, label=f"Elixir: {p0_elix}", font=font)

    # P1 (right) bars
    right_x = W - (HP_BAR_W + 36 + 16)
    draw_text(surf, font, "P1", right_x, y1)
    draw_bar(surf, right_x + 36, y1 + 2, HP_BAR_W, HP_BAR_H, p1_hp / max(1.0, hp_max), HP_BAR, label="King HP", font=font)

    p1_elix = getattr(env.p1, 'elixir', 0)
    draw_bar(surf, right_x + 36, y2 + 2, ELIXIR_BAR_W, ELIXIR_BAR_H, p1_elix / max(1, rules.START_ELIXIR), ELIXIR_BAR, label=f"Elixir: {p1_elix}", font=font)

def draw_unit(surf, unit, owner):
    # unit.pos is float (r,c)
    cx, cy = pos_to_px(unit.pos[0], unit.pos[1])
    color = P0C if owner == 0 else P1C

    # size based on troop type
    if unit.troop_id == TANK:
        # tank: filled circle
        pygame.draw.circle(surf, color, (cx, cy), int(CELL*0.30))
    else:
        # archer: diamond
        s = int(CELL*0.28)
        pts = [(cx, cy-s), (cx+s, cy), (cx, cy+s), (cx-s, cy)]
        pygame.draw.polygon(surf, color, pts)

    # small star pips
    pip = int(CELL*0.06)
    gap = int(CELL*0.12)
    start_x = cx - gap
    for i in range(unit.star):
        pygame.draw.circle(surf, WHITE, (start_x + i*gap, cy - int(CELL*0.35)), pip)

    # tiny hp bar
    max_hp = rules.BASE_HP[unit.troop_id] * rules.STAR_HP_MUL[unit.star]
    hp_w = int((unit.hp / max_hp) * (CELL*0.6))
    bar_x = cx - int(CELL*0.3)
    bar_y = cy + int(CELL*0.34)
    pygame.draw.rect(surf, (80,80,90), (bar_x, bar_y, int(CELL*0.6), 6), border_radius=3)
    pygame.draw.rect(surf, (80,255,120), (bar_x, bar_y, max(0, hp_w), 6), border_radius=3)

def draw_projectile(surf, p):
    # simple bright bolt
    color = P0C if p.owner == 0 else P1C
    pygame.draw.circle(surf, color, pos_to_px(p.r, p.c), 6)

def build_engine_from_env(env):
    """Mirror what _run_battle does, but keep the Unit instances we can render."""
    units = []
    for pos, u in env.p0.units.items():
        units.append([0, Unit.from_troop(u.troop_id, u.star, (pos[0], pos[1]))])
    for pos, u in env.p1.units.items():
        units.append([1, Unit.from_troop(u.troop_id, u.star, (pos[0], pos[1]))])
    return BattleEngine(units=units)

def nearest_enemy_idx(engine, idx):
    # helper to get current target (for drawing aim-lines if desired)
    return engine.nearest_enemy(idx)

# ------------------------------
# Env API compatibility shim
# ------------------------------
def env_step_with_mask(env, action):
    """Call env.step(action) and always return (obs, mask, reward, done, info).
    Supports both APIs:
      - (obs, reward, done, info) with mask inside info or via observe()
      - (obs, mask)
    """
    ret = env.step(action)
    if isinstance(ret, tuple):
        if len(ret) == 4:
            obs, reward, done, info = ret
            # try to get mask from info; fallback to observe
            mask = info.get("mask") if isinstance(info, dict) else None
            if mask is None:
                _, mask = env.observe()
            return obs, mask, reward, done, info
        if len(ret) == 2:
            obs, mask = ret
            # best-effort defaults
            reward = 0.0
            done = getattr(env, "done", False)
            info = {}
            return obs, mask, reward, done, info
    # Fallback: force observe to avoid crashing
    obs, mask = env.observe()
    return obs, mask, 0.0, getattr(env, "done", False), {}

# ------------------------------
# Deployment visualizer
# ------------------------------
def visualize_deploy(screen, font, env, b0, b1, delay_ms=DEPLOY_DELAY_MS_DEFAULT):
    """Play out the deploy phase with bots, drawing each step and action text.
       Returns a BattleEngine snapshot for the ensuing battle when deploy ends."""
    obs, mask = env.observe()
    action_text = "Start deploy"

    clock = pygame.time.Clock()
    while not (env.p0.actions_left == 0 and env.p1.actions_left == 0):
        # Draw current board (no float positions; just cells from env slots)
        screen.fill(BG)
        draw_grid(screen)

        # draw env board units as static sprites (use integer positions from dict keys)
        for (r,c), u in env.p0.units.items():
            draw_unit(screen, Unit.from_troop(u.troop_id, u.star, (r,c)), 0)
        for (r,c), u in env.p1.units.items():
            draw_unit(screen, Unit.from_troop(u.troop_id, u.star, (r,c)), 1)

        draw_hud(screen, font, env, mode_text=f"Action: {action_text}")
        pygame.draw.line(screen, GRID, (0, BOARD_Y0 - 1), (W, BOARD_Y0 - 1), 1)
        pygame.display.flip()
        # hotkeys to tweak deploy pacing
        for ev in pygame.event.get():
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_MINUS:  # slower
                    delay_ms = min(1000, delay_ms + 50)
                elif ev.key == pygame.K_EQUALS or ev.key == pygame.K_PLUS:  # faster
                    delay_ms = max(0, delay_ms - 50)
                elif ev.key == pygame.K_SPACE:
                    # modal pause loop for DEPLOY view
                    while True:
                        # redraw current frame with PAUSED banner
                        screen.fill(BG)
                        draw_grid(screen)
                        for (r,c), u in env.p0.units.items():
                            draw_unit(screen, Unit.from_troop(u.troop_id, u.star, (r,c)), 0)
                        for (r,c), u in env.p1.units.items():
                            draw_unit(screen, Unit.from_troop(u.troop_id, u.star, (r,c)), 1)
                        draw_hud(screen, font, env, mode_text=f"[PAUSED] Action: {action_text}")
                        pygame.draw.line(screen, GRID, (0, BOARD_Y0 - 1), (W, BOARD_Y0 - 1), 1)
                        pygame.display.flip()
                        got_cmd = False
                        for ev2 in pygame.event.get():
                            if ev2.type == pygame.QUIT:
                                return None
                            if ev2.type == pygame.KEYDOWN:
                                if ev2.key == pygame.K_ESCAPE:
                                    return None
                                if ev2.key == pygame.K_SPACE:
                                    got_cmd = True  # resume
                                if ev2.key == pygame.K_MINUS:
                                    delay_ms = min(1000, delay_ms + 50)
                                if ev2.key == pygame.K_EQUALS or ev2.key == pygame.K_PLUS:
                                    delay_ms = max(0, delay_ms - 50)
                        if got_cmd:
                            break
                        pygame.time.Clock().tick(60)
                elif ev.key == pygame.K_ESCAPE:
                    return None
        clock.tick(60)

        # sleep a bit so you can see state before action
        pygame.time.delay(delay_ms)

        # snapshot units before taking the action (so if this ends deploy, we can visualize the ensuing battle)
        pre_p0_units = {pos: (u.troop_id, u.star) for pos, u in env.p0.units.items()}
        pre_p1_units = {pos: (u.troop_id, u.star) for pos, u in env.p1.units.items()}

        # choose action
        bot = b0 if env.turn == 0 else b1
        action = bot.act(obs, mask)
        action_text = f"{'P0' if env.turn==0 else 'P1'} -> {action[0]} {action[1]}"

        # step env (supports both (obs,mask) and (obs,reward,done,info))
        prev_round = env.round
        obs, mask, reward, done, info = env_step_with_mask(env, action)

        # If deploy just ended (both at 0) **or** the env advanced the round, visualize battle now.
        if (env.p0.actions_left == 0 and env.p1.actions_left == 0) or (env.round > prev_round):
            units = []
            for (r,c), (tid, star) in pre_p0_units.items():
                units.append([0, Unit.from_troop(tid, star, (r, c))])
            for (r,c), (tid, star) in pre_p1_units.items():
                units.append([1, Unit.from_troop(tid, star, (r, c))])
            return BattleEngine(units=units)

    return None

#
# ------------------------------
# Battle visualizer (movement/projectiles)
# ------------------------------
def visualize_battle(screen, font, env, speed=1.0, engine=None):
    """Run/visualize the battle using the same engine as env, with per-substep drawing."""
    engine = engine or build_engine_from_env(env)
    clock = pygame.time.Clock()

    global SPEED_MULT

    # to animate projectiles, we store current pos + velocity derived from remaining time
    # But BattleEngine keeps only 'remaining' seconds and target_idx. For visuals,
    # we will also track px positions for each Projectile.
    # We'll create a parallel list with (r,c, vr, vc) for drawing.
    # For simplicity, we recompute projectile position each frame assuming straight-line
    # to the locked target position at fire time.

    # Monkey-patch: store initial target (r,c) at fire-time for draw
    def wrap_step(dt):
        # Before stepping, capture new projectiles to attach a frozen target point
        before = len(engine.projectiles)
        engine.step(dt)
        after = len(engine.projectiles)
        # Newly added projectiles are at the tail; attach frozen target xy and start xy
        for i in range(before, after):
            p = engine.projectiles[i]
            if 0 <= p.target_idx < len(engine.units):
                tgt = engine.units[p.target_idx][1]
                # freeze start/target for drawing
                p.tr = float(tgt.pos[0])
                p.tc = float(tgt.pos[1])
                p.sr = float(p.r)
                p.sc = float(p.c)
                # remember initial remaining to compute progress
                p._draw_tremain0 = max(1e-6, p.remaining)

        # After stepping, update projectile draw-positions by interpolation
        for p in engine.projectiles:
            if hasattr(p, "_draw_tremain0"):
                frac = 1.0 - (p.remaining / p._draw_tremain0)
                frac = 0.0 if frac < 0.0 else (1.0 if frac > 1.0 else frac)
                # linear interpolate from (sr,sc) to (tr,tc)
                p.r = p.sr + (p.tr - p.sr) * frac
                p.c = p.sc + (p.tc - p.sc) * frac

    # Run loop until one side dies (or time cap, depending on rules)
    t = 0.0
    dt = SUB_TICK_DT
    max_t = MAX_BATTLE_TIME
    abs_cap = ABSOLUTE_BATTLE_TIME_CAP
    end_on_wipe = END_ONLY_ON_WIPE

    def time_remaining():
        return (t < abs_cap) if end_on_wipe else (t < max_t)

    while time_remaining():
        p0_alive = sum(1 for o,u in engine.units if o==0 and u.is_alive())
        p1_alive = sum(1 for o,u in engine.units if o==1 and u.is_alive())
        if p0_alive == 0 or p1_alive == 0:
            break

        # step physics possibly multiple times per frame depending on speed
        substeps = max(1, int(speed * SPEED_MULT))
        for _ in range(substeps):
            wrap_step(dt)
            t += dt

        # draw
        screen.fill(BG)
        draw_grid(screen)

        for owner, u in engine.units:
            if u.is_alive():
                draw_unit(screen, u, owner)

        for p in engine.projectiles:
            draw_projectile(screen, p)

        speed_hint = f"speed x{SPEED_MULT:g}  (1..5 change, SPACE pause, F fast-forward)"
        draw_hud(screen, font, env, speed_text=f"BATTLE t={t:0.1f}s  |  Alive P0={p0_alive} P1={p1_alive}", mode_text=speed_hint)
        pygame.draw.line(screen, GRID, (0, BOARD_Y0 - 1), (W, BOARD_Y0 - 1), 1)
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    return
                # modal pause for BATTLE view
                if ev.key == pygame.K_SPACE:
                    while True:
                        # redraw current frame with PAUSED banner (no stepping)
                        screen.fill(BG)
                        draw_grid(screen)
                        for owner, u in engine.units:
                            if u.is_alive():
                                draw_unit(screen, u, owner)
                        for p in engine.projectiles:
                            draw_projectile(screen, p)
                        speed_hint2 = f"speed x{SPEED_MULT:g}  (1..5 change, SPACE resume, F fast-forward)"
                        draw_hud(screen, font, env, speed_text=f"BATTLE t={t:0.1f}s  |  Alive P0={p0_alive} P1={p1_alive}", mode_text=f'[PAUSED]  {speed_hint2}')
                        pygame.draw.line(screen, GRID, (0, BOARD_Y0 - 1), (W, BOARD_Y0 - 1), 1)
                        pygame.display.flip()
                        resume = False
                        for ev2 in pygame.event.get():
                            if ev2.type == pygame.QUIT:
                                return
                            if ev2.type == pygame.KEYDOWN:
                                if ev2.key == pygame.K_ESCAPE:
                                    return
                                if ev2.key == pygame.K_SPACE:
                                    resume = True
                                # allow speed changes while paused
                                if ev2.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5):
                                    SPEED_MULT = {pygame.K_1:1.0, pygame.K_2:2.0, pygame.K_3:4.0, pygame.K_4:8.0, pygame.K_5:16.0}[ev2.key]
                        if resume:
                            break
                        pygame.time.Clock().tick(60)
                # speed presets 1..5 => x1,x2,x4,x8,x16
                if ev.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5):
                    SPEED_MULT = {pygame.K_1:1.0, pygame.K_2:2.0, pygame.K_3:4.0, pygame.K_4:8.0, pygame.K_5:16.0}[ev.key]
                # fast-forward (no draw) until battle ends
                if ev.key == pygame.K_f:
                    # run a tight loop without rendering
                    while time_remaining():
                        p0_alive = sum(1 for o,u in engine.units if o==0 and u.is_alive())
                        p1_alive = sum(1 for o,u in engine.units if o==1 and u.is_alive())
                        if p0_alive == 0 or p1_alive == 0:
                            break
                        wrap_step(dt)
                        t += dt
                    # after fast-forward, break draw loop so function can finish
                    break

        pygame.time.Clock().tick(60)

    # Apply damage like env does (for display only; env will also do this in step run)
    p0_alive = sum(1 for o,u in engine.units if o==0 and u.is_alive())
    p1_alive = sum(1 for o,u in engine.units if o==1 and u.is_alive())
    winner = -1
    if p0_alive>0 and p1_alive==0: winner = 0
    elif p1_alive>0 and p0_alive==0: winner = 1

# ------------------------------
# Main: demo one full round
# ------------------------------
def main():
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Merge Tactics – Mini Arena Viewer")
    font = pygame.font.SysFont("Menlo,Consolas,monospace", 22)

    env = MTEnv(seed=42)
    obs, mask = env.reset()
    b0, b1 = GreedyBot(), RandomBot()

    # Play multiple rounds until the game ends
    while not env.done and env.round <= rules.MAX_ROUNDS:
        engine = visualize_deploy(screen, font, env, b0, b1)
        if engine is None:
            break
        visualize_battle(screen, font, env, speed=1.0, engine=engine)

    pygame.time.delay(900)
    pygame.quit()

if __name__ == "__main__":
    main()