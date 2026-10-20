"""A remembered room the minimap shows isn't there is forgotten with its doors (PC 10-19 20:12:
kept walking into the south wall towards a room that didn't exist).
    python test_phantom.py
"""
import os, sys
import cv2
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hud, minimap as mm, dungeon as dg  # noqa: E402

im = cv2.imread(os.path.join(HERE, "testdata", "screens", "pc-1019-new-ui-phantom-south.jpg"))
v = mm.MapReader().parse(hud.minimap_crop(im))
assert v is not None
m = dg.Memory()
m.cx, m.cy, m.anchored = -3, -2, True
m.rooms[(-3, -1)] = mm.TODO
m.doors |= {((-3, -2), (-3, -1)), ((-3, -1), (-3, -2))}
for i in range(3):
    m.merge(v, i)
assert (-3, -1) not in m.rooms and ((-3, -2), (-3, -1)) not in m.doors
assert all((m.cx + a, m.cy + b) in m.rooms for (a, b) in v.cells)
print("phantom: ok")
