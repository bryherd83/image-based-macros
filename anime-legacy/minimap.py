"""Minimap reader for Anime Legacy dungeons.

Since the game's 10-19 UI update the minimap (top-right) is a dark navy disc with N/E/S/W badges
on its rim and gold -/+ zoom buttons below. It is north-up and centred on you:
  rooms = rounded tiles with a black outline and a light-to-dark gradient:
          blue = spawn, green = cleared, grey = not done, gold = treasure;
  doors = small lavender tabs in the gap between two rooms;
  you   = a white outline around your room and a white arrow (same size at every zoom).
Everything here works on a BGR numpy crop of the minimap: no screen access, so it can be tested
on saved screenshots. (The pre-update reader is in git history, before commit "new minimap".)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

# Positions on a 1920x1080 client area (new UI, 10-19)
REF_W, REF_H = 1920, 1080
MAP_CX, MAP_CY, MAP_R = 1774, 174, 90          # disc centre; read radius (inside the badges)
MAP_MINUS_X, MAP_PLUS_X, MAP_BUTTONS_Y = 1686, 1859, 263
COMPASS_DY = 105                                # N / S badges this far above / below the centre

NONE, SPAWN, CLEARED, TODO, TREASURE, WHITE, DOOR = 0, 1, 2, 3, 4, 5, 6
HIDDEN = 9  # your own room, if its colour can't be seen

NAMES = {SPAWN: "spawn", CLEARED: "cleared", TODO: "not done", TREASURE: "treasure", HIDDEN: "hidden"}


def classify(bgr: np.ndarray) -> np.ndarray:
    """Pixel classes. Tiles are gradients, so colours are told apart by hue, not exact values."""
    b = bgr[..., 0].astype(np.int16)
    g = bgr[..., 1].astype(np.int16)
    r = bgr[..., 2].astype(np.int16)
    k = np.zeros(b.shape, np.uint8)
    neutral = (np.abs(r - g) < 10) & (np.abs(g - b) < 10)
    k[neutral & (g > 90) & (g < 228)] = TODO
    k[(g > 120) & (g - r > 45) & (g - b > 25)] = CLEARED
    k[(b > 185) & (b - r > 70) & (g > 100)] = SPAWN
    k[(r > 175) & (r - b > 60) & (g > 140)] = TREASURE
    k[(b > 238) & (g > 228) & (r > 222) & (b - r >= 8) & (b - r <= 30)] = DOOR     # lavender tab
    k[(b > 245) & (g > 245) & (r > 245)] = WHITE
    return k


@dataclass
class MapView:
    s: int                      # room size (px)
    p: float                    # room spacing (px)
    cells: dict                 # (a, b) -> class, a columns east / b rows south of your room
    doors: set                  # {((a,b),(c,d)), ...} both directions
    walls: set
    offx: float                 # where you are inside your room (px from its centre, east +)
    offy: float                 # (south +)
    edges: int = 0              # how many whole tiles were used (quality)
    raw: np.ndarray | None = field(default=None, repr=False)

    def here(self) -> int:
        return self.cells.get((0, 0), HIDDEN)


def _circ_mean(fr: np.ndarray) -> float:
    """Mean of values in [-0.5, 0.5) taken as a phase (wraps around)."""
    t = 2 * math.pi * fr
    return math.atan2(np.sin(t).sum(), np.cos(t).sum()) / (2 * math.pi)


def _outline(bgr: np.ndarray, R: int, s: int):
    """Centre (x, y) of the white outline around your own room, or None."""
    N = bgr.shape[0]
    yy, xx = np.mgrid[0:N, 0:N]
    d2 = (xx - R) ** 2 + (yy - R) ** 2
    w = (bgr.min(axis=2) > 240) & (d2 > 14 * 14) & (d2 <= R * R)       # (not the arrow)
    n, _, st, _ = cv2.connectedComponentsWithStats(w.astype(np.uint8), connectivity=8)
    best = None
    for i in range(1, n):
        x, y, ww, hh, a = (int(v) for v in st[i])
        if (1.0 * s <= ww <= 1.5 * s + 4 and 1.0 * s <= hh <= 1.5 * s + 4 and 0.8 < ww / hh < 1.25
                and x - 10 < R < x + ww + 10 and y - 10 < R < y + hh + 10):
            if best is None or a > best[4]:
                best = (x, y, ww, hh, a)
    if best is None:
        return None
    x, y, ww, hh, _ = best
    return x + (ww - 1) / 2, y + (hh - 1) / 2


class MapReader:
    """Keeps the room spacing between frames (a frame with few whole tiles can't measure it)."""

    def __init__(self):
        self.p = 0.0
        self.s = 0
        self.pitch_by_size: dict[int, float] = {}

    def reset(self):
        self.p, self.s = 0.0, 0

    def parse(self, bgr: np.ndarray) -> MapView | None:
        """bgr: square crop (2R+1) centred on the minimap centre."""
        N = bgr.shape[0]
        R = (N - 1) // 2
        cls = classify(bgr)
        yy, xx = np.mgrid[0:N, 0:N]
        d2 = (xx - R) ** 2 + (yy - R) ** 2
        inside = d2 <= R * R
        cls[~inside] = NONE
        body = ((cls >= 1) & (cls <= 4)).astype(np.uint8)
        n, lab, stats, cent = cv2.connectedComponentsWithStats(body, connectivity=4)
        if n <= 1:
            return None
        counts = np.bincount((lab * 8 + cls).ravel(), minlength=n * 8).reshape(n, 8)
        blobs = []
        for i in range(1, n):
            x, y, w, h, a = (int(v) for v in stats[i])
            if w < 5 or h < 5 or a < 20:
                continue                        # specks, the tiles' thin top highlight
            cx, cy = float(cent[i][0]), float(cent[i][1])
            far = max(math.hypot(px - R, py - R) for px in (x, x + w - 1) for py in (y, y + h - 1))
            clipped = far > R - 2
            blobs.append((cx, cy, w, h, a, int(np.argmax(counts[i, 1:5])) + 1, clipped))
        if not blobs:
            return None
        full = [b for b in blobs if not b[6] and 0.75 <= b[2] / b[3] <= 1.33]
        if full:
            s = int(round(float(np.median([max(b[2], b[3]) for b in full]))))
        else:                                   # zoomed right in: only parts of big tiles
            s = max(max(b[2], b[3]) for b in blobs)
        # spacing between neighbouring tiles
        steps = []
        for i, a in enumerate(full):
            for b in full[i + 1:]:
                dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
                if dy < s / 3 and s < dx < 1.8 * s:
                    steps.append(dx)
                elif dx < s / 3 and s < dy < 1.8 * s:
                    steps.append(dy)
        p_new = float(np.median(steps)) if steps else 0.0
        if self.p == 0 or abs(self.s - s) > 1:
            self.p = p_new or self.pitch_by_size.get(s, 1.15 * s)
            self.s = s
        elif p_new:
            self.p = self.p * 0.7 + p_new * 0.3
        p = self.p
        if p_new:
            old = self.pitch_by_size.get(s)
            self.pitch_by_size[s] = p_new if old is None else old * 0.8 + p_new * 0.2
        # where the grid of room centres sits (your room's centre = nearest to the map centre)
        ref = full or [max(blobs, key=lambda b: b[4])]
        fx = np.array([(b[0] - R) / p for b in ref])
        fy = np.array([(b[1] - R) / p for b in ref])
        gx = R + _circ_mean(fx - np.round(fx)) * p
        gy = R + _circ_mean(fy - np.round(fy)) * p
        # your own room has a white outline: its centre is exact (the tiles' centroids sit a few
        # px low because of their white top line, and big tiles are cut off by the rim), and it
        # is the room the game says you're in - also while you stand in a doorway (PC 10-19
        # 16:02: at a doorway the nearest tile flipped back and forth and the farm with it)
        ol = _outline(bgr, R, s)
        if ol is not None and abs(ol[0] - gx) < 0.75 * p and abs(ol[1] - gy) < 0.75 * p:
            gx, gy = ol
        cells, area = {}, {}
        for cx, cy, w, h, a, k, clipped in blobs:
            if a < (0.12 if clipped else 0.25) * s * s:
                continue
            key = (int(round((cx - gx) / p)), int(round((cy - gy) / p)))
            if a > area.get(key, 0):
                cells[key], area[key] = k, a
        if (0, 0) not in cells:
            cells[(0, 0)] = HIDDEN

        # a door is a short light tab across the gap, in the middle of the side: light pixels in
        # the middle of the gap but not near the corners (a tile's white top highlight runs
        # along the whole side, so it shows up at both)
        bi = bgr.astype(np.int16)
        light = (bi.min(axis=2) > 185) & (np.abs(bi[..., 1] - bi[..., 0]) < 25) \
            & (np.abs(bi[..., 2] - bi[..., 1]) < 25) & (bi[..., 0] >= bi[..., 2] - 8) & inside
        arrow = d2 <= 13 * 13
        door = (cls == DOOR) & inside & ~arrow
        doors, walls = set(), set()
        hg = max(1.5, (p - s) / 2 + 1)

        def share(x1, x2, y1, y2):
            xa, xb = max(0, round(x1)), min(N - 1, round(x2))
            ya, yb = max(0, round(y1)), min(N - 1, round(y2))
            if xa > xb or ya > yb:
                return 0.0, 0
            ok = inside[ya:yb + 1, xa:xb + 1] & ~arrow[ya:yb + 1, xa:xb + 1]
            t = int(ok.sum())
            return (float((light[ya:yb + 1, xa:xb + 1] & ok).sum()) / t if t else 0.0), t

        lt = (bi.min(axis=2) > 185) & inside

        def own_tab(mx, my, g):
            # light pixels across the gap (+-4 px, a 5 px wide strip) in the middle of the side,
            # minus the same next to the corners (0.3 of a room either way)
            def strip(lat):
                tot = 0
                for t in range(-4, 5):
                    x = round(mx + g[0] * t + g[1] * lat)
                    y = round(my + g[1] * t + g[0] * lat)
                    if g[0]:
                        seg = lt[max(0, y - 2):y + 3, x] if 0 <= x < N else lt[0:0, 0]
                    else:
                        seg = lt[y, max(0, x - 2):x + 3] if 0 <= y < N else lt[0, 0:0]
                    tot += int(seg.sum())
                return tot
            return strip(0) - max(strip(-0.3 * s), strip(0.3 * s))

        for (a, b), k in cells.items():
            for g in ((1, 0), (0, 1)):
                k2 = (a + g[0], b + g[1])
                if k2 not in cells:
                    continue
                mx, my = gx + (a + g[0] / 2) * p, gy + (b + g[1] / 2) * p
                bands = []
                for lo, hi in ((-0.15, 0.15), (-0.45, -0.3), (0.3, 0.45)):
                    if g[0]:
                        bands.append(share(mx - hg, mx + hg, my + lo * s, my + hi * s))
                    else:
                        bands.append(share(mx + lo * s, mx + hi * s, my - hg, my + hg))
                (mid, nm), (e1, n1), (e2, n2) = bands
                # the tab's own lavender, in the same three bands: a tab is only in the middle;
                # your room's white outline and its glow run along the whole side (PC 10-19
                # 15:37: a plain wall next to your room was taken for a door, and the farm kept
                # walking into it)
                lavs = []
                for lo, hi in ((-0.2, 0.2), (-0.48, -0.3), (0.3, 0.48)):
                    if g[0]:
                        sl = door[max(0, round(my + lo * s)):max(0, round(my + hi * s)) + 1,
                                  max(0, round(mx - hg - 2)):round(mx + hg + 2) + 1]
                    else:
                        sl = door[max(0, round(my - hg - 2)):round(my + hg + 2) + 1,
                                  max(0, round(mx + lo * s)):max(0, round(mx + hi * s)) + 1]
                    lavs.append(int(sl.sum()))
                    if lo == -0.2:
                        # how thick the lavender is across the gap: a tab spans the gap; the blue
                        # spawn room's top highlight is a 1 px line that classes as lavender too
                        # (PC 10-19 20:23: read as a door north of spawn, ran into the wall)
                        thick = int((sl.any(axis=0) if g[0] else sl.any(axis=1)).sum())
                lm, l1, l2 = lavs
                lav_tab = lm >= (3 if s >= 20 else 2) and l1 <= 0.4 * lm and l2 <= 0.4 * lm \
                    and (thick >= 2 or s < 20)
                tab = nm >= 2 and mid >= 0.35 and (n1 == 0 or e1 < 0.6 * mid) and (n2 == 0 or e2 < 0.6 * mid)
                if (0, 0) in ((a, b), k2):
                    # your room's white outline lies in these gaps (and its rounded corners
                    # leave the corner bands darker, so it looked like a tab: laptop 16:33, the
                    # farm ran into the wall north of it over and over). Only the tab's own
                    # lavender counts here
                    tab = False
                if math.hypot(mx - R, my - R) < max(ARROW_NEAR_MIN, 0.36 * p):
                    # a gap near your arrow says nothing either way: the arrow can hide its dot
                    # or look like one (Blayne 10-19: read the doors from the middle of the room,
                    # not up against a wall). Memory keeps what was read from further away
                    pass
                elif tab or lav_tab:
                    doors.add(((a, b), k2))
                    doors.add((k2, (a, b)))
                elif (0, 0) in ((a, b), k2) and k != HIDDEN and cells[k2] != HIDDEN and s >= 20:
                    # your own room: its white outline fills the gap, so 'dark gap' never
                    # happens and its walls stayed 'maybe a door' and were walked into (PC
                    # 20:09). Across the gap, a tab is light much further than the thin outline
                    # is (the outline looks the same in the middle of the side as near a corner)
                    ext = own_tab(mx, my, g)
                    if ext >= 12:
                        doors.add(((a, b), k2))
                        doors.add((k2, (a, b)))
                    elif ext <= 3:
                        walls.add(((a, b), k2))
                        walls.add((k2, (a, b)))
                elif k != HIDDEN and cells[k2] != HIDDEN and nm >= 2 and mid < 0.1:
                    walls.add(((a, b), k2))
                    walls.add((k2, (a, b)))
        return MapView(s=s, p=p, cells=cells, doors=doors, walls=walls, offx=R - gx, offy=R - gy,
                       edges=len(full), raw=None)


# ---------------- The arrow in the middle of the minimap ----------------
# gaps closer than this (px) to the map centre are left unread: the ~10 px arrow (its tip reaches
# ~10 px out) plus the strip a door is looked for in. From the middle of a room every side is
# 0.5 room away (24+ px at the walking zoom), so all four get read there
# (0.36 of a room: from the middle a side is 0.5 away, so a few px off the middle still reads it)
ARROW_NEAR_MIN = 14
# The new UI's white arrow (taken from a screenshot), pointing north, around the map centre.
# It is the same size at every zoom.
_ARROW = "1,-7;1,-6;0,-5;1,-5;2,-5;-1,-4;0,-4;1,-4;2,-4;3,-4;-2,-3;-1,-3;0,-3;1,-3;2,-3;3,-3;-2,-2;-1,-2;0,-2;1,-2;2,-2;3,-2;4,-2;-3,-1;-2,-1;-1,-1;0,-1;1,-1;2,-1;3,-1;4,-1;5,-1;-4,0;-3,0;-2,0;-1,0;0,0;1,0;2,0;3,0;4,0;5,0;-4,1;-3,1;-2,1;-1,1;0,1;1,1;2,1;3,1;4,1;5,1;6,1;-5,2;-4,2;-3,2;-2,2;-1,2;0,2;1,2;2,2;3,2;4,2;5,2;6,2;-2,3;-1,3;0,3;1,3;2,3;3,3;4,3;5,3;6,3;-1,4;0,4;1,4;2,4;-1,5;0,5;1,5;2,5;-1,6;0,6;1,6;2,6;-1,7;0,7;1,7;2,7;-1,8;0,8;1,8;2,8;1,9;2,9"
_ARROW_PTS = np.array([[int(v) for v in p.split(",")] for p in _ARROW.split(";")])


def _arrow_tables():
    """For each of 120 turns (3 deg apart) and each small shift: where the arrow's white pixels
    would be, and the ring of pixels around it that should not be white. The arrow is turned
    about its own centre and allowed to sit up to 4 px off the map centre: turning it about the
    map centre left diagonal arrows off by a few pixels, and those read 90-100 deg wrong
    (PC 10-19 20:02: up-right read as down-right, so the camera was 'corrected' back and forth
    and the player spun in circles)."""
    pts = _ARROW_PTS.astype(float)
    pts = pts - pts.mean(axis=0)
    N, R, S = 41, 20, 4
    W = N + 2 * S                                   # the crop is padded by S on every side
    yy, xx = np.mgrid[-12:13, -12:13]
    disc = np.stack([xx[xx ** 2 + yy ** 2 <= 121], yy[xx ** 2 + yy ** 2 <= 121]], axis=1)
    shifts = np.array([(dx, dy) for dy in range(-S, S + 1) for dx in range(-S, S + 1)])
    sh = (shifts[:, 1] * W + shifts[:, 0])[:, None]
    tabs = []
    for k in range(120):
        th = math.radians(k * 3)
        cs, sn = math.cos(th), math.sin(th)
        X = np.rint(pts[:, 0] * cs - pts[:, 1] * sn).astype(int)
        Y = np.rint(pts[:, 0] * sn + pts[:, 1] * cs).astype(int)
        on = set(zip(X.tolist(), Y.tolist()))
        near = {(x + i, y + j) for x, y in on for i in (-1, 0, 1) for j in (-1, 0, 1)}
        ring = np.array([(x, y) for x, y in disc.tolist() if (x, y) not in near])
        onp = np.array(sorted(on))
        ip = (onp[:, 1] + R + S) * W + onp[:, 0] + R + S
        ir = (ring[:, 1] + R + S) * W + ring[:, 0] + R + S
        tabs.append((ip[None, :] + sh, ir[None, :] + sh))
    return tabs


_ARROW_TABS = None


def read_arrow(bgr41: np.ndarray):
    """Direction the arrow points, in radians (0 = east, +pi/2 = south), or None.
    bgr41: 41x41 crop centred on the minimap centre. (At the widest zoom other white bits -
    your room's outline, door tabs - lie around it.)"""
    global _ARROW_TABS
    if _ARROW_TABS is None:
        _ARROW_TABS = _arrow_tables()
    if bgr41 is None or bgr41.shape[0] != 41 or bgr41.shape[1] != 41:
        return None
    wm = np.pad(bgr41.min(axis=2) > 235, 4).ravel().astype(np.float32)
    best, best_k = -9.0, 0
    for k, (ip, ir) in enumerate(_ARROW_TABS):
        hit = wm[ip].mean(axis=1)
        sc = hit - wm[ir].mean(axis=1)
        sc[hit < 0.6] = -9.0
        j = int(sc.argmax())
        if sc[j] > best:
            best, best_k = float(sc[j]), k
    if best < 0.6:
        return None
    return wrap(math.radians(best_k * 3 - 90))

def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def has_minimap(disc_bgr: np.ndarray, buttons_bgr: np.ndarray | None) -> bool:
    """Dungeons have the minimap (a dark navy disc top-right); trials don't.
    disc_bgr: crop of radius 80 around the map centre. buttons_bgr: the strip with the
    two gold -/+ buttons (see hud.minimap_buttons_strip)."""
    N = disc_bgr.shape[0]
    R = (N - 1) // 2
    sub = disc_bgr[::4, ::4].astype(np.int16)
    yy, xx = np.mgrid[0:N:4, 0:N:4]
    m = (xx - R) ** 2 + (yy - R) ** 2 <= R * R
    b, g, r = sub[..., 0], sub[..., 1], sub[..., 2]
    navy = (r < 90) & (g < 80) & (b >= r) & (b < 140)
    darkish = navy | (classify(disc_bgr[::4, ::4]) > 0) | (sub.max(axis=2) < 40)
    if m.sum() == 0 or (darkish & m).sum() / m.sum() <= 0.75:
        return False
    if buttons_bgr is None:
        return True
    h, w = buttons_bgr.shape[:2]
    sq = 13
    halves = (buttons_bgr[:, :sq], buttons_bgr[:, w - sq:])
    ok = []
    for part in halves:
        pb = part[..., 0].astype(int)
        pg = part[..., 1].astype(int)
        pr = part[..., 2].astype(int)
        gold = (pr > 200) & (pg > 130) & (pg < 225) & (pb < 110)
        ok.append(gold.mean() >= 0.15)      # (the + button: its white cross takes up much of it)
    return all(ok)
