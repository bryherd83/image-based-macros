"""Alt mode (farm.alt_tick): stands still in a dungeon or trial and leaves at the right moment.
    python test_alt.py
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import farm  # noqa: E402
import hud  # noqa: E402


class G:
    """Records what the farm does; `tap`, `set_keys` or a drag would be movement, so there are none."""

    def __init__(self):
        self.info, self.clicks, self.logs = {}, [], []
        self.hud = True

    def find(self, name, f=None, **kw):
        return {"roomhud": (1, 1) if self.hud else None, "leave": (900, 115)}.get(name)

    def housekeeping(self):
        return False

    def click(self, *a):
        self.clicks.append(a)

    def log(self, m):
        self.logs.append(m)

    def shot(self, *a, **k):
        pass

    def status(self, m):
        pass


class C:
    def __init__(self):
        self.waited = self.afk = 0

    def waiting_room(self, f):
        self.waited += 1

    def anti_afk(self):
        self.afk += 1


clock = [1000.0]
farm.time = types.SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda s: None)
counters = {}
hud.read_counter = lambda f, which, **kw: counters.get(which)
minimap = [False]
hud.has_minimap = lambda f: minimap[0]


def setup(leave=27):
    return types.SimpleNamespace(S={"trial_leave_after": leave, "trial_give_up_sec": 180, "alt_dungeon_max_sec": 900}), G(), C()


def step(s, g, c, dt=1.0):
    farm.Farm.alt_tick(s, g, c, None)
    clock[0] += dt


def trial(wave, killed, total=10):
    counters["wave"] = hud.Counter(wave, 50, f"{wave}/50")
    counters["enemies"] = hud.Counter(killed, total, f"{killed}/{total}")


# dungeon: stays, whatever its room counter says, until the game ends it
s, g, c = setup()
minimap[0] = True
trial(49, 10)
for _ in range(600):
    step(s, g, c)
assert not g.clicks and s._alt["kind"] == "dungeon"
g.hud = False
step(s, g, c)
assert c.waited == 1 and s._alt is None

# dungeon nobody clears: Leave after 15 minutes
s, g, c = setup()
g.hud = True
for _ in range(910):
    step(s, g, c)
assert len(g.clicks) == 1 and "15 min" in g.logs[0], g.logs

# trial: stays through the set wave until it's cleared
minimap[0] = False
s, g, c = setup()
trial(26, 10)
for _ in range(10):
    step(s, g, c)
trial(27, 3)
for _ in range(10):
    step(s, g, c)
assert not g.clicks
trial(27, 10)
step(s, g, c)
assert len(g.clicks) == 1 and "wave 27 done" in g.logs[0], g.logs

# already past it when first seen, but not in the first seconds (could be a dimmed dungeon)
s, g, c = setup()
trial(30, 0)
for _ in range(4):
    step(s, g, c)
assert not g.clicks
for _ in range(3):
    step(s, g, c)
assert len(g.clicks) == 1

# trial where nobody clears the wave: Leave after 3 minutes, not before
s, g, c = setup()
trial(5, 2)
for _ in range(170):
    step(s, g, c)
assert not g.clicks
for _ in range(15):
    step(s, g, c)
assert len(g.clicks) == 1 and "not cleared" in g.logs[0], g.logs
print("alt: ok")
