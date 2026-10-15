"""Minimap reader for Anime Legacy dungeons (numpy port of the AHK ReadMap/ParseMap).

The minimap (top-right) is north-up and centred on you:
  blue = spawn, green = cleared, grey = not done, gold = treasure,
  white bar in the gap between two rooms = a door.
Everything here works on a BGR numpy crop of the minimap: no screen access,
so it can be tested on saved screenshots.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# Positions on a 1920x1080 client area
REF_W, REF_H = 1920, 1080
MAP_CX, MAP_CY, MAP_R = 1773, 162, 95
MAP_MINUS_X, MAP_PLUS_X, MAP_BUTTONS_Y = 1686, 1859, 243

NONE, SPAWN, CLEARED, TODO, TREASURE, WHITE = 0, 1, 2, 3, 4, 5
HIDDEN = 9  # your own room, hidden under the arrow
ARROW_R2 = 169  # the arrow covers r <= 13 around the centre

NAMES = {SPAWN: "spawn", CLEARED: "cleared", TODO: "not done", TREASURE: "treasure", HIDDEN: "hidden"}


def classify(bgr: np.ndarray) -> np.ndarray:
    """Pixel classes, same colour rules as the AHK MapClassify (white wins, then blue...)."""
    b = bgr[..., 0].astype(np.int16)
    g = bgr[..., 1].astype(np.int16)
    r = bgr[..., 2].astype(np.int16)
    k = np.zeros(b.shape, np.uint8)
    k[(r > 235) & (np.abs(g - 200) < 25) & (b < 80)] = TREASURE
    k[(np.abs(r - 128) < 10) & (np.abs(g - 128) < 10) & (np.abs(b - 128) < 10)] = TODO
    k[(np.abs(r - 70) < 30) & (g > 185) & (np.abs(b - 90) < 35)] = CLEARED
    k[(np.abs(r - 60) < 30) & (np.abs(g - 140) < 30) & (b > 215)] = SPAWN
    k[(r > 235) & (g > 235) & (b > 235)] = WHITE
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
    edges: int = 0              # how many strong room edges were used (quality)
    raw: np.ndarray | None = field(default=None, repr=False)

    def here(self) -> int:
        return self.cells.get((0, 0), HIDDEN)


def _runs(a: np.ndarray, R: int, axis_rows: bool, hist: dict, starts: list):
    """Collects run lengths of same-coloured room pixels and where runs start."""
    N = a.shape[0]
    rr = R * R
    for y in range(N):
        v = a[y]
        ch = np.flatnonzero(v[1:] != v[:-1]) + 1
        st = np.concatenate(([0], ch))
        en = np.concatenate((ch, [N]))
        vals = v[st]
        keep = (vals >= 1) & (vals <= 4)
        if not keep.any():
            continue
        st, en = st[keep], en[keep]
        ln = en - st
        for L in ln[ln >= 8].tolist():
            hist[L] = hist.get(L, 0) + 1
        ok = st > 0
        st = st[ok]
        if st.size:
            # not where the circle's rim cuts a room
            d = (st - 1 - R) ** 2 + (y - R) ** 2
            starts.extend(st[d <= rr].tolist())


def _strong_edges(vals: list, s: int):
    if not vals:
        return []
    c = np.bincount(np.asarray(vals))
    thr = max(4, 0.5 * s)
    out = []
    for v in np.flatnonzero(c).tolist():
        n = c[v]
        a = c[v - 1] if v >= 1 else 0
        b = c[v + 1] if v + 1 < c.size else 0
        if n + a + b >= thr and n >= a and n >= b:
            out.append((v, int(n)))
    return out


def _edge_pitch(sl, st, s):
    diffs = []
    for e in (sl, st):
        for i in range(len(e)):
            for j in range(i + 1, len(e)):
                d = e[j][0] - e[i][0]
                for k in (1, 2, 3):
                    if 1.2 * s <= d / k <= 1.6 * s:
                        diffs.append(d / k)
    if not diffs:
        return 0.0
    diffs.sort()
    return diffs[(len(diffs) - 1) // 2]


def _phase(vals, p):
    if not vals:
        return 0.0
    v = np.asarray(vals, float)
    t = 2 * math.pi * v / p
    ph = math.atan2(np.sin(t).sum(), np.cos(t).sum()) / (2 * math.pi) * p
    return ph % p


def _edge_phase(edges, allv, p):
    if not edges:
        return _phase(allv, p)
    best_w, best = -1, []
    for e in edges:
        r = e[0] % p
        w, mem = 0, []
        for x in edges:
            d = abs((x[0] % p) - r)
            d = min(d, p - d)
            if d <= 2.5:
                w += x[1]
                mem.append(x)
        if w > best_w:
            best_w, best = w, mem
    cs = sum(x[1] * math.cos(2 * math.pi * x[0] / p) for x in best)
    sn = sum(x[1] * math.sin(2 * math.pi * x[0] / p) for x in best)
    return (math.atan2(sn, cs) / (2 * math.pi) * p + p) % p


class MapReader:
    """Keeps the room spacing between frames (it is noisy from a single frame)."""

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
        room = np.where((cls >= 1) & (cls <= 4), cls, 0).astype(np.uint8)

        hist: dict = {}
        lefts: list = []
        tops: list = []
        _runs(room, R, True, hist, lefts)
        _runs(np.ascontiguousarray(room.T), R, False, hist, tops)
        if len(lefts) < 6 or len(tops) < 6 or not hist:
            return None
        best, s = 0, 0
        for L, n in hist.items():
            sc = n + hist.get(L - 1, 0) + hist.get(L + 1, 0)
            if sc > best:
                best, s = sc, L
        sl, st = _strong_edges(lefts, s), _strong_edges(tops, s)
        p_new = _edge_pitch(sl, st, s)
        if self.p == 0 or abs(self.s - s) > 1:
            self.p = p_new or self.pitch_by_size.get(s, 1.34 * s)
            self.s = s
        elif p_new:
            self.p = self.p * 0.7 + p_new * 0.3
        p = self.p
        if p_new:
            old = self.pitch_by_size.get(s)
            self.pitch_by_size[s] = p_new if old is None else old * 0.8 + p_new * 0.2
        phx, phy = _edge_phase(sl, lefts, p), _edge_phase(st, tops, p)
        ci = math.floor((R - phx + (p - s) / 2) / p)
        cj = math.floor((R - phy + (p - s) / 2) / p)

        cells = {}
        span = int(R / p) + 2
        step = max(1, round(s / 12))
        for i in range(ci - span, ci + span + 1):
            x1, x2 = math.floor(phx + i * p + s * 0.2), math.floor(phx + i * p + s * 0.8)
            if x2 < 0 or x1 >= N:
                continue
            xs = np.arange(x1, x2 + 1, step)
            xs = xs[(xs >= 0) & (xs < N)]
            if not xs.size:
                continue
            for j in range(cj - span, cj + span + 1):
                y1, y2 = math.floor(phy + j * p + s * 0.2), math.floor(phy + j * p + s * 0.8)
                if y2 < 0 or y1 >= N:
                    continue
                ys = np.arange(y1, y2 + 1, step)
                ys = ys[(ys >= 0) & (ys < N)]
                if not ys.size:
                    continue
                sub_in = inside[np.ix_(ys, xs)]
                tot = int(sub_in.sum())
                if tot < 4:
                    continue
                sub = room[np.ix_(ys, xs)][sub_in]
                cnt = np.bincount(sub, minlength=5)[1:5]
                bk = int(np.argmax(cnt))
                frac = cnt[bk] / tot
                own = (i == ci and j == cj)
                if cnt[bk] > 0 and (frac >= 0.25 or (own and frac >= 0.08)):
                    cells[(i - ci, j - cj)] = bk + 1
        if (0, 0) not in cells:
            cells[(0, 0)] = HIDDEN

        white = (cls == WHITE) & (d2 > ARROW_R2)
        seen_m = inside & (d2 > ARROW_R2)
        doors, walls = set(), set()

        def gap(x1, y1, x2, y2):
            xa, xb = max(0, round(x1)), min(N - 1, round(x2))
            ya, yb = max(0, round(y1)), min(N - 1, round(y2))
            area = max(0, round(x2) - round(x1) + 1) * max(0, round(y2) - round(y1) + 1)
            if xa > xb or ya > yb:
                return 0.0, 0, area
            sm = seen_m[ya:yb + 1, xa:xb + 1]
            t = int(sm.sum())
            w = int((white[ya:yb + 1, xa:xb + 1] & sm).sum())
            return (w / t if t else 0.0), t, area

        for (a, b), k in cells.items():
            lx = phx + (a + ci) * p
            ty = phy + (b + cj) * p
            for g in ((1, 0), (0, 1)):
                k2 = (a + g[0], b + g[1])
                if k2 not in cells:
                    continue
                if g[0]:
                    gw = gap(lx + s + 1, ty + s * 0.2, lx + p - 1, ty + s * 0.8)
                    gl = gap(lx + s + 1, ty + s * 0.05, lx + p - 1, ty + s * 0.95)
                else:
                    gw = gap(lx + s * 0.2, ty + s + 1, lx + s * 0.8, ty + p - 1)
                    gl = gap(lx + s * 0.05, ty + s + 1, lx + s * 0.95, ty + p - 1)
                if gw[1] >= 4 and gw[0] > 0.3:
                    doors.add(((a, b), k2))
                    doors.add((k2, (a, b)))
                elif (k != HIDDEN and cells[k2] != HIDDEN and gl[1] >= 0.4 * gl[2]
                      and gl[1] >= 6 and gl[0] < 0.05):
                    walls.add(((a, b), k2))
                    walls.add((k2, (a, b)))
        offx = R - (phx + ci * p + s / 2)
        offy = R - (phy + cj * p + s / 2)
        return MapView(s=s, p=p, cells=cells, doors=doors, walls=walls, offx=offx, offy=offy,
                       edges=len(sl) + len(st), raw=None)


# ---------------- The arrow in the middle of the minimap ----------------
_ARROW = "0,-10;-1,-9;0,-9;1,-9;-1,-8;0,-8;1,-8;2,-8;-2,-7;-1,-7;0,-7;1,-7;2,-7;-3,-6;-2,-6;-1,-6;0,-6;1,-6;2,-6;3,-6;-3,-5;-2,-5;-1,-5;0,-5;1,-5;2,-5;3,-5;-4,-4;-3,-4;-2,-4;-1,-4;0,-4;1,-4;2,-4;3,-4;4,-4;-5,-3;-4,-3;-3,-3;-2,-3;-1,-3;0,-3;1,-3;2,-3;3,-3;4,-3;5,-3;-5,-2;-4,-2;-3,-2;-2,-2;-1,-2;0,-2;1,-2;2,-2;3,-2;4,-2;5,-2;-6,-1;-5,-1;-4,-1;-3,-1;-2,-1;-1,-1;0,-1;1,-1;2,-1;3,-1;4,-1;5,-1;6,-1;-6,0;-5,0;-4,0;-3,0;-2,0;-1,0;0,0;1,0;2,0;3,0;4,0;5,0;6,0;7,0;-7,1;-6,1;-5,1;-4,1;-3,1;-2,1;-1,1;0,1;1,1;2,1;3,1;4,1;5,1;6,1;7,1;-8,2;-7,2;-6,2;-5,2;-4,2;-3,2;-2,2;-1,2;0,2;1,2;2,2;3,2;4,2;5,2;6,2;7,2;8,2;-3,3;-2,3;-1,3;0,3;1,3;2,3;3,3;-2,4;-1,4;0,4;1,4;2,4;-2,5;-1,5;0,5;1,5;2,5;-2,6;-1,6;0,6;1,6;2,6;-2,7;-1,7;0,7;1,7;2,7;-2,8;-1,8;0,8;1,8;2,8;-2,9;-1,9;0,9;1,9;2,9;-2,10;-1,10;0,10;1,10;2,10"
_ARROW_PTS = np.array([[int(v) for v in p.split(",")] for p in _ARROW.split(";")])


def _arrow_tables():
    pts = _ARROW_PTS
    dark = []
    for x in range(-13, 14):
        for y in range(-13, 14):
            if x * x + y * y > 169:
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
    bgr41: 41x41 crop centred on the minimap centre."""
    global _ARROW_TABS
    if _ARROW_TABS is None:
        _ARROW_TABS = _arrow_tables()
    wm = ((bgr41[..., 0] > 230) & (bgr41[..., 1] > 230) & (bgr41[..., 2] > 230)).ravel()
    best, best_k = -9.0, 0
    for k, ((ip, nT), (idk, nD)) in enumerate(_ARROW_TABS):
        sc = wm[ip].sum() / nT - 0.5 * wm[idk].sum() / nD
        if sc > best:
            best, best_k = sc, k
    if best < 0.7:
        return None
    return wrap(math.radians(best_k * 3 - 90))


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def has_minimap(disc_bgr: np.ndarray, buttons_bgr: np.ndarray | None) -> bool:
    """Dungeons have the minimap (a dark disc top-right); trials don't.
    disc_bgr: crop of radius 80 around the map centre. buttons_bgr: the strip with the
    two gold -/+ buttons (see Screen.minimap_buttons_strip)."""
    N = disc_bgr.shape[0]
    R = (N - 1) // 2
    sub = disc_bgr[::4, ::4].astype(np.int16)
    yy, xx = np.mgrid[0:N:4, 0:N:4]
    m = (xx - R) ** 2 + (yy - R) ** 2 <= R * R
    b, g, r = sub[..., 0], sub[..., 1], sub[..., 2]
    darkish = ((r < 50) & (g < 60) & (b < 50)) | (classify(disc_bgr[::4, ::4]) > 0)
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
        ok.append(gold.mean() >= 0.3)
    return all(ok)
