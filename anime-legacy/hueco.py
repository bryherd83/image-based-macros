"""Hueco Mundo (Soul Society's purple key in the Teleport menu -> Create -> Play).

Inside: a fixed, north-up map of one arena (a light lavender disc, top right). Each wave
"awakens" a few spots - red skulls on the map - with a group of enemies at each. Walk to the
nearest skull, stay until its group is dead (the skull turns into a grey check), go on to the next.
When every spot is cleared the game teleports you back to spawn (the black-and-gold diamond in the
middle of the map) and starts the next wave. Every 5 waves there's a boss (one skull), and after
waves 5 / 10 a "CHOOSE A CARD" vote (keys 1 / 2 / 3). The macro leaves after hueco_leave_after
(10) waves.

Movement works like the dungeon's: your white arrow on the map shows where the CAMERA looks
(arrow_is_camera), so it turns the camera toward the skull with a right-mouse drag and walks with
W (the way a mount moves well). Pressing Spawn is used when walking back from spawn is quicker.
Not moving although W is held (a rock in the way) = jump, then step around it.

Everything that reads the screen takes a BGR frame of the 1920x1080 client area, so it can be
tested on screenshots (test_hueco.py).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

import hud
import minimap as mm
from dungeon import keys_for

MAP_R = 102                     # read radius of the disc: out to its blue rim (a skull by the
                                # S badge sat at 91 px and wasn't seen: the run froze, 11-01 18:12)
ARROW_EXTRA = 10                # your arrow is read this much further out: it sticks out past MAP_R
                                # when you walk round a skull by the rim (lost at 94+ px, Blayne 11-01)
SPAWN_COST_SEC = 2.5            # what pressing Spawn costs, in seconds of walking
CENTER_PX = 1.5                 # "in the middle of the skull": this close (map px)
ARRIVE_PX = 4.0                 # at a skull when this close (map px at the default zoom)
CARD_X = (570, 960, 1350)       # the three cards of the "CHOOSE A CARD" screen (1920 px)


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


# ======================= what's on screen =======================
def _disc(frame):
    return hud.minimap_crop(frame, MAP_R)


def lavender_share(frame) -> float:
    c = _disc(frame)
    if c is None or c.size == 0:
        return 0.0
    N = c.shape[0]
    R = (N - 1) // 2
    sub = c[::3, ::3].astype(np.int16)
    yy, xx = np.mgrid[0:N:3, 0:N:3]
    ins = (xx - R) ** 2 + (yy - R) ** 2 <= R * R
    b, g, r = sub[..., 0], sub[..., 1], sub[..., 2]
    lav = (b > 200) & (r > 170) & (g > 170) & (b - r > 8)
    return float((lav & ins).sum() / max(1, ins.sum()))


def is_hueco(frame, castle=None) -> bool:
    """In a Hueco Mundo run: its 4-box top panel (ENEMIES / WAVE / TIME / SPOTS: the castle icon
    sits at x ~828, where Defense has it too - Defense has a HEALTH heart instead of SPOTS) and the
    light lavender map with the N/S badges (dungeons have a dark navy one, trials none)."""
    if frame is None:
        return False
    cx = hud.castle_x(frame) if castle is None else castle
    if cx is None or abs(cx - 828) > 8:
        return False
    return lavender_share(frame) > 0.45 and hud.compass_letters(frame)


def card_screen(frame, tpl) -> bool:
    """The "CHOOSE A CARD" vote between waves."""
    return frame is not None and tpl.find(frame, "hmcards", min_frac=0.9) is not None


def _card_kinds(frame):
    """'risk' (red RISK & REWARD) or 'buff' (gold) for each of the three cards, from the colour
    of the card's frame beside its picture (gold: green ~0.8 of red, red cards ~0.4)."""
    sx, sy = hud.map_scale(frame)
    out = []
    for x in CARD_X:
        px = []
        for dx in (-150, 150):
            x0, y0 = round((x + dx) * sx), round(450 * sy)
            px.append(frame[y0 - 8:y0 + 8, x0 - 4:x0 + 4].reshape(-1, 3).astype(float))
        p = np.vstack(px)
        b, g, r = p.mean(axis=0) if p.size else (0, 0, 0)
        out.append("buff" if g >= 0.6 * r else "risk")
    return out


def card_pictures(folder=hud.ASSETS):
    """Card title pictures in priority order: assets/hmcard_1_*.png first, then hmcard_2_*.png...
    (1 = "50%+ more mobs", 2 = drops, e.g. "Espada Challenge": +1 drop roll). Add a picture of a
    card's title plate there to have it picked first."""
    import glob, os
    out = []
    for p in sorted(glob.glob(os.path.join(folder, "hmcard_*.png"))):
        im = cv2.imread(p, cv2.IMREAD_COLOR)
        if im is not None:
            out.append((os.path.basename(p), im))
    return out


def pick_card(frame, pictures=()):
    """Which card to vote for (1-3) and why: a card from the priority list (more mobs, then drops),
    else a red RISK & REWARD card (more enemies / bosses = more drops), else card 1."""
    sx, sy = hud.map_scale(frame)
    for name, tpl in pictures:
        th, tw = tpl.shape[:2]
        for i, x in enumerate(CARD_X, start=1):
            x0, x1 = max(0, round((x - 200) * sx)), round((x + 200) * sx)
            y0, y1 = round(540 * sy), round(620 * sy)
            sub = frame[y0:y1, x0:x1]
            if sub.shape[0] < th or sub.shape[1] < tw:
                continue
            res = cv2.matchTemplate(sub, tpl, cv2.TM_SQDIFF)
            _, _, loc, _ = cv2.minMaxLoc(res)
            patch = sub[loc[1]:loc[1] + th, loc[0]:loc[0] + tw].astype(np.int16)
            ok = (np.abs(patch - tpl.astype(np.int16)).max(axis=2) <= 70).mean()
            if ok >= 0.9:
                return i, name.rsplit(".", 1)[0]
    kinds = _card_kinds(frame)
    if "risk" in kinds:
        return kinds.index("risk") + 1, "risk & reward"
    return 1, "first card"


# ---- your arrow, found by its shape: a white arrow with a dark outline 2-3 px out ----
# (on a skull its white merges with the skull's white face into one blob, so going by the size of
# white blobs lost you every time you walked onto a skull: "can't see you on the map", 11-01)
_ARROW_SHAPES = None


def _arrow_shapes():
    import minimap as _mm
    pts = _mm._ARROW_PTS.astype(float)
    pts = pts - pts.mean(axis=0)
    out = []
    for k in range(120):
        th = math.radians(k * 3)
        cs, sn = math.cos(th), math.sin(th)
        fill = {(int(round(x * cs - y * sn)), int(round(x * sn + y * cs))) for x, y in pts}
        near1 = {(x + i, y + j) for x, y in fill for i in range(-1, 2) for j in range(-1, 2)}
        near3 = {(x + i, y + j) for x, y in fill for i in range(-3, 4) for j in range(-3, 4)}
        band = near3 - near1
        out.append((np.array(sorted(fill)), np.array(sorted(band))))
    return out


def find_arrow(c, R, sy, prev=None):
    """(x, y, angle) of your arrow in the disc crop `c` (px from its centre, before scaling), or
    None. Looks at every white blob big enough to hold the arrow (also merged with a skull face)
    and keeps the spot where an arrow shape is white inside and dark around."""
    global _ARROW_SHAPES
    if _ARROW_SHAPES is None:
        _ARROW_SHAPES = _arrow_shapes()
    N = c.shape[0]
    mn, mx = c.min(axis=2), c.max(axis=2)
    yy, xx = np.mgrid[0:N, 0:N]
    # (only on the disc: past its rim is the game world, which can be white snow)
    ins = (xx - R) ** 2 + (yy - R) ** 2 <= ((MAP_R + 2) * sy) ** 2
    white = ((mn > 235) & ins).astype(np.float32)
    dark = (mx < 160).astype(np.float32)        # the outline is black to mid grey
    n, _, st, _ = cv2.connectedComponentsWithStats(white.astype(np.uint8), connectivity=8)
    pos = []
    for i in range(1, n):
        x, y, w, h, a = (int(v) for v in st[i])
        if a < 60 * sy * sy or a > 700 * sy * sy:
            continue
        for py in range(max(6, y - 2), min(N - 6, y + h + 2)):
            for px in range(max(6, x - 2), min(N - 6, x + w + 2)):
                if white[py, px]:
                    pos.append((px, py))
    if not pos:
        return None
    P = np.array(pos)
    best = None
    pad = 8
    W2 = np.pad(white, pad)
    D2 = np.pad(dark, pad)
    Wn = N + 2 * pad
    base = (P[:, 1] + pad) * Wn + (P[:, 0] + pad)
    wf, df = W2.ravel(), D2.ravel()
    for k, (fill, band) in enumerate(_ARROW_SHAPES):
        fi = fill[:, 1] * Wn + fill[:, 0]
        bi = band[:, 1] * Wn + band[:, 0]
        hit = wf[base[:, None] + fi[None, :]].mean(axis=1)
        ring = df[base[:, None] + bi[None, :]].mean(axis=1)
        ring_white = wf[base[:, None] + bi[None, :]].mean(axis=1)
        sc = hit + 0.8 * ring
        # white inside, an outline round it (black to grey; partly hidden on a skull: >= 0.3) and
        # no white just outside (an arrow-shaped bit of a bigger white shape - the gate - has)
        sc[(hit < 0.85) | (ring < 0.3) | (ring_white > 0.12)] = -1
        j = int(sc.argmax())
        if sc[j] > 0 and (best is None or sc[j] > best[0]):
            best = (float(sc[j]), int(P[j, 0]), int(P[j, 1]), k)
    if best is None:
        return None
    _, px, py, k = best
    return px, py, wrap(math.radians(k * 3 - 90))


@dataclass
class HMap:
    player: tuple | None            # (x, y) map px from the disc centre, east / south +
    arrow: float | None             # which way the arrow points (radians, 0 = east, +pi/2 = south)
    skulls: list = field(default_factory=list)   # [(x, y), ...]
    spawn: tuple = (0.0, 0.0)


def read_map(frame, prev=None) -> HMap | None:
    """Skulls, spawn and you on the Hueco Mundo map. `prev` = your last position (picks the right
    arrow if two white shapes look like one)."""
    c = _disc(frame)
    if c is None or c.size == 0:
        return None
    N = c.shape[0]
    R = (N - 1) // 2
    sx, sy = hud.map_scale(frame)
    ci = c.astype(np.int16)
    b, g, r = ci[..., 0], ci[..., 1], ci[..., 2]
    yy, xx = np.mgrid[0:N, 0:N]
    ins = (xx - R) ** 2 + (yy - R) ** 2 <= (R - 1) ** 2
    red = (r > 190) & (g < 90) & (b < 120) & ins
    white = (ci.min(axis=2) > 235) & ins
    # red skull circles (the white skull inside splits nothing: the circle is one ring)
    skulls = []

    dark = ci.max(axis=2) < 70

    def comps(mask):
        out = []
        n, _, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
        for i in range(1, n):
            x, y, w, h, a = (int(v) for v in st[i])
            if not (a >= 40 * sy * sy and 12 * sy <= w <= 30 * sy):
                continue
            # the exact centre: the middle of the skull's dark outline ring (a whole circle; the
            # red inside isn't - its top is lighter, so the red alone put it ~3 px too far south)
            cx, cy = x + (w - 1) / 2, y + (h - 1) / 2 - 1
            for _ in range(2):          # (twice: the second time around the better centre)
                rr0, rr1 = 8 * sy, 15 * sy
                xa, xb = max(0, int(cx - rr1)), min(N, int(cx + rr1) + 1)
                ya, yb = max(0, int(cy - rr1)), min(N, int(cy + rr1) + 1)
                yy2, xx2 = np.mgrid[ya:yb, xa:xb]
                d2 = (xx2 - cx) ** 2 + (yy2 - cy) ** 2
                ring = dark[ya:yb, xa:xb] & (d2 >= rr0 * rr0) & (d2 <= rr1 * rr1)
                if ring.sum() < 25 * sy:
                    break
                cx, cy = float(xx2[ring].mean()), float(yy2[ring].mean())
            out.append(((cx - R) / sy, (cy - R) / sy))
        return out
    skulls = comps(red)
    # standing on a skull, its white face and your arrow cut the red circle in two halves, each
    # too small to count (Blayne 11-01 17:59: "no spots left" with 1/6 to go): close the gaps
    # and take what that adds (only that: closing can also join a skull to red bits nearby)
    red_c = cv2.morphologyEx(red.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8)) & ins
    for q in comps(red_c):
        if all(math.hypot(q[0] - k[0], q[1] - k[1]) > 8 for k in skulls):
            skulls.append(q)
    # a skull on the map's edge is cut off (only ~35-65 red px, its face can split them), too small
    # to count: "no spots left" with 2/3 to go (11-02 08:10). Nothing else red is out there. The
    # middle of what shows is good enough, and the ring can't be used (it's black past the edge)
    # shortcut: walks only to 92 px from the map's middle, so your arrow stays readable (98 px); if
    # enemies out there stay out of reach, the spot is given up after 120 s and this needs a rethink
    rim = red & ((xx - R) ** 2 + (yy - R) ** 2 >= (R - 25 * sy) ** 2)
    k = max(3, round(13 * sy)) | 1
    n, lab, st, _ = cv2.connectedComponentsWithStats(cv2.morphologyEx(rim.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((k, k), np.uint8)), connectivity=8)
    for i in range(1, n):
        x, y, w, h, _ = (int(v) for v in st[i])
        q = ((x + (w - 1) / 2 - R) / sy, (y + (h - 1) / 2 - R) / sy)
        q = (q[0] * min(1.0, 92 / math.hypot(*q)), q[1] * min(1.0, 92 / math.hypot(*q)))
        if (rim & (lab == i)).sum() >= 25 * sy * sy and all(math.hypot(q[0] - s[0], q[1] - s[1]) > 16 for s in skulls):
            skulls.append(q)
    # spawn: the black-and-gold diamond in the middle of the map (the map doesn't move)
    spawn = (-1.0, -1.0)
    # you: the white arrow (12x17 px, any way round). Not the skulls' white faces (11x11), the
    # trees (thin), the gate at the top (big) or the checks of cleared spots (small). (Standing
    # on a skull, the arrow sits inside its red ring: still found)
    cands = []
    n, _, st, cen = cv2.connectedComponentsWithStats(white.astype(np.uint8), connectivity=8)
    for i in range(1, n):
        x, y, w, h, a = (int(v) for v in st[i])
        big, small = max(w, h) / sy, min(w, h) / sy
        # (pointing diagonally its box is ~12x12 - that was thrown out, and you were "lost" next
        # to a skull: Blayne 11-01 18:06. The skulls' faces stay under 75 px, the arrow ~90)
        if not (80 <= a / (sy * sy) <= 140 and 10 <= big <= 21 and 8 <= small <= 16):
            continue
        cands.append((float(cen[i][0]), float(cen[i][1])))
    player, arrow = None, None
    c2 = hud.minimap_crop(frame, MAP_R + ARROW_EXTRA)
    R2 = (c2.shape[0] - 1) // 2
    fa = find_arrow(c2, R2, sy, prev)
    if fa is not None:
        return HMap(player=((fa[0] - R2) / sy, (fa[1] - R2) / sy), arrow=fa[2], skulls=skulls, spawn=spawn)
    best = None
    for (px, py) in cands:
        X, Y = round(mm.MAP_CX * sx - R + px), round(mm.MAP_CY * sy - R + py)
        crop = frame[Y - 20:Y + 21, X - 20:X + 21]
        a = mm.read_arrow(crop) if crop.shape[:2] == (41, 41) else None
        pos = ((px - R) / sy, (py - R) / sy)
        score = (0 if a is not None else 1, math.hypot(pos[0] - prev[0], pos[1] - prev[1]) if prev else 0)
        if best is None or score < best[0]:
            best = (score, pos, a)
    if best is not None:
        _, player, arrow = best
    return HMap(player=player, arrow=arrow, skulls=skulls, spawn=spawn)


def red_near(frame, pos, r=11):
    """Red skull pixels within r map px of `pos`: a skull still there (even half hidden under your
    arrow: ~100) or gone (a grey check: 0)."""
    c = _disc(frame)
    if c is None or c.size == 0 or pos is None:
        return 0
    N = c.shape[0]
    R = (N - 1) // 2
    _, sy = hud.map_scale(frame)
    x, y = R + pos[0] * sy, R + pos[1] * sy
    rr = r * sy
    x0, x1 = max(0, int(x - rr)), min(N, int(x + rr) + 1)
    y0, y1 = max(0, int(y - rr)), min(N, int(y + rr) + 1)
    if x0 >= x1 or y0 >= y1:
        return 0
    ci = c[y0:y1, x0:x1].astype(np.int16)
    b, g, rd = ci[..., 0], ci[..., 1], ci[..., 2]
    yy, xx = np.mgrid[y0:y1, x0:x1]
    near = (xx - x) ** 2 + (yy - y) ** 2 <= rr * rr
    return int(((rd > 190) & (g < 90) & (b < 120) & near).sum())


def red_centroid(frame, pos, r=14):
    """Middle of the red skull pixels within r map px of `pos` (a skull half hidden under your
    arrow), or None."""
    c = _disc(frame)
    if c is None or c.size == 0 or pos is None:
        return None
    N = c.shape[0]
    R = (N - 1) // 2
    _, sy = hud.map_scale(frame)
    x, y = R + pos[0] * sy, R + pos[1] * sy
    rr = r * sy
    x0, x1 = max(0, int(x - rr)), min(N, int(x + rr) + 1)
    y0, y1 = max(0, int(y - rr)), min(N, int(y + rr) + 1)
    if x0 >= x1 or y0 >= y1:
        return None
    ci = c[y0:y1, x0:x1].astype(np.int16)
    b, g, rd = ci[..., 0], ci[..., 1], ci[..., 2]
    yy, xx = np.mgrid[y0:y1, x0:x1]
    m = (rd > 190) & (g < 90) & (b < 120) & ((xx - x) ** 2 + (yy - y) ** 2 <= rr * rr)
    if m.sum() < 10:
        return None
    return (float(xx[m].mean()) - R) / sy, (float(yy[m].mean()) - R) / sy


def _digits(frame, bx, scale, col, width=60):
    """Digits (left to right, with x) in a counter box, using the HUD's digit pictures."""
    H, W = frame.shape[:2]
    bw, bh = 110, 30
    x0, y0 = round(bx * W / 1920), round(40 * H / 1080)
    box = frame[y0:y0 + round(bh / scale) + 1, x0:x0 + round(bw / scale)]
    if box.shape[0] < bh or box.shape[1] < bw:
        return []
    if scale != 1.0:
        box = cv2.resize(box, (bw, bh), interpolation=cv2.INTER_AREA)
    m = (box[..., 0] > col[0]) & (box[..., 1] > col[1]) & (box[..., 2] > col[2])
    m[:, width:] = False
    cands = []
    for ch, (bits, top) in hud.DIGITS.items():
        if ch == "/":
            continue
        th, tw = bits.shape
        lim = math.floor(bits.size * 0.12)
        for y in range(top - 1, top + 2):
            if y < 0 or y + th > bh:
                continue
            win = np.lib.stride_tricks.sliding_window_view(m[y:y + th], (th, tw))[0]
            bad = (win != bits).sum(axis=(1, 2))
            for x in np.flatnonzero(bad <= lim).tolist():
                cands.append((bad[x] / bits.size, x, tw, ch))
    cands.sort()
    chosen = []
    for cd in cands:
        if all(min(cd[1] + cd[2], d[1] + d[2]) - max(cd[1], d[1]) < 0.4 * min(cd[2], d[2]) for d in chosen):
            chosen.append(cd)
    return sorted(chosen, key=lambda cd: cd[1])


def read_wave(frame, castle=None) -> int | None:
    """The WAVE number (just the number: a "BEST 10" badge follows it)."""
    cx = hud.castle_x(frame) if castle is None else castle
    if cx is None:
        return None
    best = None
    for scale, col in ((15 / 17, (140, 200, 215)), (1.0, (200, 200, 200))):
        ds = _digits(frame, cx + 27, scale, col, width=48)
        # the number = the first digits, up to the first gap (the badge starts after one)
        out, end = "", None
        for _, x, tw, ch in ds:
            if end is not None and x - end > 6:
                break
            out += ch
            end = x + tw
        if out and (best is None or len(out) > len(best)):
            best = out
    try:
        return int(best) if best else None
    except ValueError:
        return None


def read_spots(frame, castle=None) -> hud.Counter | None:
    """SPOTS a/b: spots still awake / spots this wave."""
    cx = hud.castle_x(frame) if castle is None else castle
    if cx is None:
        return None
    for dx in (348, 352, 344, 356):
        r = hud._read_counter(frame, cx + dx, 15 / 17, (140, 200, 215))
        if r is not None:
            return r
    return hud._read_counter(frame, cx + 352, 1.0, (200, 200, 200))


# ======================= the run =======================
class HuecoRun:
    """One Hueco Mundo run. env = the farm's Game (or a test double). run() returns 'done',
    'left' (left after the set wave), 'popup' (joined a Dungeon / Trial popup), 'stopped' (F6) or
    'paused' (Roblox not in front)."""

    def __init__(self, env):
        self.env = env
        self.S = env.settings
        S = self.S
        self.leave_after = int(S.get("hueco_leave_after", 10))
        self.k = float(S.get("cam_px_per_rad", 584))
        if not 60 <= abs(self.k) <= 4000:
            self.k = 584.0
        self.speed = float(S.get("hueco_speed_px_s", 0) or 0)      # map px per second (learned)
        self.prev = None
        self.target = None
        self.lock = None                # the spot being cleared (see run)
        self.lost_since = None          # when your arrow went missing from the map
        self.lost_steps = 0             # steps taken to find it again
        self.lost_logged = False
        self.wave_t = env.now()
        self.unseen_logged = None
        self.last_arrow = None
        self.lost_drags = 0             # camera drags in a row that didn't turn it
        self.no_turn_until = -1e9
        self.at_target_since = None
        self.last_kill_t = env.now()
        self.en_text = None
        self.skip: dict = {}
        self.last_spawn = -1e9
        self.wave = None
        self.wave_seen_spots = False
        self.progress = None            # (t, x, y) for the stuck check
        self.tap_ref = None             # (t, distance) when the short taps near a spot began
        self.last_walk = -1e9
        self.last_tap = None            # ((x, y), seconds) of the last short tap
        self.stucks = 0
        self.unstick_until = 0.0
        self.unstick_keys = set()
        self.keys = set()
        self.last_status = ""
        self.sample = None              # (t, x, y) start of a W-only stretch (speed / mount check)
        self.mount_want = bool(S.get("hueco_mount", True)) and hasattr(env, "toggle_mount")
        self.mount_step = None          # None, ('pressed', speed_before)
        self.mount_speeds = []
        self.mount_done = getattr(env, "mount_on", None) is True
        self.card_t = -1e9
        self.cards = card_pictures()
        self.sweep_i = 0

    # ---- small helpers ----
    def say(self, msg):
        if msg != self.last_status:
            self.last_status = msg
            self.env.status(msg)
            if not msg.startswith(("walking to", "turning", "fighting")):
                self.env.log(msg)

    def hold(self, keys):
        keys = set(keys)
        if keys != self.keys:
            self.keys = keys
            self.env.set_keys(keys)

    def stop(self):
        self.hold(set())

    def leave(self, why):
        e = self.env
        self.stop()
        c = e.find("leave")
        if c:
            e.click(*c)
            e.log(f"Hueco Mundo: {why} · leaving")
            e.shot(f"hueco-left-wave-{self.wave}", force=True)
            e.sleep(3)
            return True
        return False

    # ---- mount: like the dungeon's, judged by the speed on the map ----
    def mount_check(self, now, speed):
        """Gets on the mount: three speed readings, press M, three more. Faster = it got on; slower =
        it was on already and that press got off (press again). The fastest of each three counts
        (a rock or a turn only ever makes a reading slower)."""
        e = self.env
        if not self.mount_want or self.mount_done:
            return
        self.mount_speeds.append(speed)
        if len(self.mount_speeds) < 3:
            return
        sp, self.mount_speeds = max(self.mount_speeds), []
        if self.mount_step is None:
            if e.toggle_mount("Hueco Mundo · getting on the mount"):
                self.mount_step = ("pressed", sp)
            else:
                self.mount_done = True
            return
        before = self.mount_step[1]
        self.mount_done = True
        if sp < 0.8 * before:
            e.toggle_mount("slower after that press, so it was already on the mount · pressing again")
        elif sp < 1.3 * before:
            e.log("Hueco Mundo: the mount key didn't change the speed · leaving it as it is")
            return
        e.mount_on = True
        mx = max(sp, before)
        e.save_setting("hueco_speed_px_s", round(mx, 1), quiet=True)
        self.speed = mx

    def step_sec(self, px):
        """How long to hold a key to move about `px` map pixels."""
        return max(0.12, min(0.6, px / (self.speed or 25.0)))

    # ---- the camera ----
    def turn_to(self, want, arrow):
        """Right-mouse drag to look along map angle `want`, checked on the arrow."""
        e = self.env
        d = wrap(want - arrow)
        self.stop()
        self.say(f"turning the camera toward the spot ({math.degrees(d):+.0f} deg)")
        for _ in range(3):
            px = round(max(-1.6, min(1.6, d)) * self.k)
            # after a drag that didn't turn the camera (Roblox missed the right-button press and
            # the mouse just slid across the screen, Blayne 11-01 18:21): the careful kind - a
            # separate right click first, a longer hold, smaller steps
            try:
                e.cam_drag(px, slow=self.lost_drags > 0)
            except TypeError:
                e.cam_drag(px)
            e.sleep(0.25)
            f = e.frame()
            m = read_map(f, self.prev) if f is not None else None
            if m is None or m.arrow is None:
                return
            turned = wrap(m.arrow - arrow)
            if abs(px) > 100:
                if abs(turned) < 0.05:
                    self.lost_drags += 1
                    if self.lost_drags >= 2:
                        # twice in a row: stop turning for a while and walk there with W/A/S/D
                        # relative to wherever the camera looks
                        self.no_turn_until = e.now() + 10
                        e.log("Hueco Mundo: the camera didn't turn on 2 drags in a row · walking "
                              "without turning for 10s")
                        self.lost_drags = 0
                        return
                else:
                    self.lost_drags = 0
            if abs(px) > 150 and abs(turned) > 0.4:
                k = px / turned
                if 60 <= abs(k) <= 4000 and abs(self.k) / 2 <= abs(k) <= 2 * abs(self.k) and (k > 0) == (self.k > 0):
                    self.k = 0.7 * self.k + 0.3 * k
                    e.save_setting("cam_px_per_rad", round(self.k), quiet=True)
            arrow = m.arrow
            d = wrap(want - arrow)
            if abs(d) < 0.12:
                return

    # ---- main loop ----
    def run(self):
        e = self.env
        S = self.S
        leave_for_popups = bool(S.get("hueco_leave_for_popups", True))
        misses = 0
        last_house = last_pop = 0.0
        e.log(f"Hueco Mundo started · leaving after wave {self.leave_after}")
        e.shot("hueco-started", force=True)
        while True:
            if not e.running():
                self.stop()
                sf = getattr(e, "stop_flag", None)
                return "stopped" if (sf and sf()) else "paused"
            now = e.now()
            f = e.frame()
            if f is None:
                e.sleep(0.2)
                continue
            # ---- card vote between waves
            if card_screen(f, e.tpl):
                self.stop()
                misses = 0
                if now - self.card_t > 3:
                    self.card_t = now
                    i, why = pick_card(f, self.cards)
                    e.tap(str(i), 60)
                    e.log(f"Hueco Mundo: card vote · picked card {i} ({why})")
                    self.say(f"choosing a card ({i})")
                e.sleep(0.3)
                continue
            castle = hud.castle_x(f)
            if castle is None or not is_hueco(f, castle):
                self.stop()
                if hud.covered(f) or hud.spawn_hidden(f):
                    misses = 0                 # teleport / trait-roll animation: not the end
                    e.sleep(0.2)
                    continue
                misses += 1
                if misses >= 20:
                    e.log(f"Hueco Mundo: run over (wave {self.wave})")
                    e.shot("hueco-finished", force=True)
                    return "done"
                e.sleep(0.25)
                continue
            misses = 0
            # ---- popups: join a Dungeon / Trial popup (leaves this run) if set so
            if leave_for_popups and now - last_pop > 2.0:
                last_pop = now
                pop = hud.find_popup(f)
                if pop and ((pop.kind == "dungeon") or (pop.kind == "trial" and S.get("join_trials"))):
                    self.stop()
                    e.click(pop.x, pop.y)
                    e.log(f"Hueco Mundo: leaving for the {pop.kind} popup (wave {self.wave})")
                    e.shot(f"hueco-left-for-{pop.kind}", force=True)
                    return "popup"
            if now - last_house > 1.0:
                last_house = now
                if e.housekeeping():          # the menus left open after Play, Join Event...
                    self.stop()
                    continue
            # ---- counters
            wave = read_wave(f, castle)
            spots = read_spots(f, castle)
            en = hud.read_counter(f, "enemies")
            if isinstance(getattr(e, "info", None), dict):
                e.info["wave"] = str(wave) if wave is not None else "?"
                e.info["enemies"] = en.text if en else "?"
                e.info["rooms"] = f"spots {spots.text}" if spots else "spots ?"
            if wave is not None and wave != self.wave:
                if self.wave is not None:
                    e.log(f"Hueco Mundo: wave {wave}")
                self.wave, self.wave_seen_spots = wave, False
                self.wave_t = now
                self.skip.clear()
            if spots is not None and spots.b > 0 and spots.a > 0:
                self.wave_seen_spots = True
            if self.wave is not None and self.wave > self.leave_after:
                if self.leave(f"wave {self.leave_after} done"):
                    return "left"
            if self.wave == self.leave_after and self.wave_seen_spots and spots is not None \
                    and spots.b > 0 and spots.a == 0:
                if self.leave(f"wave {self.wave} cleared"):
                    return "left"
            if en is not None and en.text != self.en_text:
                self.en_text, self.last_kill_t = en.text, now
            # ---- the map
            m = read_map(f, self.prev)
            spots_a = spots.a if spots is not None and spots.b > 0 else None
            # ---- the spot being cleared (locked): it's done when the SPOTS counter goes down by
            # one (its group is dead), or its skull has turned into a grey check (no red left
            # there). NOT when the skull just can't be seen: standing on it, your arrow covers it
            # (that made it walk off with enemies left, Blayne 11-01)
            lk = self.lock
            if lk is not None and self.wave is not None and lk["wave"] != self.wave:
                self.lock = lk = None                 # next wave: back at spawn, new spots
            if lk is not None:
                if red_near(f, lk["pos"]) < 10:
                    lk["gone"] += 1
                else:
                    lk["gone"] = 0
                done = None
                if lk["arrived"] is not None and spots_a is not None and lk["spots"] is not None \
                        and spots_a < lk["spots"]:
                    done = f"SPOTS went down to {spots.text}"
                elif lk["gone"] >= 4:
                    done = "its skull turned into a check"
                if done:
                    if lk["arrived"] is not None:
                        e.log(f"Hueco Mundo: spot cleared ({done}) after {now - lk['arrived']:.0f}s")
                    self.lock = lk = None
                    self.at_target_since, self.sweep_i = None, 0
            if m is None or m.player is None:
                self.stop()
                self.lost_since = self.lost_since or now
                if lk is not None and lk["arrived"] is None and now - self.lost_since > 1.5 and \
                        self.prev is not None and self.last_arrow is not None and self.lost_steps < 5:
                    # lost next to the skull for a moment: a short step toward it (worked out from
                    # where you were last seen and which way the camera looked then). Only a few:
                    # that spot goes stale, and past it these only walk you further off the map
                    self.lost_since = now
                    self.lost_steps += 1
                    k = keys_for(lk["pos"][0] - self.prev[0], lk["pos"][1] - self.prev[1], self.last_arrow) or {"w"}
                    self.hold(k)
                    e.sleep(0.09)
                    self.stop()
                    e.log("Hueco Mundo: lost you on the map next to the spot · a short step toward it")
                    continue
                # still not seen: step until it shows. Waiting for it lost whole runs: the arrow
                # can be hidden under the spawn diamond and only comes back when you move (11-01
                # 18:44-19:24: 12 runs stood there, 0 kills, Defeat) or stay lost at a spot by the
                # rim (18:42). Only with spots left (not in the countdown), and later when on a
                # spot, where your arrow can sit on its skull while the group dies
                at_spot = lk is not None and self.prev is not None and \
                    math.hypot(self.prev[0] - lk["pos"][0], self.prev[1] - lk["pos"][1]) < 4
                if spots_a and now - self.lost_since > (12 if at_spot else 3):
                    self.lost_since = now
                    self.hold({"wasd"[self.lost_steps % 4]})
                    e.sleep(self.step_sec(12))
                    self.stop()
                    self.lost_steps += 1
                    if not self.lost_logged:
                        self.lost_logged = True
                        e.log("Hueco Mundo: can't see you on the map · stepping until it shows · screenshot saved")
                        e.shot("hueco-arrow-lost", force=True)
                    continue
                if lk is not None and self.prev is not None and \
                        math.hypot(self.prev[0] - lk["pos"][0], self.prev[1] - lk["pos"][1]) < 4:
                    # (on the skull your arrow can merge with its white face: you're there)
                    if lk["arrived"] is None:
                        lk["arrived"], lk["spots"] = now, spots_a
                    self.say(f"fighting · wave {self.wave} · enemies {self.en_text} · spots {spots.text if spots else '?'}")
                else:
                    self.say("can't see you on the map · waiting")
                e.sleep(0.15)
                continue
            px, py = m.player
            self.lost_since = None
            self.lost_steps, self.lost_logged = 0, False
            if m.arrow is not None:
                self.last_arrow = m.arrow
            moved = self.prev is not None and math.hypot(px - self.prev[0], py - self.prev[1]) > 12
            self.prev = (px, py)
            if moved:                          # teleported (Spawn, or the next wave)
                self.progress = self.sample = self.last_tap = None

            def dist(a, b2):
                return math.hypot(a[0] - b2[0], a[1] - b2[1])
            skulls = [sk for sk in m.skulls if self.skip.get((round(sk[0] / 4), round(sk[1] / 4)), 0) <= now]
            if lk is None and not skulls and spots_a:
                # SPOTS says some are left but none is on the map: one may be under your arrow
                # (its circle hidden) - take the red right around you
                q = red_centroid(f, (px, py))
                if q is not None:
                    skulls = [q]
            if lk is None:
                if not skulls:
                    self.stop()
                    self.target = None
                    if spots_a and now - self.wave_t > 8 and self.unseen_logged != self.wave:
                        # the counter says spots are left but none can be seen on the map: say so
                        # (with a picture), so it can be fixed (11-01 18:12: one by the S badge)
                        self.unseen_logged = self.wave
                        e.log(f"Hueco Mundo: SPOTS says {spots.text} but no skull seen on the map · screenshot saved")
                        e.shot("hueco-spot-not-seen", force=True)
                    self.say(f"wave {self.wave} · no spots left on the map · waiting for the next wave")
                    e.sleep(0.2)
                    continue
                best = min(skulls, key=lambda sk: dist(sk, (px, py)))
                self.lock = lk = {"pos": best, "wave": self.wave, "arrived": None, "spots": None,
                                  "gone": 0, "t": now}
                self.at_target_since, self.sweep_i = None, 0
            else:
                # the skull's centre, measured while you're not on top of it (from close up your
                # arrow hides part of it and shifts the reading)
                near = [sk for sk in skulls if dist(sk, lk["pos"]) < 6]
                if near and dist(near[0], (px, py)) > 14:
                    q = near[0]
                    lk["pos"] = (0.5 * lk["pos"][0] + 0.5 * q[0], 0.5 * lk["pos"][1] + 0.5 * q[1])
            best = lk["pos"]
            self.target = best
            d = dist(best, (px, py))
            # ---- press Spawn when walking from spawn is quicker
            spd = self.speed or 25.0
            if lk["arrived"] is None and d > 20 and now - self.last_spawn > 8 and \
                    dist(best, m.spawn) + SPAWN_COST_SEC * spd < d and S.get("hueco_spawn_shortcut", True):
                self.stop()
                if e.press_spawn(wait=1.2):
                    self.last_spawn = e.now()
                    e.log("Hueco Mundo: pressed Spawn · the next spot is quicker from there")
                    self.prev = None
                    continue
                self.last_spawn = now
            # ---- into the very middle of the skull (the group is spread around it)
            if lk["arrived"] is None and d <= CENTER_PX:
                lk["arrived"], lk["spots"] = now, spots_a
                self.at_target_since = now
                self.stucks, self.tap_ref = 0, None
            if lk["arrived"] is None:
                self.walk(now, (px, py), best, m)
                self.say(f"walking to the spot · wave {self.wave} · {d:.1f}px")
                continue
            # ---- at the spot: stay until SPOTS goes down (see above)
            if lk["spots"] is None:
                lk["spots"] = spots_a
            here = now - lk["arrived"]
            quiet = now - max(self.last_kill_t, lk["arrived"])
            if here > 120:
                self.skip[(round(best[0] / 4), round(best[1] / 4))] = now + 60
                e.log(f"Hueco Mundo: spot not cleared after {here:.0f}s · trying another for now")
                e.shot("hueco-spot-stuck", force=True)
                self.lock = None
                continue
            if quiet > 12 and here > 12:
                # nothing died for a while: some of the group stands out of reach - a small round
                # about the spot, then back to the middle
                ang = self.sweep_i * math.pi / 2
                tx, ty = (best[0] + 5 * math.cos(ang), best[1] + 5 * math.sin(ang)) if self.sweep_i < 4 else best
                self.walk(now, (px, py), (tx, ty), m, close=True)
                if math.hypot(tx - px, ty - py) < 2.0:
                    self.sweep_i += 1
                    if self.sweep_i > 4:
                        self.sweep_i, self.last_kill_t = 0, now
                self.say(f"wave {self.wave} · enemies {self.en_text} · walking round the spot")
                continue
            if d > 3.0:                         # pushed off the middle: back onto it
                self.walk(now, (px, py), best, m, close=True)
                self.say(f"back to the middle of the spot · {d:.1f}px")
                continue
            self.stop()
            self.progress = None
            self.say(f"fighting · wave {self.wave} · enemies {self.en_text} · spots {spots.text if spots else '?'}")
            e.sleep(0.1)

    def stuck_check(self, now, px, py):
        """Keys held but the arrow isn't moving on the map (a rock in the way): jump, then go
        round it, and after 8 tries press Spawn."""
        e = self.env
        if self.progress is None:
            self.progress = (now, px, py)
        elif math.hypot(px - self.progress[1], py - self.progress[2]) > 2.0:
            self.progress, self.stucks = (now, px, py), 0
        elif now - self.progress[0] > 0.8:
            self.stucks += 1
            self.progress = None
            self.sample = None
            e.tap("space", 80)
            if self.stucks >= 2:
                # jump didn't do it: back up and go round (left / right in turn)
                side = "a" if self.stucks % 2 else "d"
                self.unstick_keys = {"w", side} if self.stucks <= 3 else {"s", side}
                self.unstick_until = now + self.step_sec(12)
            e.log(f"Hueco Mundo: not moving · jumping{' and going round' if self.stucks >= 2 else ''}")
            if self.stucks >= 8 and now - self.last_spawn > 20 and e.press_spawn(wait=1.2):
                e.log("Hueco Mundo: stuck · pressed Spawn")
                self.last_spawn = e.now()
                self.stucks = 0
                self.prev = None

    def walk(self, now, pos, tgt, m, close=False):
        """One step toward `tgt` (map px): face it, then W (short taps when close)."""
        e = self.env
        px, py = pos
        vx, vy = tgt[0] - px, tgt[1] - py
        d = math.hypot(vx, vy)
        want = math.atan2(vy, vx)
        if now < self.unstick_until:
            self.hold(self.unstick_keys)
            e.sleep(0.03)
            return
        if m.arrow is None:
            self.stop()
            e.sleep(0.1)
            return
        err = wrap(want - m.arrow)
        near = d < 14 or close
        if not near and abs(err) > 0.35 and now < self.no_turn_until:
            # the camera won't turn right now: walk there with W/A/S/D as it is
            self.hold(keys_for(vx, vy, m.arrow) or {"w"})
            e.sleep(0.05)
            self.stuck_check(now, px, py)
            return
        if not near and abs(err) > 0.35:
            self.turn_to(want, m.arrow)
            self.progress = self.sample = None
            return
        if near:
            # close: a tap sized to the distance, so it stops on the spot. Taps that don't get it
            # any closer (a rock in the way) = jump with the next one, then go round
            # how far the last tap went teaches the speed (it changes with the mount, and an
            # unknown speed made taps swing past the spot and back)
            if self.last_tap is not None:
                (tx0, ty0), tsec = self.last_tap
                went = math.hypot(px - tx0, py - ty0)
                if went > 1.0 and tsec >= 0.03:
                    v = went / tsec
                    if 3 < v < 1000:
                        self.speed = v if not self.speed else 0.5 * self.speed + 0.5 * v
            spd = self.speed or 25.0
            ms = max(30, min(220, 0.7 * d / spd * 1000))
            self.last_tap = ((px, py), ms / 1000)
            if close or self.tap_ref is None or d < self.tap_ref[1] - 1.0:
                self.tap_ref = (now, d)        # (walking round a spot: the target keeps moving)
            elif now - self.tap_ref[0] > 1.5:
                self.tap_ref = (now, d)
                self.stucks += 1
                e.tap("space", 80)
                if self.stucks >= 2:
                    side = "a" if self.stucks % 2 else "d"
                    self.unstick_keys = {"s", side} if self.stucks % 3 == 0 else {"w", side}
                    self.unstick_until = now + self.step_sec(8)
                e.log(f"Hueco Mundo: not getting closer · jumping{' and going round' if self.stucks >= 2 else ''}")
            # (no camera turn this close: step whichever way with W/A/S/D)
            self.hold(keys_for(vx, vy, m.arrow) or {"w"})
            e.sleep(ms / 1000)
            self.stop()
            e.sleep(0.08)
            self.progress = self.sample = None
            return
        self.tap_ref = None
        self.hold({"w"})
        # speed (W only, going straight): the mount check and the Spawn shortcut use it. Only a
        # stretch walked without a break (a fight or a turn in between made it look slow)
        if now - self.last_walk > 0.4:
            self.sample = None
        self.last_walk = now
        if self.sample is None:
            self.sample = (now, px, py, self.stucks)
        elif now - self.sample[0] >= 0.4:
            t0, x0, y0, st0 = self.sample
            dx, dy = px - x0, py - y0
            sp = math.hypot(dx, dy) / (now - t0)
            self.sample = None
            # a clean stretch: no rock hit, and going the way the camera looks (not scraping along)
            if sp > 3 and st0 == self.stucks and abs(wrap(math.atan2(dy, dx) - m.arrow)) < 0.4:
                if self.mount_want and not self.mount_done:
                    self.mount_check(now, sp)
                elif sp > 0.6 * (self.speed or sp):
                    self.speed = sp if not self.speed else 0.8 * self.speed + 0.2 * sp
                    e.save_setting("hueco_speed_px_s", round(self.speed, 1), quiet=True)
        self.stuck_check(now, px, py)
        e.sleep(0.03)
