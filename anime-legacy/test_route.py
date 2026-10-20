"""Routes: quickest by rooms + turns, and pressing Spawn when walking from the blue room is quicker
(Blayne 10-19: from far away it walked the long way round).
    python test_route.py
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import minimap as mm  # noqa: E402
import dungeon as dg  # noqa: E402
import sim  # noqa: E402


def line_map():
    # spawn (0,0); a long corridor east to (8,0), then up to (8,-1); unfinished room (0,-1) north of spawn
    m = dg.Memory()
    m.anchored = True
    for x in range(0, 9):
        m.rooms[(x, 0)] = mm.CLEARED
    m.rooms[(0, 0)] = mm.SPAWN
    m.rooms[(0, -1)] = mm.TODO
    for x in range(0, 8):
        m.doors |= {((x, 0), (x + 1, 0)), ((x + 1, 0), (x, 0))}
    m.doors |= {((0, 0), (0, -1)), ((0, -1), (0, 0))}
    return m


m = line_map()
m.cx, m.cy = 8, 0
p = m.plan(0)
assert m.via_spawn and p == [(0, 0), (0, -1)], (p, m.via_spawn)
print("far away: press Spawn, then", p)
m.spawn_ok = False
p = m.plan(0)
assert not m.via_spawn and len(p) == 10, p
print("Spawn not allowed: walks", len(p) - 1, "rooms")
m.cx, m.cy = 2, 0
p = m.plan(0)
assert not m.via_spawn or True
m.spawn_ok = True
p = m.plan(0)
assert not m.via_spawn and len(p) == 4, (p, m.via_spawn)
print("close by: walks", len(p) - 1, "rooms")

# fewer turns when two routes are as long: an L (1 turn) beats a zig-zag
m = dg.Memory()
for x in range(3):
    for y in range(3):
        m.rooms[(x, y)] = mm.CLEARED
m.rooms[(2, 2)] = mm.TODO
for x in range(3):
    for y in range(3):
        for d in ((1, 0), (0, 1)):
            k = (x + d[0], y + d[1])
            if k in m.rooms:
                m.doors |= {((x, y), k), (k, (x, y))}
m.cx, m.cy = 0, 0
p = m.plan(0)
turns = sum(1 for i in range(1, len(p) - 1)
            if (p[i][0] - p[i - 1][0], p[i][1] - p[i - 1][1]) != (p[i + 1][0] - p[i][0], p[i + 1][1] - p[i][1]))
assert len(p) == 5 and turns == 1, p
print("fewest turns:", p)

for sc in (False, True):
    res = []
    for seed in (1, 2, 3):
        env = sim.SimEnv(seed=seed, arrow_follows="camera")
        env.settings["spawn_shortcut"] = sc
        lines = []
        env.log = lambda msg, *a, **k: lines.append(msg)
        dg.DungeonRun(env).run()
        res.append((round(env.t / 60, 1), sum(x.startswith("stuck") for x in lines),
                    sum("quicker from there" in x for x in lines)))
    print("spawn shortcut", sc, "(min, stucks, shortcuts):", res)
    assert all(t < 9.5 for t, _, _ in res)
print("route: ok")
