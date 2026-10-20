import sys, os, cv2
sys.path.insert(0, r"C:\Users\bryhe\Downloads\anime-legacy-farmpy")
import hud, minimap as mm, dungeon as dg
im = cv2.imread(os.path.expandvars(r"%USERPROFILE%\Pictures\Screenshots\anime-legacy-log\1019-201240-py-stuck-3.jpg"))
cv2.imwrite(r"C:\Users\bryhe\Downloads\anime-legacy-farmpy\testdata\screens\pc-1019-new-ui-phantom-south.jpg", im)
v = mm.MapReader().parse(hud.minimap_crop(im))
print("s", v.s, "p", round(v.p, 1), "off", v.offx, v.offy, "cells", sorted(v.cells))
m = dg.Memory()
m.cx, m.cy, m.anchored = -3, -2, True
m.rooms[(-3, -1)] = mm.TODO
m.doors |= {((-3, -2), (-3, -1)), ((-3, -1), (-3, -2))}
for i in range(3):
    m.merge(v, i)
print("phantom gone:", (-3, -1) not in m.rooms, "door gone:", ((-3, -2), (-3, -1)) not in m.doors)
# rooms that are on screen must stay
print("real neighbours kept:", all((m.cx + a, m.cy + b) in m.rooms for (a, b) in v.cells))
assert (-3, -1) not in m.rooms and ((-3, -2), (-3, -1)) not in m.doors
print("phantom: ok")
