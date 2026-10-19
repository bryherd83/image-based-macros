"""Boss 'Drops' panel: found on every screenshot that has it, on none without it.
    python test_drops.py   (needs testdata/screens)
"""
import glob, os, sys
import cv2
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hud

T = hud.Templates()
files = glob.glob(os.path.join(HERE, "testdata", "screens", "*.jpg"))

hits = []
for p in files:
    f = cv2.imread(p)
    if f is not None and f.shape[1] == 1920 and T.find(f, "dropsx", min_frac=0.9):
        hits.append(os.path.basename(p))
print(f"{len(files)} screenshots, Drops panel found on {len(hits)}: {sorted(hits)}")

want = {"laptop-1017-030002-py-joining-dungeon.jpg", "laptop-1017-040002-py-joining-dungeon.jpg",
        "laptop-1017-121501-py-joining-trial.jpg", "laptop-1017-123002-py-joining-dungeon.jpg",
        "laptop-1017-120752-py-dungeon-finished.jpg"}
assert set(hits) == want, set(hits) ^ want
print("drops: ok")

# Defense mode's HEALTH heart: on the Defense screenshot, on nothing else
d = [os.path.basename(p) for p in glob.glob(os.path.join(HERE, "testdata", "screens", "*.*"))
     if p.lower().endswith((".jpg", ".png")) and (lambda f: f is not None and f.shape[1] == 1920
                                                  and T.find(f, "defheart"))(cv2.imread(p))]
print("Defense HEALTH heart found on:", d)
assert sorted(d) == ["laptop-1017-defense-run.png", "pc-1019-new-ui-defense.png", "pc-1019-new-ui-dg-28.png"], d
print("defense: ok")

# new UI (10-19): the Worlds button's new look is found as "worlds"
_n = T.find(cv2.imread(os.path.join(HERE, "testdata", "screens", "pc-1019-new-ui-lobby.png")), "worlds")
print("new-UI Worlds button at", _n)
assert _n and abs(_n[0] - 223) < 6 and abs(_n[1] - 509) < 6
print("new UI: ok")
