"""Reading the game's HUD from a frame: buttons (pictures), counters (digits), popups.

All functions take a BGR numpy frame of the Roblox client area. Coordinates are
client pixels. Positions written as 1920x1080 numbers are scaled to the real size.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

import cv2
import numpy as np

import minimap as mm

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")

# Where each picture is looked for: (left, top, right, bottom) as fractions of the window,
# and how different a pixel may be (like AutoHotkey's ImageSearch *n)
REGIONS = {
    "worlds": ((0.00, 0.40, 0.25, 0.80), 70),
    "dice": ((0.00, 0.00, 1.00, 1.00), 70),
    "create": ((0.00, 0.00, 1.00, 1.00), 70),
    "play": ((0.00, 0.00, 1.00, 1.00), 70),
    "close": ((0.70, 0.08, 0.92, 0.38), 100),
    "leave": ((0.30, 0.00, 0.70, 0.20), 70),
    "spawn": ((0.30, 0.00, 0.70, 0.20), 70),
    "wave9": ((0.50, 0.00, 0.70, 0.10), 70),
    "joinevent": ((0.20, 0.10, 0.80, 0.60), 70),
    "roomhud": ((0.50, 0.00, 0.70, 0.12), 50),
    "dungeonpop": ((0.15, 0.35, 0.85, 0.95), 70),
    "trialpop": ((0.15, 0.35, 0.85, 0.95), 70),
}


class Templates:
    def __init__(self, folder: str = ASSETS):
        self.img = {}
        for name in REGIONS:
            path = os.path.join(folder, name + ".png")
            im = cv2.imread(path, cv2.IMREAD_COLOR)
            if im is not None:
                self.img[name] = im

    def find(self, frame: np.ndarray, name: str, region=None, tol=None, min_frac=0.97):
        """Centre (x, y) of the picture inside frame, or None."""
        frac, c = self.match(frame, name, region, tol)
        return c if c is not None and frac >= min_frac else None

    def match(self, frame: np.ndarray, name: str, region=None, tol=None):
        """(share of pixels that match, centre (x, y)) of the best spot for the picture, or
        (0.0, None). find() needs a share of 0.97."""
        tpl = self.img.get(name)
        if tpl is None or frame is None:
            return 0.0, None
        H, W = frame.shape[:2]
        reg, t0 = REGIONS[name]
        if region is not None:
            reg = region
        tol = t0 if tol is None else tol
        x1, y1 = round(W * reg[0]), round(H * reg[1])
        x2, y2 = round(W * reg[2]), round(H * reg[3])
        sub = frame[y1:y2, x1:x2]
        th, tw = tpl.shape[:2]
        if sub.shape[0] < th or sub.shape[1] < tw:
            return 0.0, None
        res = cv2.matchTemplate(sub, tpl, cv2.TM_SQDIFF)
        _, _, loc, _ = cv2.minMaxLoc(res)
        fx, fy = loc
        patch = sub[fy:fy + th, fx:fx + tw].astype(np.int16)
        diff = np.abs(patch - tpl.astype(np.int16)).max(axis=2)
        return float((diff <= tol).mean()), (x1 + fx + tw // 2, y1 + fy + th // 2)

    def size(self, name):
        th, tw = self.img[name].shape[:2]
        return tw, th


# ---------------- Counters: ENEMIES a/b and WAVE (or ROOM) a/b ----------------
_DIGITS = {
    "0": (13, 15, "000001110000000011111110000011111111100011111011111001111000111100111100011110111100000111111110000011111111000001111011110001111001111000111100111110111110001111111110000011111110000000011100000"),
    "1": (6, 15, "111111111111111111001111001111001111001111001111001111001111001111001111001111001111001111"),
    "2": (12, 15, "000011100000011111111000111111111100111111111110001000011110000000011110000000111100000001111100000011111000000111110000001111100000011111100000111111111111111111111111111111111111"),
    "3": (11, 15, "111111111111111111111111111111111000001111100000011110000001111100000011111100000111111100001111111000000011110000000111101110011111111111111101111111110000011110000"),
    "4": (13, 15, "000000111100000000111100000000111110000000011110000000011110000000011111000000001111011110001111001111001111110111110111111111111111111111111111111111111111000000011110000000001111000000000111100"),
    "5": (11, 15, "001111111100011111111000111111110011111000000111100000001111111000011111111100111111111100000011111000000011110000000111101110011111011111111101111111110000011110000"),
    "6": (12, 15, "000000111100000111111111001111111110011111110110011110000000011110111000111111111110111111111111111111011111111110001111011110001111011111011111001111111111000111111110000001110000"),
    "7": (12, 15, "111111111111111111111111111111111111111100011111111100011111111100011110000000111110000000111100000001111100000001111000000011111000000011111000000011110000000111110000000111100000"),
    "8": (12, 15, "000011110000001111111100011111111110011111111111011110001111011110011110001111111110001111111110011110001111111100001111111110001111011111011111011111111111001111111110000001110000"),
    "9": (12, 15, "000011100000001111111100011111111110011111011111111100001111111110001111011111111111011111111111001111111111000000001111000000011111001101111110011111111100011111111000000111100000"),
    "/": (9, 20, "000000111000000111000001111000001110000001110000011110000011100000011100000111100000111000000111000001111000001110000001110000011110000011100000011100000111100000111000000111000000"),
}
DIGITS = {}
for ch, (w, h, s) in _DIGITS.items():
    DIGITS[ch] = (np.frombuffer(s.encode(), np.uint8).reshape(h, w) == ord("1"), 5 if ch == "/" else 8)


@dataclass
class Counter:
    a: int
    b: int
    text: str


def read_counter(frame: np.ndarray, which: str) -> Counter | None:
    """Reads 'a/b' from the ENEMIES box ('enemies') or the WAVE/ROOM box ('wave')."""
    H, W = frame.shape[:2]
    bx, bw = (690, 110) if which == "enemies" else (1140, 100)
    bh = 30
    x0, y0 = round(bx * W / 1920), round(40 * H / 1080)
    box = frame[y0:y0 + bh, x0:x0 + bw]
    if box.shape[0] < bh or box.shape[1] < bw:
        return None
    m = (box[..., 0] > 215) & (box[..., 1] > 215) & (box[..., 2] > 215)
    col_on = m.any(axis=0)
    cands = []
    for ch, (bits, top) in DIGITS.items():
        th, tw = bits.shape
        lim = math.floor(bits.size * 0.12)
        for y in range(top - 1, top + 2):
            if y < 0 or y + th > bh:
                continue
            win = np.lib.stride_tricks.sliding_window_view(m[y:y + th], (th, tw))[0]  # (bw-tw+1, th, tw)
            bad = (win != bits).sum(axis=(1, 2))
            for x in np.flatnonzero((bad <= lim) & col_on[:bad.size]).tolist():
                cands.append((bad[x] / bits.size, x, tw, ch))
    cands.sort()
    chosen = []
    for c in cands:
        if all(min(c[1] + c[2], d[1] + d[2]) - max(c[1], d[1]) < 0.4 * min(c[2], d[2]) for d in chosen):
            chosen.append(c)
    chosen.sort(key=lambda c: c[1])
    s = "".join(c[3] for c in chosen)
    parts = s.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    try:
        return Counter(int(parts[0]), int(parts[1]), s)
    except ValueError:
        return None


# ---------------- DPS meter (top-left): is anything being hit right now? ----------------
# The text is white with a black outline and centred at x ~190, so a bigger number makes it
# wider: 'DPS: 0' is ~100 px wide, 'DPS: 1.01M' ~150, 'DPS: 95.44B' ~180 (1920x1080).
DPS_BOX = (80, 238, 320, 280)
DPS_CENTRE_X = 190
DPS_HIT_WIDTH = 125


def dps_width(frame: np.ndarray) -> int | None:
    """Width of the DPS text in 1920x1080 pixels, or None if it isn't on screen."""
    sx, sy = map_scale(frame)
    x0, y0 = round(DPS_BOX[0] * sx), round(DPS_BOX[1] * sy)
    x1, y1 = round(DPS_BOX[2] * sx), round(DPS_BOX[3] * sy)
    box = frame[y0:y1, x0:x1]
    if box.size == 0:
        return None
    white = box.min(axis=2) > 215
    outline = cv2.dilate((box.max(axis=2) < 70).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    cols = np.flatnonzero((white & outline).sum(axis=0) >= 2)    # white strokes beside a black outline
    if cols.size == 0:
        return None
    blocks, start, prev = [], cols[0], cols[0]
    for c in cols[1:]:
        if c - prev > 14 * sx:              # letters of one text are closer than this
            blocks.append((start, prev))
            start = c
        prev = c
    blocks.append((start, prev))
    cx = (DPS_CENTRE_X - DPS_BOX[0]) * sx
    a, b = min(blocks, key=lambda bl: 0 if bl[0] <= cx <= bl[1] else min(abs(bl[0] - cx), abs(bl[1] - cx)))
    w = (b - a) / sx
    return round(w) if w >= 60 else None    # narrower than 'DPS: 0' = something else


def dps_hitting(frame: np.ndarray) -> bool | None:
    """True = damage is being done, False = the meter says ~0, None = can't read it."""
    w = dps_width(frame)
    return None if w is None else w >= DPS_HIT_WIDTH


# ---------------- has the view changed? (Spawn moved you) ----------------
# Mean difference of two view_sig()s, 0..255: standing still ~1 (0.7 in a trial room, 1 s
# apart), a different room 27-79 (measured on the log screenshots).
VIEW_MOVED = 15
VIEW_STILL = 5


def view_sig(frame: np.ndarray) -> np.ndarray:
    """Tiny grey thumbnail of the middle of the screen (the HUD edges left out)."""
    H, W = frame.shape[:2]
    mid = frame[int(H * 0.2):int(H * 0.8), int(W * 0.25):int(W * 0.75)]
    return cv2.resize(cv2.cvtColor(mid, cv2.COLOR_BGR2GRAY), (48, 27), interpolation=cv2.INTER_AREA).astype(np.int16)


def view_diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a - b).mean())


# ---------------- Dungeon / Trial popup (green check + pink X) ----------------
@dataclass
class Popup:
    kind: str  # 'dungeon', 'trial' or 'other'
    x: int
    y: int


def find_popup(frame: np.ndarray) -> Popup | None:
    H, W = frame.shape[:2]
    rx, ry = round(W * 0.15), round(H * 0.35)
    rw, rh = round(W * 0.70), round(H * 0.60)
    area = frame[ry:ry + rh, rx:rx + rw]
    sub = area[::3, ::3].astype(np.int16)
    b, g, r = sub[..., 0], sub[..., 1], sub[..., 2]
    green = (g > 200) & (r < 80) & (b < 140) & (g - b > 100)
    if not green.any():
        return None
    # join pixels that are within 12 px (4 cells of 3 px) of each other
    joined = cv2.dilate(green.astype(np.uint8), np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    result = None
    for i in range(1, n):
        ys, xs = np.nonzero((lab == i) & green)
        cnt = xs.size
        if cnt < 40:
            continue
        l, t, rr, bb = xs.min() * 3, ys.min() * 3, xs.max() * 3, ys.max() * 3
        w, h = rr - l + 3, bb - t + 3
        if not (30 <= w <= 90 and 30 <= h <= 90 and 0.7 <= w / h <= 1.4):
            continue
        # pink X to the right of the check
        xa, xb = rr + 5, min(rw, round(rr + w * 1.6))
        if xb <= xa:
            continue
        pz = area[t:bb:3, xa:xb:3].astype(np.int16)
        pink = ((pz[..., 2] > 180) & (pz[..., 1] < 70) & (pz[..., 0] > 50)).sum()
        if pink < 15:
            continue
        # icon on the left: purple portal = dungeon, brown shield = trial
        ya, yb = max(0, round(t - 0.2 * w)), min(rh, round(bb + 0.2 * w))
        xa, xb = max(0, round(l - 7.6 * w)), max(0, round(l - 5.2 * w))
        ic = area[ya:yb:2, xa:xb:2].astype(np.int16)
        if ic.size:
            cr, cg, cb = ic[..., 2], ic[..., 1], ic[..., 0]
            pur = ((cr > 110) & (cb > 170) & (cg < 100)).sum()
            brn = (~((cr > 110) & (cb > 170) & (cg < 100)) & (cr > 150) & (cg > 70) & (cg < 145) & (cb < 80)).sum()
        else:
            pur = brn = 0
        kind = "dungeon" if (pur > brn and pur >= 10) else "trial" if (brn > pur and brn >= 10) else "other"
        result = Popup(kind, rx + (l + rr) // 2, ry + (t + bb) // 2)
        if kind != "other":
            break
    return result


# ---------------- Minimap crops ----------------
def map_scale(frame):
    H, W = frame.shape[:2]
    return W / 1920, H / 1080


def minimap_crop(frame, r=mm.MAP_R):
    sx, sy = map_scale(frame)
    cx, cy = round(mm.MAP_CX * sx), round(mm.MAP_CY * sy)
    R = round(r * sy)
    return frame[cy - R:cy + R + 1, cx - R:cx + R + 1]


def minimap_buttons_strip(frame):
    sx, sy = map_scale(frame)
    x1, x2 = round((mm.MAP_MINUS_X - 6) * sx), round((mm.MAP_PLUS_X + 6) * sx)
    y = round((mm.MAP_BUTTONS_Y - 2 - 6) * sy)
    return frame[y:y + 13, x1:x2 + 1]


def covered(frame) -> bool:
    """Most of the screen is black: a full-screen game animation (the trait roll's "MYTHICAL
    TRAIT" card, a loading screen) is hiding the HUD for a moment."""
    if frame is None or frame.size == 0:
        return False
    small = frame[::8, ::8]
    return float((small.max(axis=2) < 25).mean()) > 0.75


def has_minimap(frame) -> bool:
    return mm.has_minimap(minimap_crop(frame, 80), minimap_buttons_strip(frame)) and compass_letters(frame)


def compass_letters(frame) -> bool:
    """The white N and S letters on the minimap's ring. A dark scene with gold text top-right
    (another player's "Mythical · Lvl. 45" title) passed the disc + gold-button check twice in
    laptop trials (10-16), and the trial broke off as a 'dungeon'. On 842 real minimap frames
    N/S are 16-33% white pixels; on those two, 0%."""
    sx, sy = map_scale(frame)
    R = round(11 * sy)
    for y in (50, 274):
        X, Y = round(mm.MAP_CX * sx), round(y * sy)
        box = frame[max(0, Y - R):Y + R, max(0, X - R):X + R]
        if box.size == 0 or (box.min(axis=2) > 190).mean() < 0.05:
            return False
    return True


def minimap_buttons(frame):
    """Client positions of the minimap's - and + buttons."""
    sx, sy = map_scale(frame)
    return ((round(mm.MAP_MINUS_X * sx), round(mm.MAP_BUTTONS_Y * sy)),
            (round(mm.MAP_PLUS_X * sx), round(mm.MAP_BUTTONS_Y * sy)))


def black_share(img) -> float:
    """Share of (nearly) pure black pixels."""
    if img is None or img.size == 0:
        return 0.0
    return float((img.max(axis=2) < 12).mean())


def spawn_hidden(frame, xy=(1080, 122)) -> bool:
    """The black-squares teleport animation is over the Spawn button (laptop 10-15: its picture
    then matched only 76%). The button itself has no black: 0% on every normal screenshot,
    82% under the animation."""
    if getattr(frame, "ndim", 0) != 3:
        return False
    x, y = xy
    return black_share(frame[max(0, y - 20):y + 20, max(0, x - 50):x + 50]) > 0.05
