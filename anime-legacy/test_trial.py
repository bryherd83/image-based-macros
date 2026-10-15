"""Trial simulator: runs trial.py, and the previous version from git for comparison, against
a simple model of trial rooms. Nothing here touches the game.

Model (room-pitch units, like sim.py): a room is 0.74 deep and 0.74 wide; Spawn puts you at
its doorway; W walks 0.268 per second (measured in your dungeons, no sprint); your aura hits
enemies within REACH; an enemy dies after KILL_SEC in reach; the DPS meter shows damage while
something is in reach (plus a short lag). Enemies stand still and fighters aren't modelled,
so this is a pessimistic model of the real game, not the game.

    python test_trial.py [seeds per scenario, default 8]
"""
import collections
import importlib.util
import os
import random
import statistics
import subprocess
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from game import DEFAULTS  # noqa: E402
from hud import Counter  # noqa: E402
import trial as trial_new  # noqa: E402

WALK = 0.268
DEPTH, HALF = 0.74, 0.37
KILL_SEC = 2.0
DPS_LAG = 0.8
LEAVE = (840, 122)

SCENES = {
    "far in (your screenshots)": lambda r: (r.uniform(0.45, 0.72), r.uniform(-0.25, 0.25)),
    "deep (like your 19:47 trial)": lambda r: (r.uniform(0.62, 0.72), r.uniform(-0.12, 0.12)),
    "spread over the room": lambda r: (r.uniform(0.05, 0.72), r.uniform(-0.3, 0.3)),
    "near the door": lambda r: (r.uniform(0.08, 0.35), r.uniform(-0.15, 0.15)),
    "near the side walls": lambda r: (r.uniform(0.2, 0.6), r.choice((-1, 1)) * r.uniform(0.27, 0.35)),
}

FAKE_HUD = types.SimpleNamespace(
    has_minimap=lambda f: False,
    find_popup=lambda f: None,
    read_counter=lambda f, which: f.counter(which),
    dps_hitting=lambda f: f.dps(),
)


class TrialSim:
    def __init__(self, scene, seed, reach=0.22, dps=True, waves=22, limit=25 * 60, spawn_at=0.0,
                 onset=0.0, hold=DPS_LAG, teleport=(0.3, 0.7), seen=True):
        self.r = random.Random(seed)
        self.r2 = random.Random(seed + 1000)     # Spawn timing (keeps the rooms the same per seed)
        self.place = SCENES[scene]
        self.reach, self.dps_ok, self.leave_after = reach, dps, waves
        self.limit, self.spawn_at = limit, spawn_at
        # DPS meter: shows damage `onset` s after a hit and keeps showing it for `hold` s
        self.onset, self.hold = onset, hold
        self.hits = collections.deque()
        # Spawn moves you after `teleport` s; seen=False: the screen check never notices
        self.tp, self.tp_seen = teleport, seen
        self.settings = dict(DEFAULTS)
        self.info = {}
        self.t = 0.0
        self.wave = 1
        self.left = False
        self.keys = set()
        self.lines = []
        self.steps = 0
        self.fallback_spawns = 0
        self.clear_times = []
        self.n = 4
        self._room()

    # ---- the room ----
    def _room(self):
        self.pos = [self.spawn_at, 0.0]
        self.en = [[*self.place(self.r), 0.0] for _ in range(self.n)]
        self.room_t = self.t
        self.last_in_reach = -9.0
        self.cleared = False

    def _killed(self):
        return sum(1 for e in self.en if e[2] >= KILL_SEC)

    def _advance(self, s, keys):
        end = self.t + s
        while self.t < end - 1e-9:
            dt = min(0.05, end - self.t)
            dd = (("w" in keys) - ("s" in keys)) * WALK * dt
            dl = (("d" in keys) - ("a" in keys)) * WALK * dt
            self.pos[0] = min(DEPTH, max(self.spawn_at - 0.1, self.pos[0] + dd))
            self.pos[1] = min(HALF, max(-HALF, self.pos[1] + dl))
            self.t += dt
            in_reach = False
            for e in self.en:
                if e[2] < KILL_SEC and ((e[0] - self.pos[0]) ** 2 + (e[1] - self.pos[1]) ** 2) ** 0.5 <= self.reach:
                    e[2] += dt
                    in_reach = True
            if in_reach:
                self.last_in_reach = self.t
                self.hits.append(self.t)
            if not self.cleared and self._killed() == self.n:
                self.cleared = True
                self.clear_times.append(self.t - self.room_t)

    # ---- what trial.py sees ----
    def counter(self, which):
        if which == "enemies":
            k = self._killed()
            return Counter(k, self.n, f"{k}/{self.n}")
        return Counter(self.wave, 50, f"{self.wave}/50")

    def dps(self):
        """Damage shows if something was in reach between `hold` and `onset` seconds ago."""
        if not self.dps_ok:
            return None
        while self.hits and self.hits[0] < self.t - self.hold:
            self.hits.popleft()
        return bool(self.hits) and self.hits[0] <= self.t - self.onset

    def frame(self):
        return self

    def enemies(self):
        return self.counter("enemies")

    def find(self, name, f=None, **kw):
        if name == "roomhud":
            return None if self.left else (1110, 52)
        return LEAVE if name == "leave" else None

    # ---- what trial.py does ----
    def now(self):
        return self.t

    def sleep(self, s):
        self._advance(s, self.keys)

    def tap(self, key, ms=50):
        self._advance(ms / 1000, {key})

    def set_keys(self, keys):
        self.keys = set(keys)

    def release_all(self):
        self.keys = set()

    def press_spawn(self, wait=1.0):
        if self.cleared:
            self.wave += 1
            self._room()
        else:
            if self.t > 3:              # (the press at the start of the trial isn't a retry)
                self.fallback_spawns += 1
            self.pos = [self.spawn_at, 0.0]
        self.sleep(wait)
        return True

    def wait_moved(self, before, most=2.5):
        if not self.tp_seen:
            self.sleep(most)
            return None
        took = min(most, self.r2.uniform(*self.tp))
        self.sleep(took)
        return took

    def save_setting(self, key, value, quiet=False):
        self.settings[key] = value

    def click(self, x, y, park=True):
        if (x, y) == LEAVE:
            self.left = True

    def running(self):
        return not self.left and self.t < self.limit

    def stop_flag(self):
        return self.t >= self.limit

    def housekeeping(self):
        return False

    def has_minimap(self):
        return False

    def set_sprint(self, on):
        pass

    def status(self, msg):
        if msg.startswith("trial: enemies out of reach"):
            self.steps += 1

    def log(self, msg):
        self.lines.append((round(self.t, 1), msg))

    def shot(self, *a, **k):
        pass


def load_old():
    """trial.py as it was in the last git commit (the 'before' version)."""
    src = subprocess.run(["git", "show", "HEAD:trial.py"], cwd=HERE, capture_output=True, text=True, check=True).stdout
    path = os.path.join(os.environ.get("TMPDIR", HERE), "trial_before.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    spec = importlib.util.spec_from_file_location("trial_before", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(mod, scene, seed, **kw):
    sim = TrialSim(scene, seed, **kw)
    mod.run_trial(sim, "dungeon", sim.leave_after)
    return sim


def summary(sims):
    done = [s for s in sims if s.left]
    per_room = [t for s in sims for t in s.clear_times]
    return (f"{len(done):2d}/{len(sims)} reached wave {sims[0].leave_after}"
            f" · {statistics.mean(s.t for s in done) / 60 if done else 0:5.1f} min"
            f" · {statistics.mean(per_room) if per_room else 0:5.1f} s/room"
            f" · rooms cleared {statistics.mean(len(s.clear_times) for s in sims):5.1f}"
            f" · steps/room {statistics.mean(s.steps / max(1, len(s.clear_times)) for s in sims):4.1f}"
            f" · Spawn retries {statistics.mean(s.fallback_spawns for s in sims):4.1f}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    old = load_old()
    for mod in (old, trial_new):
        mod.hud = FAKE_HUD
    print("aura reach 0.22 room, 22 waves, 25 min limit")
    for scene in SCENES:
        print(f"\n{scene}")
        print("  before:", summary([run(old, scene, s) for s in range(n)]))
        print("  now:   ", summary([run(trial_new, scene, s) for s in range(n)]))
    print("\nharder cases (spread over the room): before → now")
    for label, kw in ((("aura reach 0.15", {"reach": 0.15}), ("aura reach 0.30", {"reach": 0.30}),
                       ("DPS meter unreadable", {"dps": False}),
                       ("DPS meter slow (0.5 s late, keeps 2 s)", {"onset": 0.5, "hold": 2.0}),
                       ("DPS meter very slow (1 s late, keeps 4 s)", {"onset": 1.0, "hold": 4.0}),
                       ("Spawn takes 1-2 s to move you", {"teleport": (1.0, 2.0)}),
                       ("Spawn move never noticed", {"seen": False}),
                       ("Spawn lands 0.1 before the door", {"spawn_at": -0.1}))):
        print(f"  {label:42s} before:", summary([run(old, "spread over the room", s, **kw) for s in range(n)]))
        print(f"  {'':42s} now:   ", summary([run(trial_new, "spread over the room", s, **kw) for s in range(n)]))
    print("\ndeep rooms with a very slow DPS meter: before → now")
    kw = {"onset": 1.0, "hold": 4.0}
    print("  before:", summary([run(old, "deep (like your 19:47 trial)", s, **kw) for s in range(n)]))
    print("  now:   ", summary([run(trial_new, "deep (like your 19:47 trial)", s, **kw) for s in range(n)]))
