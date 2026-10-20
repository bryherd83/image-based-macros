"""When the remembered map has unfinished rooms but no way to them, the farm starts the map over
from spawn instead of waiting (PC 10-20 07:43 sat 3 min, 08:33 until a restart).
And a drag that doesn't turn the camera makes the next ones the careful kind.
    python test_mapreset.py
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sim  # noqa: E402
import dungeon as dg  # noqa: E402

Real = dg.Memory
made = []


class Broken(Real):
    """The first map in memory loses every door it sees (like a memory that went wrong)."""
    def __init__(self):
        super().__init__()
        made.append(self)

    def merge(self, v, now):
        r = super().merge(v, now)
        if self is made[0] and now > 20:
            self.doors.clear()
        return r


dg.Memory = Broken
env = sim.SimEnv(seed=1, arrow_follows="camera")
lines = []
env.log = lambda m, *a, **k: lines.append((env.t, m))
dg.DungeonRun(env).run()
dg.Memory = Real
resets = [t for t, m in lines if "starting the map over" in m]
stuck = [t for t, m in lines if m.startswith("no unfinished rooms found")]
print(f"{env.t / 60:.1f} min, map restarts {len(resets)}, maps made {len(made)}, "
      f"restart {resets[0] - stuck[0]:.0f}s after the first 'no way'")
assert resets and len(made) >= 2 and resets[0] - stuck[0] < 35
assert sum(1 for t, m in lines if t > resets[0] and "dungeon" in m and "finished" in m) or env.t - resets[0] < 600

# lost drags: with every 2nd drag lost, slow drags get used and the dungeon still finishes
slow = []
env = sim.SimEnv(seed=2, arrow_follows="camera", drag_fail=0.5)
orig = env.cam_drag
env.cam_drag = lambda px, slow_=False, **k: (slow.append(k.get("slow", False)), orig(px))
lines = []
env.log = lambda m, *a, **k: lines.append(m)
dg.DungeonRun(env).run()
print(f"lost drags: {env.t / 60:.1f} min, careful drags {sum(slow)} of {len(slow)}")
assert any(slow) and env.t / 60 < 10
print("map reset: ok")
