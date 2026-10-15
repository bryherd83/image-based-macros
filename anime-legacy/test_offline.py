"""Offline checks on the macro's own log screenshots (no game needed).

    .venv\\Scripts\\python.exe test_offline.py            # minimap on every screenshot
    .venv\\Scripts\\python.exe test_offline.py --hud      # buttons, counters, popups
"""
import glob
import os
import sys
import time

import cv2
import numpy as np

import minimap as mm

# a kept copy of the log screenshots (the farm deletes its own screenshots after 24 h)
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "testdata", "screens")
if not os.path.isdir(LOG_DIR):
    LOG_DIR = os.path.expandvars(r"%USERPROFILE%\Pictures\Screenshots\anime-legacy-log")


def crop(img, cx, cy, r):
    return img[cy - r:cy + r + 1, cx - r:cx + r + 1]


def strip(img):
    x1, x2 = mm.MAP_MINUS_X - 6, mm.MAP_PLUS_X + 6
    y = mm.MAP_BUTTONS_Y - 2 - 6
    return img[y:y + 13, x1:x2 + 1]


def main_map(files):
    reader = mm.MapReader()
    n = ok = 0
    times = []
    for f in files:
        img = cv2.imread(f)
        if img is None or img.shape[:2] != (1080, 1920):
            continue
        disc = crop(img, mm.MAP_CX, mm.MAP_CY, 80)
        if not mm.has_minimap(disc, strip(img)):
            continue
        n += 1
        reader.reset()
        t = time.perf_counter()
        v = reader.parse(crop(img, mm.MAP_CX, mm.MAP_CY, mm.MAP_R))
        times.append(time.perf_counter() - t)
        a = mm.read_arrow(crop(img, mm.MAP_CX, mm.MAP_CY, 20))
        name = os.path.basename(f)
        if v is None:
            print(f"{name:45s} map: unreadable")
            continue
        ok += 1
        todo = sum(1 for c in v.cells.values() if c in (mm.TODO, mm.TREASURE))
        print(f"{name:45s} s={v.s:3d} p={v.p:5.1f} rooms={len(v.cells):2d} todo={todo} doors={len(v.doors)//2} "
              f"walls={len(v.walls)//2} here={mm.NAMES.get(v.here())} off=({v.offx:+5.1f},{v.offy:+5.1f}) "
              f"edges={v.edges} arrow={'-' if a is None else round(np.degrees(a))}")
    if times:
        print(f"\n{ok}/{n} minimap screenshots read; parse time median {1000*np.median(times):.1f} ms, max {1000*max(times):.1f} ms")


if __name__ == "__main__":
    files = sorted(glob.glob(os.path.join(LOG_DIR, "*.jpg")))
    if "--hud" in sys.argv:
        import test_hud
        test_hud.main(files)
    else:
        main_map(files)
