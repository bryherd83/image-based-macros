"""New minimap (game UI update 10-19), on the PC screenshots: found only in dungeons, rooms,
doors and the arrow read right.
    python test_newmap.py
"""
import math, os, sys
import cv2
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hud  # noqa: E402
import minimap as mm  # noqa: E402

S = os.path.join(HERE, "testdata", "screens", "pc-1019-new-ui-%s.png")
C, G, Tt, SP, TR = mm.CLEARED, mm.TODO, mm.TODO, mm.SPAWN, mm.TREASURE
# (screenshot, arrow degrees (0 east, 90 south), cells that must be read, doors, walls)
CASES = [
    ("dg-32", 90, {(0, -2): SP, (-2, -1): C, (-1, -1): C, (0, -1): C, (1, -1): G, (0, 0): C},
     [((0, -2), (0, -1)), ((0, -1), (0, 0)), ((-1, -1), (0, -1)), ((0, -1), (1, -1))], []),
    ("dg-33", 0, {(-1, -1): SP, (0, -1): G, (-2, 0): C, (-1, 0): C, (0, 0): C, (1, 0): G, (-1, 1): C, (0, 1): G},
     [((-1, 0), (0, 0)), ((0, 0), (1, 0)), ((0, 0), (0, 1)), ((0, -1), (0, 0)), ((-1, -1), (-1, 0))],
     [((-1, -1), (0, -1))]),
    ("dg-34", 0, {(1, 0): TR, (0, 0): C}, [((0, 0), (1, 0))], []),
    ("dg-35", 0, {(0, 0): G, (1, 0): G, (-1, 0): C}, [((-1, 0), (0, 0)), ((0, 0), (1, 0))], [((-2, 0), (-1, 0))]),
    ("dg-37", 70, {}, [], []),
]
for name, deg, cells, doors, walls in CASES:
    f = cv2.imread(S % name)
    assert hud.has_minimap(f), name
    v = mm.MapReader().parse(hud.minimap_crop(f))
    a = mm.read_arrow(hud.minimap_crop(f, 20))
    assert v is not None and a is not None, name
    err = abs(mm.wrap(a - math.radians(deg)))
    print(f"{name}: s={v.s} p={v.p:.1f} arrow {math.degrees(a):+.0f} (want {deg:+d}) rooms {len(v.cells)} "
          f"doors {len(v.doors) // 2} walls {len(v.walls) // 2}")
    assert err < math.radians(15), (name, math.degrees(a))
    for k, c in cells.items():
        assert v.cells.get(k) == c, (name, k, v.cells.get(k), c)
    for d in doors:
        assert d in v.doors, (name, "door", d)
    for w in walls:
        assert w in v.walls and w not in v.doors, (name, "wall", w)
# zoomed out (13 px rooms): a whole map's worth of rooms
assert len(mm.MapReader().parse(hud.minimap_crop(cv2.imread(S % "dg-37"))).cells) >= 35
# no minimap: lobby, trial, Defense, lobby with a popup
for name in ("lobby", "dungeon-24", "dungeon-25", "dungeon-26", "defense", "dg-28"):
    assert not hud.has_minimap(cv2.imread(S % name)), name
# PC 10-19 14:02: the + button looked lighter (mouse over it) and the dungeon was taken for a
# trial; these are all dungeon frames
for name in ("1019-140205-py-dungeon-started.jpg", "1019-140211-py-trial-started.jpg",
             "1019-140224-py-dungeon-popup-due.jpg", "1019-140236-py-dungeon-popup-due.jpg", "bug-38.png"):
    p = os.path.join(HERE, "testdata", "screens", "pc-1019-new-ui-" + name)
    assert hud.has_minimap(cv2.imread(p)), name
# PC 10-19 14:33: standing in the spawn room after Spawn (ENEMIES still showing 3/4): the map
# must say so, so the farm doesn't "fight" there
for n in (42, 43, 44):
    v = mm.MapReader().parse(hud.minimap_crop(cv2.imread(S % ("spawnstuck-%d" % n))))
    assert v.here() == mm.SPAWN and v.cells.get((0, 1)) == mm.CLEARED and ((0, 0), (0, 1)) in v.doors, n
# every key the farm may press is known (the mount key "m" was missing: crash on every press)
import winio  # noqa: E402
assert all(c in winio.SCAN for c in "abcdefghijklmnopqrstuvwxyz0123456789")
print("new minimap: ok")
