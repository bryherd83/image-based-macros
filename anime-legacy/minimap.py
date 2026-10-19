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
                # (your own room's white outline runs along its whole side: there, count the
                # lavender of the tab itself instead)
                if g[0]:
                    lav = door[max(0, round(my - 0.3 * s)):round(my + 0.3 * s) + 1,
                               max(0, round(mx - hg - 2)):round(mx + hg + 2) + 1]
                else:
                    lav = door[max(0, round(my - hg - 2)):round(my + hg + 2) + 1,
                               max(0, round(mx - 0.3 * s)):round(mx + 0.3 * s) + 1]
                tab = nm >= 2 and mid >= 0.35 and (n1 == 0 or e1 < 0.6 * mid) and (n2 == 0 or e2 < 0.6 * mid)
                if tab or int(lav.sum()) >= (3 if (0, 0) in ((a, b), k2) or s >= 20 else 2):
                    doors.add(((a, b), k2))
                    doors.add((k2, (a, b)))
                elif k != HIDDEN and cells[k2] != HIDDEN and nm >= 2 and mid < 0.1:
                    walls.add(((a, b), k2))
                    walls.add((k2, (a, b)))
        return MapView(s=s, p=p, cells=cells, doors=doors, walls=walls, offx=R - gx, offy=R - gy,
                       edges=len(full), raw=None)


# ---------------- The arrow in the middle of the minimap ----------------
# The new UI's white arrow (taken from a screenshot), pointing north, around the map centre.
# It is the same size at every zoom.
_ARROW = "1,-7;1,-6;0,-5;1,-5;2,-5;-1,-4;0,-4;1,-4;2,-4;3,-4;-2,-3;-1,-3;0,-3;1,-3;2,-3;3,-3;-2,-2;-1,-2;0,-2;1,-2;2,-2;3,-2;4,-2;-3,-1;-2,-1;-1,-1;0,-1;1,-1;2,-1;3,-1;4,-1;5,-1;-4,0;-3,0;-2,0;-1,0;0,0;1,0;2,0;3,0;4,0;5,0;-4,1;-3,1;-2,1;-1,1;0,1;1,1;2,1;3,1;4,1;5,1;6,1;-5,2;-4,2;-3,2;-2,2;-1,2;0,2;1,2;2,2;3,2;4,2;5,2;6,2;-2,3;-1,3;0,3;1,3;2,3;3,3;4,3;5,3;6,3;-1,4;0,4;1,4;2,4;-1,5;0,5;1,5;2,5;-1,6;0,6;1,6;2,6;-1,7;0,7;1,7;2,7;-1,8;0,8;1,8;2,8;1,9;2,9"
_ARROW_PTS = np.array([[int(v) for v in p.split(",")] for p in _ARROW.split(";")])


def _arrow_tables():
    pts = _ARROW_PTS
    dark = []
    for x in range(-12, 13):
        for y in range(-12, 13):
            if x * x + y * y > 144:
                continue
            if np.any((np.abs(pts[:, 0] - x) <= 1) & (np.abs(pts[:, 1] - y) <= 1)):
                continue
            dark.append((x, y))
    dark = np.array(dark)
    R, N = 20, 41
    tabs = []
    for k in range(120):
        th = math.radians(k * 3)
        cs, sn = math.cos(th), math.sin(th)
        out = []
        for P in (pts, dark):
            X = np.rint(P[:, 0] * cs - P[:, 1] * sn).astype(int) + R
            Y = np.rint(P[:, 0] * sn + P[:, 1] * cs).astype(int) + R
            ok = (X >= 0) & (Y >= 0) & (X < N) & (Y < N)
            out.append((Y[ok] * N + X[ok], len(P)))
        tabs.append(out)
    return tabs


_ARROW_TABS = None


def read_arrow(bgr41: np.ndarray):
    """Direction the arrow points, in radians (0 = east, +pi/2 = south), or None.
    bgr41: 41x41 crop centred on the minimap centre. (At the widest zoom other white bits -
    your room's outline, door tabs - lie around it; the dark-ring penalty is kept mild.)"""
    global _ARROW_TABS
    if _ARROW_TABS is None:
        _ARROW_TABS = _arrow_tables()
    wm = (bgr41.min(axis=2) > 235).ravel()
    best, best_k = -9.0, 0
    for k, ((ip, nT), (idk, nD)) in enumerate(_ARROW_TABS):
        sc = wm[ip].sum() / nT - 0.5 * wm[idk].sum() / nD
        if sc > best:
            best, best_k = sc, k
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
