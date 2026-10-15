"""HUD checks on the log screenshots: which buttons are seen, counters, popups."""
import collections
import os
import time

import cv2
import numpy as np

import hud


def main(files):
    T = hud.Templates()
    seen = collections.Counter()
    total = 0
    times = collections.defaultdict(list)
    rows = []
    for f in files:
        img = cv2.imread(f)
        if img is None or img.shape[:2] != (1080, 1920):
            continue
        total += 1
        found = {}
        for name in ("worlds", "leave", "spawn", "roomhud", "close", "joinevent", "wave9"):
            t = time.perf_counter()
            # JPEG screenshots: allow a little more noise than live frames
            found[name] = T.find(img, name, min_frac=0.93)
            times[name].append(time.perf_counter() - t)
            if found[name]:
                seen[name] += 1
        t = time.perf_counter()
        pop = hud.find_popup(img)
        times["popup"].append(time.perf_counter() - t)
        if pop:
            seen["popup:" + pop.kind] += 1
        en = wv = None
        if found["roomhud"]:
            t = time.perf_counter()
            en, wv = hud.read_counter(img, "enemies"), hud.read_counter(img, "wave")
            times["counters"].append(time.perf_counter() - t)
            seen["enemies read"] += en is not None
            seen["wave read"] += wv is not None
        mapok = hud.has_minimap(img)
        seen["minimap"] += mapok
        rows.append((os.path.basename(f), found, pop, en, wv, mapok))
    print(f"{total} screenshots")
    for k, v in sorted(seen.items()):
        print(f"  {k:16s} {v}")
    print("times (ms, median/max):")
    for k, v in times.items():
        print(f"  {k:10s} {1000*np.median(v):6.2f} / {1000*max(v):6.2f}")
    # a few samples
    for name, found, pop, en, wv, mapok in rows:
        if any(x in name for x in ("070629", "183421", "Joining", "Trial-wave", "Closed", "every-5min")) or pop:
            fs = " ".join(k for k, v in found.items() if v)
            print(f"{name:45s} [{fs}] pop={pop.kind if pop else '-'} enemies={en.text if en else '-'} wave={wv.text if wv else '-'} map={mapok}")
