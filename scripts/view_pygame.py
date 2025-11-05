import os, sys, time, math, re
import pygame
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from mergetactics.env import MTEnv, BattleEngine, Projectile, _unit_make
from mergetactics.bots import GreedyBot, RandomBot
from mergetactics import rules
from mergetactics.entities import Unit

# Force-enable projectiles in the viewer (env respects rules.USE_PROJECTILES)
try:
    setattr(rules, "USE_PROJECTILES", True)
except Exception:
    pass

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
DEFAULT_TRAIT_COLORS = {
    'Undead': (120, 240, 160),
    'Ranger': (130, 170, 255),
    'Goblin': (110, 210, 110),
    'Royal': (245, 210, 90),
    'Avenger': (250, 120, 160),
}
TRAIT_COLORS = {**DEFAULT_TRAIT_COLORS, **getattr(rules, "TRAIT_COLORS", {})}
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
BATTLE_BASE_SPEED = 3.0        # additional substeps per frame for faster battles
PROJECTILE_SPEED_SCALE = 0.75  # viewer-only projectile slow-down (1.0 = stock)

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
    """Map continuous odd‑r (row, col) to pixel center smoothly.
    We linearly interpolate the half‑column offset between neighbouring rows
    so moving across rows doesn’t cause jumps (the classic odd‑r discontinuity).
    """
    bx, by = board_origin()
    r = float(rf); c = float(cf)
    r0 = math.floor(r)
    r1 = r0 + 1
    alpha = r - r0  # blend toward next row
    # odd‑r offset (0 for even rows, 0.5 for odd rows), blended across rows
    off0 = 0.5 if (r0 & 1) else 0.0
    off1 = 0.5 if (r1 & 1) else 0.0
    off = (1.0 - alpha) * off0 + alpha * off1
    x = bx + HEX_W * (c + off) + HEX_W * 0.75
    y = by + HEX_VSTEP * r + HEX_R * 1.1
    return int(x), int(y)

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

def _color_for_trait(name):
    if not name:
        return None
    candidates = [name, name.lower(), name.title(), re.sub(r"\s+cards$", "", name, flags=re.I).strip()]
    candidates += [c.lower() for c in candidates]
    for key in candidates:
        if key in TRAIT_COLORS:
            return TRAIT_COLORS[key]
    return None

def _primary_trait_color(tid):
    for trait in _traits_for_tid(tid):
        color = _color_for_trait(trait)
        if color:
            return color
    return None

def _blend_color(base, overlay, alpha=0.5):
    ax = max(0.0, min(1.0, alpha))
    return tuple(int((1-ax)*base[i] + ax*overlay[i]) for i in range(3))

def _cost_for_tid(tid):
    try:
        catalog = getattr(rules, 'CARD_CATALOG', None)
        card = None
        if isinstance(catalog, (list, tuple)) and 0 <= tid < len(catalog):
            card = catalog[tid]
        elif isinstance(catalog, dict):
            card = catalog.get(tid)
        if card is not None:
            return int(rules.elixir_cost_for(card))
    except Exception:
        pass
    return getattr(rules, "CARD_COST_DEFAULT", 3)


def _name_for_tid(tid):
    names = getattr(rules, 'TROOP_NAMES', {})
    return names.get(tid, f"ID{tid}")


def card_chip(surf, rect, tid, font_small, font_big):
    pygame.draw.rect(surf, DEFAULT_CARD_BG, rect, border_radius=10)
    pygame.draw.rect(surf, TILE_BORDER, rect, width=2, border_radius=10)

    # Trait squares in top-left corner
    traits = _traits_for_tid(tid)
    trait_colors = [_color_for_trait(t) for t in traits if _color_for_trait(t)]
    inner = rect.inflate(-12, -12)
    if trait_colors and inner.w > 0 and inner.h > 0:
        count = min(2, len(trait_colors))
        box_size = max(6, min(10, inner.h // 7))
        spacing = max(2, min(5, inner.w // 20))
        total_width = count * box_size + (count - 1) * spacing
        start_x = inner.x + 3
        if start_x + total_width > inner.right - 3:
            start_x = inner.right - total_width - 3
        y = inner.y + 3
        pygame.draw.rect(surf, DEFAULT_CARD_BG, (start_x - 2, y - 2, total_width + 4, box_size + 4), border_radius=3)
        for idx, color in enumerate(trait_colors[:count]):
            box = pygame.Rect(start_x + idx * (box_size + spacing), y, box_size, box_size)
            pygame.draw.rect(surf, color, box, border_radius=2)

    # Trait ribbons (up to two)
    sw = max(8, rect.w // 8)
    x0 = rect.x + 6
    for k, t in enumerate(traits[:2]):
        c = _color_for_trait(t) or DEFAULT_CARD_BG
        rr = pygame.Rect(x0 + k*(sw+4), rect.y + 6, sw, 16)
        pygame.draw.rect(surf, c, rr, border_radius=3)

    # Name label
    nm = _name_for_tid(tid)
    label = font_small.render(nm, True, DEFAULT_CARD_FG)
    # clip to tile width
    clip = surf.get_clip()
    surf.set_clip(rect.inflate(-10, -10))
    surf.blit(label, (rect.x + 8, rect.y + rect.h//2 - label.get_height()//2))
    surf.set_clip(clip)


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
    slot_h = 86
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
            # Cost label bottom-right
            cost = _cost_for_tid(int(tid))
            label = font_small.render(f"{cost} elixir", True, SUBTLE)
            surf.blit(label, (rect.right - label.get_width() - 8, rect.bottom - label.get_height() - 6))


def draw_bench_column(surf, font_small, font_big, items, owner=0, hp=None, elixir=None):
    # items: list of troop_ids (or data)
    x = 0 if owner==0 else W - SIDE_W
    bg = pygame.Rect(x, 0, SIDE_W, H)
    pygame.draw.rect(surf, (24,24,32), bg)
    pygame.draw.rect(surf, (44,44,58), bg, width=1)

    title = f"P{owner} Bench"
    draw_text(surf, font_big, title, x + 12, 10)

    # Show King HP as a bar + number, and Elixir as a number (no bar)
    if hp is None:
        hp = 10
    if elixir is None:
        elixir = 0

    # Determine max king HP if exposed in rules, else default to 10
    king_hp_max = getattr(rules, 'KING_HP_MAX', 10)
    hp_frac = float(hp) / max(1.0, float(king_hp_max))

    # King HP bar
    hp_bar_x = x + 12
    hp_bar_w = SIDE_W - 24
    hp_bar_y = 40
    draw_bar(surf, hp_bar_x, hp_bar_y, hp_bar_w, 12, hp_frac, HP_BAR)

    # King HP number overlay (e.g., "HP: 8/10")
    hp_text = f"HP: {int(hp)}/{int(king_hp_max)}"
    txt = font_small.render(hp_text, True, WHITE)
    surf.blit(txt, (hp_bar_x, hp_bar_y - txt.get_height() - 2))

    # Elixir as a number (no bar)
    elixir_text = f"Elixir: {int(elixir)}"
    etxt = font_small.render(elixir_text, True, SUBTLE)
    surf.blit(etxt, (x + 12, 58))

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
    """
    Build a BattleEngine snapshot from the deploy state without losing
    catalog-derived fields (range, projectile speed, etc.).
    We (re)bind Unit to the active catalog/level and prefer to clone the
    existing Unit objects when possible.
    """
    # 1) Rebind Unit to the same catalog/level that env uses (if present)
    _rebind_unit_catalog(env)

    def _clone_or_rebuild(src_u, pos):
        # Prefer a simple field-wise clone if constructor allows (hp, star, pos preserved)
        try:
            # Some versions expose a copy/clone; use it if available.
            if hasattr(src_u, "clone"):
                v = src_u.clone()
                v.pos = (float(pos[0]), float(pos[1]))
                base_hp = float(getattr(v, "_viewer_max_hp", getattr(v, "hp", 1.0)))
                setattr(v, "_viewer_max_hp", base_hp)
                return v
        except Exception:
            pass
        # Fallback: rebuild from catalog/card id
        cid = getattr(src_u, "card_id", getattr(src_u, "troop_id", 0))
        star = getattr(src_u, "star", 1)
        try:
            v = Unit.from_card(card_id=cid, star=star, pos=(pos[0], pos[1]))
        except Exception:
            # very old fallback: from_troop(troop_id=..., ...)
            try:
                v = Unit.from_troop(troop_id=cid, star=star, pos=(pos[0], pos[1]))
            except Exception:
                # Last resort: shallow shim with minimal attributes
                v = Unit.from_card(card_id=cid, star=star, pos=(pos[0], pos[1]))
        base_hp = float(getattr(v, "hp", 1.0))
        # carry over current HP if the deploy phase modified it (should be full in most cases)
        try:
            if hasattr(src_u, "hp"):
                v.hp = float(src_u.hp)
        except Exception:
            pass
        _apply_projectile_speed_scale(v)
        setattr(v, "_viewer_max_hp", base_hp)
        return v

    units = []
    for pos, u in env.p0.units.items():
        units.append([0, _clone_or_rebuild(u, pos)])
    for pos, u in env.p1.units.items():
        units.append([1, _clone_or_rebuild(u, pos)])
    return BattleEngine(units=units)


def build_engine_from_seed(env):
    """Rebuild a BattleEngine using env._battle_replay_seed if available."""
    seed = getattr(env, "_battle_replay_seed", None)
    if not seed:
        return None
    _rebind_unit_catalog(env)
    units = []
    for entry in seed:
        try:
            owner = int(entry.get("owner", 0))
            cid = int(entry.get("card_id"))
        except Exception:
            continue
        star = int(entry.get("star", 1))
        pos = entry.get("pos", (0, 0))
        if not isinstance(pos, (tuple, list)) or len(pos) != 2:
            pos = (0, 0)
        r, c = float(pos[0]), float(pos[1])
        unit = _unit_make(card_or_troop_id=cid, star=star, pos=(r, c))
        base_hp = float(getattr(unit, "hp", 1.0))
        hp_override = entry.get("hp")
        if hp_override is not None:
            try:
                unit.hp = float(hp_override)
            except Exception:
                pass
        _apply_projectile_speed_scale(unit)
        setattr(unit, "_viewer_max_hp", base_hp)
        units.append([owner, unit])
    return BattleEngine(units=units)


def _rebind_unit_catalog(env):
    """Ensure Unit has the same catalog/level bindings as the env."""
    try:
        catalog = getattr(env, "catalog", None)
        level = getattr(env, "unit_level", None)
        if catalog is not None and hasattr(Unit, "bind_catalog"):
            if level is not None:
                Unit.bind_catalog(catalog, level=level)
            else:
                Unit.bind_catalog(catalog)
    except TypeError:
        try:
            Unit.bind_catalog(catalog)
        except Exception:
            pass
    except Exception:
        pass


def _snapshot_units(units_dict):
    """Capture card_id, star, and hp for each board position.
    Dead units (hp <= 0) are ignored so battles don't start in a wiped state.
    """
    snap = {}
    for (r, c), u in units_dict.items():
        cid = getattr(u, "card_id", getattr(u, "troop_id", 0))
        star = int(getattr(u, "star", 1))
        try:
            hp = float(getattr(u, "hp", 1.0))
        except Exception:
            hp = 1.0
        if hp <= 0.0:
            continue
        snap[(int(r), int(c))] = {"id": int(cid), "star": star, "hp": hp}
    return snap


def _normalize_bench(items):
    """Return a list of (card_id, star) tuples from arbitrary bench entries."""
    out = []
    for itm in items:
        if isinstance(itm, dict):
            cid = itm.get("card_id", itm.get("troop_id", itm.get("id", 0)))
            star = itm.get("star", itm.get("level", 1))
        elif isinstance(itm, (list, tuple)):
            cid = itm[0] if itm else 0
            star = itm[1] if len(itm) > 1 else 1
        else:
            cid = itm
            star = 1
        out.append((int(cid), int(star)))
    return out


def _apply_projectile_speed_scale(unit):
    """Slow projectiles for viewer visualization only."""
    scale = PROJECTILE_SPEED_SCALE
    if scale == 1.0:
        return
    if scale <= 0.0:
        return
    if getattr(unit, "_viewer_proj_scaled", False):
        return
    try:
        attr = getattr(unit, "projectile_speed", None)
    except Exception:
        return
    if attr is None:
        return

    try:
        if callable(attr):
            def _scaled(attr=attr, scale=scale):
                try:
                    val = attr()
                except Exception:
                    return 0.0
                try:
                    val_f = float(val)
                except Exception:
                    return val
                if val_f <= 0.0:
                    return val_f
                return val_f * scale
            setattr(unit, "projectile_speed", _scaled)
        else:
            val = float(attr)
            if val <= 0.0:
                return
            setattr(unit, "projectile_speed", val * scale)
        setattr(unit, "_viewer_proj_scaled", True)
    except Exception:
        pass


def _apply_action_to_snapshot(snapshot, action, actor):
    """Mutate snapshot in-place to reflect the deploy action that just executed."""
    atype, args = action
    player_units = snapshot["units"][actor]
    benches = snapshot["benches"][actor]
    shops = snapshot["shops"][actor]
    back_row = 0 if actor == 0 else rules.BOARD_ROWS - 1

    def _pos_tuple(pos):
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            return (int(pos[0]), int(pos[1]))
        return (int(pos), 0)

    if atype == "BUY_PLACE":
        si, col = args
        if 0 <= si < len(shops):
            cid = shops[si]
            pos = (back_row, int(col))
            player_units[pos] = {"id": int(cid), "star": 1, "hp": None}
    elif atype == "PLACE_FROM_BENCH":
        bi, col = args
        if 0 <= bi < len(benches):
            cid, star = benches[bi]
            pos = (back_row, int(col))
            player_units[pos] = {"id": int(cid), "star": int(star), "hp": None}
    elif atype == "SELL":
        (pos,) = args
        player_units.pop(_pos_tuple(pos), None)
    elif atype == "MERGE":
        p1, p2 = args
        p1 = _pos_tuple(p1)
        p2 = _pos_tuple(p2)
        u1 = player_units.get(p1)
        u2 = player_units.get(p2)
        if u1 and u2 and u1["id"] == u2["id"]:
            player_units[p1] = {"id": int(u1["id"]), "star": int(u1["star"]) + 1, "hp": None}
            player_units.pop(p2, None)
    # END or unknown actions do not alter board layout


def build_engine_from_snapshot(env, snapshot, action, actor):
    """Construct a BattleEngine from the deploy snapshot and the last action."""
    _rebind_unit_catalog(env)
    _apply_action_to_snapshot(snapshot, action, actor)
    units = []
    for owner in (0, 1):
        for pos, data in snapshot["units"][owner].items():
            r, c = pos
            cid = data["id"]
            star = data["star"]
            unit = _unit_make(card_or_troop_id=cid, star=star, pos=(r, c))
            base_hp = float(getattr(unit, "hp", 1.0))
            if data.get("hp") is not None:
                try:
                    unit.hp = float(data["hp"])
                except Exception:
                    pass
            _apply_projectile_speed_scale(unit)
            setattr(unit, "_viewer_max_hp", base_hp)
            units.append([owner, unit])
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

    # Shape: melee = circle, ranged = diamond.
    # Consider a unit "ranged" if it either has projectile_speed > 0
    # OR its range (in tiles) is >= 2. We handle both callables and raw values,
    # and also dict-like values from the scraper (e.g., {"value": 3, "unit": "tiles"}).
    def _num(x):
        try:
            if isinstance(x, dict) and "value" in x:
                return float(x["value"])
            return float(x)
        except Exception:
            return 0.0

    def _val(attr, default):
        try:
            v = getattr(unit, attr, default)
            return v() if callable(v) else v
        except Exception:
            return default

    rng_tiles = _num(_val("range", 1))
    proj_speed = _num(_val("projectile_speed", 0))
    is_ranged = (proj_speed > 0.0) or (rng_tiles >= 2.0)
    if not is_ranged:
        pygame.draw.circle(surf, color, (cx, cy), int(HEX_R * 0.71))
    else:
        s = int(HEX_R * 0.66)
        pts = [(cx, cy-s), (cx+s, cy), (cx, cy+s), (cx-s, cy)]
        pygame.draw.polygon(surf, color, pts)

    # Show unit name above icon
    if font_small is not None:
        nm = rules.TROOP_NAMES.get(getattr(unit, 'card_id', getattr(unit, 'troop_id', -1)), "")
        if nm:
            name_label = font_small.render(nm, True, SUBTLE)
            surf.blit(name_label, (cx - name_label.get_width()//2, cy - int(HEX_R*1.25)))

    # star pips
    pip = int(HEX_R * 0.14)
    gap = int(HEX_R * 0.32)
    start_x = cx - gap
    for i in range(int(getattr(unit, 'star', 1))):
        pygame.draw.circle(surf, WHITE, (start_x + i*gap, cy - int(HEX_R * 0.95)), pip)

    # hp bar
    max_hp = getattr(unit, "_viewer_max_hp", None)
    if max_hp is None:
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
    if ratio < 0.0:
        ratio = 0.0
    elif ratio > 1.0:
        ratio = 1.0
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

        # footer deploy hint centered under board
        bx, by = board_origin()
        draw_text(screen, font_small, f"Action: {action_text}   (± to change speed, SPACE pause)", bx, by + int(BOARD_PIXEL_H) + 8)

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

        # Snapshot full deploy state so we can rebuild the battle board if this action ends deploy.
        snapshot = {
            "units": {
                0: _snapshot_units(env.p0.units),
                1: _snapshot_units(env.p1.units),
            },
            "shops": {
                0: list(getattr(env.p0, 'shop', [])),
                1: list(getattr(env.p1, 'shop', [])),
            },
            "benches": {
                0: _normalize_bench(getattr(env.p0, 'bench', [])),
                1: _normalize_bench(getattr(env.p1, 'bench', [])),
            },
        }

        # choose & step
        bot = b0 if env.turn == 0 else b1
        action = bot.act(obs, mask)
        action_text = f"P{env.turn} -> {action[0]} {action[1]}"
        # Immediate feedback of chosen action in HUD
        screen.fill(BG)
        draw_store_row(screen, font_small, font_big, obs.get('p0_shop', []), owner=0)
        draw_store_row(screen, font_small, font_big, obs.get('p1_shop', []), owner=1)
        draw_bench_column(screen, font_small, font_big, getattr(env.p0, 'bench', []), owner=0,
                          hp=getattr(env.p0, 'base_hp', 10), elixir=getattr(env.p0, 'elixir', 0))
        draw_bench_column(screen, font_small, font_big, getattr(env.p1, 'bench', []), owner=1,
                          hp=getattr(env.p1, 'base_hp', 10), elixir=getattr(env.p1, 'elixir', 0))
        draw_grid(screen)
        for (r,c), u in env.p0.units.items():
            draw_unit(screen, u, 0, font_small)
        for (r,c), u in env.p1.units.items():
            draw_unit(screen, u, 1, font_small)
        bx, by = board_origin()
        draw_text(screen, font_small, f"Action: {action_text}   (± to change speed, SPACE pause)", bx, by + int(BOARD_PIXEL_H) + 8)
        pygame.display.flip()
        prev_round = env.round
        actor = env.turn
        obs, mask, reward, done, info = env_step_with_mask(env, action)

        if env.round > prev_round:
            seeded = build_engine_from_seed(env)
            if seeded is not None:
                return seeded
            return build_engine_from_snapshot(env, snapshot, action, actor)

        if env.p0.actions_left == 0 and env.p1.actions_left == 0:
            seeded = build_engine_from_seed(env)
            if seeded is not None:
                return seeded
            return build_engine_from_snapshot(env, snapshot, action, actor)

    return None


# ==============================
# Battle visualizer
# ==============================

def visualize_battle(screen, font_big, font_small, env, speed=1.0, engine=None):
    engine = engine or build_engine_from_env(env)
    clock = pygame.time.Clock()
    global SPEED_MULT

    def wrap_step(dt):
        # Step the engine; ensure projectiles are on for rendering
        try:
            setattr(rules, "USE_PROJECTILES", True)
        except Exception:
            pass
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

        substeps = max(1, int(speed * SPEED_MULT * BATTLE_BASE_SPEED))
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
                draw_unit(screen, u, owner, font_small)
        for p in engine.projectiles:
            draw_projectile(screen, p)

        # footer status
        bx, by = board_origin()
        draw_text(screen, font_small, f"BATTLE t={t:0.1f}s  Alive P0={p0_alive} P1={p1_alive}  (SPACE pause, 1..5 speed, F ffwd)", bx, by + int(BOARD_PIXEL_H) + 8)

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
