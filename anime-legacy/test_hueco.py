"""Hueco Mundo: the screen readers on real screenshots (testdata/hueco/, if there), then whole runs
in a small simulated arena (skulls, rocks, waves, the card vote, Leave after wave 10).
    python test_hueco.py
"""
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hud  # noqa: E402
import hueco  # noqa: E402

# ---------------- 1. readers on screenshots (Blayne 11-01) ----------------
SHOTS = os.path.join(HERE, "testdata", "hueco")
WANT = {  # file: (in a run, wave, spots, (you x, y) or None, skulls)
    "s108.png": (True, 1, "4/4", (-1, -1), 4),
    "s109.png": (True, 1, "2/4", (-22, 70), 2),
    "s110.png": (True, 2, "3/3", (-1, -1), 3),
    "s112.png": (True, 5, "1/1", (-1, -1), 1),
    "s114.png": (True, 1, "1/6", (-48, -37), 1),       # your arrow on the last skull (11-01 17:59)
    "s115.png": (True, 2, "3/5", (34, 36), 3),         # arrow pointing SE, touching a skull (18:06)
    "s116.png": (True, 2, "2/5", (42, 43), 2),         # arrow on the middle of a cleared spot
    "s117.png": (True, 1, "1/3", (-22, 71), 1),        # last skull by the S badge, at 91 px (froze 18:12)
    "rim2.jpg": (True, 3, "2/3", (46, 47), 2),         # two skulls cut off by the map's edge (11-02 08:10)
    "rim1.jpg": (True, 2, "1/5", (-25, 29), 1),        # one cut off by the west edge (08:09)
    "s104.png": (False, None, None, None, 0),
    "s107.png": (False, None, None, None, 0),
}
if os.path.isdir(SHOTS):
    import cv2
    T = hud.Templates()
    for name, (run, wave, spots, you, n) in WANT.items():
        f = cv2.imread(os.path.join(SHOTS, name))
        if f is None:
            continue
        assert hueco.is_hueco(f) == run, name
        if not run:
            continue
        sp = hueco.read_spots(f)
        m = hueco.read_map(f)
        assert hueco.read_wave(f) == wave, (name, hueco.read_wave(f))
        assert sp is not None and sp.text == spots, (name, sp)
        assert m.player is not None and math.hypot(m.player[0] - you[0], m.player[1] - you[1]) < 2.5, (name, m.player)
        assert len(m.skulls) == n, (name, m.skulls)
        want_arrow = {"s114.png": -math.pi / 2, "s115.png": math.radians(45), "rim2.jpg": 0.84,
                      "rim1.jpg": math.pi}.get(name, math.pi / 2)
        if name == "s117.png":
            want_arrow = math.radians(84)
        if name != "s116.png":
            assert m.arrow is not None and abs(hueco.wrap(m.arrow - want_arrow)) < 0.25, (name, m.arrow)
    # out by the rim (11-02 08:25-08:27). A skull's real middle, not a spot short of it: stopping
    # at 92 px left 0 DPS with enemies alive
    f = cv2.imread(os.path.join(SHOTS, "rim2.jpg"))
    if f is not None:
        m = hueco.read_map(f)
        for want in ((-96, -34), (24, 98)):
            assert any(math.hypot(sk[0] - want[0], sk[1] - want[1]) < 3 for sk in m.skulls), m.skulls
    # your arrow dimmed 100 px out: found if you were last seen near there, and only then (the
    # mouse pointer looks just like it)
    f = cv2.imread(os.path.join(SHOTS, "rim-dimarrow.jpg"))
    if f is not None:
        m = hueco.read_map(f, prev=(-86, -31))
        assert m.player is not None and math.hypot(m.player[0] + 95, m.player[1] + 33) < 3, m.player
        assert hueco.read_map(f).player is None
        assert hueco.read_map(f, prev=(40, 40)).player is None
    # your arrow on the very middle of a skull (made from s109: arrow moved onto a skull): you're
    # found there, and the skull still counts as there (red round the arrow) until it's a check
    f = cv2.imread(os.path.join(SHOTS, "onskull.png"))
    if f is not None:
        m = hueco.read_map(f)
        assert m.player is not None and math.hypot(m.player[0] - 30, m.player[1] - 12) < 1.5, m.player
        assert hueco.red_near(f, (29.7, 12.1)) >= 10
    f = cv2.imread(os.path.join(SHOTS, "s113.png"))
    if f is not None:
        assert hueco.card_screen(f, T)
        assert hueco.pick_card(f, hueco.card_pictures())[0] == 2        # Espada Challenge (drops)
        assert hueco.pick_card(f, ())[0] == 2                          # the red risk & reward card
    f = cv2.imread(os.path.join(SHOTS, "s104.png"))
    if f is not None:
        assert T.find(f, "hmkey") is not None and T.find(f, "hmkey")[0] > 1100   # Soul Society's key
    # your arrow hidden under the spawn diamond, the mouse pointer on the map near the rim (11-01
    # 18:44-19:24, 12 runs lost): you're not found, and the pointer isn't taken for you
    f = cv2.imread(os.path.join(SHOTS, "hidden.jpg"))
    if f is not None:
        assert hueco.read_map(f).player is None
        # your arrow out by the rim (walking round a skull at 91 px: lost at 94+, Blayne 11-01)
        c = hud.minimap_crop(f, hueco.MAP_R + hueco.ARROW_EXTRA)
        R = (c.shape[0] - 1) // 2
        hueco.find_arrow(c, R, 1.0)
        for r in (70, 90, 94, 96, 98):      # (further out too little of it is on the map: stepping)
            for deg in range(15, 360, 30):
                if abs(math.cos(math.radians(deg))) > 0.97 or abs(math.sin(math.radians(deg))) > 0.97:
                    continue                # (under the N/E/S/W badges)
                x, y = R + round(r * math.cos(math.radians(deg))), R + round(r * math.sin(math.radians(deg)))
                for k in (0, 30, 60, 90):
                    o = c.copy()
                    fill, band = hueco._ARROW_SHAPES[k]
                    o[band[:, 1] + y, band[:, 0] + x] = (60, 50, 50)
                    o[fill[:, 1] + y, fill[:, 0] + x] = (255, 255, 255)
                    fa = hueco.find_arrow(o, R, 1.0)
                    assert fa is not None and math.hypot(fa[0] - x, fa[1] - y) < 4, (r, deg, k, fa)
    print("readers: ok")
else:
    print("readers: skipped (no testdata/hueco screenshots)")


# ---------------- 2. whole runs in a simulated arena ----------------
class World:
    """Map px, north-up, spawn at (-1, -1). The arrow shows the camera; W walks where it looks."""

    def __init__(self, seed, rocks=True, speed=40.0, mount=2.0, mounted=False, waves_skulls=None, aura=2.5,
                 drag_fail=0.0, hide_spawn=False, hide_beyond=None):
        self.aura = aura
        self.hide_spawn, self.hide_beyond = hide_spawn, hide_beyond
        self.drag_fail, self.lost_drags, self.drags = drag_fail, 0, 0
        self.rng = random.Random(seed)
        self.t = 0.0
        self.x, self.y = -1.0, -1.0
        self.cam = self.rng.uniform(-math.pi, math.pi)
        self.k_true = 640.0
        self.walk, self.mount_mult, self.mounted = speed, mount, mounted
        self.keys = set()
        self.wave = 1
        self.rocks = [(self.rng.uniform(-60, 60), self.rng.uniform(-60, 60)) for _ in range(6)] if rocks else []
        self.jump_until = 0.0
        self.card_until = None
        self.transition_until = 0.0
        self.left_at = None
        self.cards_picked = []
        self.spawns = 0
        self.jumps = 0
        self.new_wave()

    def new_wave(self):
        n = 1 if self.wave % 5 == 0 else self.rng.randint(3, 4)
        self.skulls = []
        for _ in range(n):
            a, r = self.rng.uniform(-math.pi, math.pi), self.rng.uniform(25, 92)   # out to the rim
            self.skulls.append([r * math.cos(a), r * math.sin(a), self.rng.uniform(1.5, 4.0), False])  # hp in s
        self.spots_b = n

    def step(self, dt):
        self.t += dt
        if self.left_at is not None:
            return
        if self.card_until is not None:
            if self.t >= self.card_until:
                self.card_until = None
                self.transition_until = self.t + 1.0
            return
        if self.t < self.transition_until:
            return
        f = ("w" in self.keys) - ("s" in self.keys)
        r = ("d" in self.keys) - ("a" in self.keys)
        if f or r:
            ang = self.cam + math.atan2(r, f)
            sp = self.walk * (self.mount_mult if self.mounted else 1.0)
            nx, ny = self.x + math.cos(ang) * sp * dt, self.y + math.sin(ang) * sp * dt
            blocked = any(math.hypot(nx - rx, ny - ry) < 5 for rx, ry in self.rocks) and self.t > self.jump_until
            if not blocked and math.hypot(nx, ny) < 98:
                self.x, self.y = nx, ny
        for s in self.skulls:            # the group is spread round the skull: only from (nearly)
            if math.hypot(s[0] - self.x, s[1] - self.y) < self.aura:   # its middle all die
                s[2] -= dt
            elif math.hypot(s[0] - self.x, s[1] - self.y) < 8:
                s[3] = True                  # some of it hit: the "enemies" count changes
        for s in self.skulls:
            if False:
                s[2] -= dt
        self.skulls = [s for s in self.skulls if s[2] > 0]
        if not self.skulls:
            if self.wave in (5, 10):
                self.card_until = self.t + 3.0
            else:
                self.transition_until = self.t + 1.0
            self.wave += 1
            self.x, self.y = -1.0, -1.0          # back to spawn
            self.new_wave()


class Env:
    def __init__(self, w, settings=None):
        self.w = w
        self.settings = {"hueco_leave_after": 10, "cam_px_per_rad": 584, "join_trials": True,
                         **(settings or {})}
        self.tpl = None
        self.info = {}
        self.mount_on = None
        self.logs = []
        self.presses = 0

    def now(self):
        return self.w.t

    def sleep(self, s):
        end = self.w.t + s
        while self.w.t < end - 1e-9:
            self.w.step(min(0.02, end - self.w.t))

    def running(self):
        return self.w.left_at is None and self.w.t < 60 * 60

    def frame(self):
        self.sleep(0.03)                  # reading the screen takes a moment
        return self.w

    def set_keys(self, keys):
        self.w.keys = set(keys)

    def release_all(self):
        self.w.keys = set()

    def tap(self, key, ms=50):
        if key == "space":
            self.w.jump_until = self.w.t + 0.5
            self.w.jumps += 1
        elif key in "123" and self.w.card_until is not None:
            self.w.cards_picked.append(int(key))
        self.sleep(ms / 1000)

    def cam_drag(self, px, slow=False):
        self.w.drags += 1
        # Roblox sometimes misses the right-button press: the mouse slides, the camera stays
        # (11-01 18:21). The careful (slow) drag gets through far more often
        fail = self.w.drag_fail * (0.2 if slow else 1.0)
        if self.w.rng.random() >= fail:
            self.w.cam = hueco.wrap(self.w.cam + px / self.w.k_true)
        else:
            self.w.lost_drags += 1
        self.sleep(0.6 if slow else 0.3)

    def press_spawn(self, wait=1.0):
        self.w.x, self.w.y = -1.0, -1.0
        self.w.spawns += 1
        self.sleep(wait)
        return True

    def toggle_mount(self, why=""):
        self.w.mounted = not self.w.mounted
        self.presses += 1
        return True

    def find(self, name, f=None, **kw):
        return (900, 115) if name == "leave" else None

    def click(self, x, y, **kw):
        if (x, y) == (900, 115):
            self.w.left_at = self.w.wave

    def housekeeping(self):
        return False

    def status(self, m):
        pass

    def log(self, m):
        self.logs.append(m)

    def shot(self, *a, **k):
        pass

    def save_setting(self, k, v, quiet=False):
        self.settings[k] = v


def patch():
    """The screen readers answer from the simulated world (frame = the World)."""
    hueco.card_screen = lambda f, tpl: f.card_until is not None
    hueco.is_hueco = lambda f, castle=None: f.card_until is None and f.t >= f.transition_until
    hud.castle_x = lambda f: 828 if (f.card_until is None and f.t >= f.transition_until and f.left_at is None) else None
    hud.covered = lambda f: f.t < f.transition_until
    hud.spawn_hidden = lambda f, xy=None: False
    hud.find_popup = lambda f: None
    hueco.read_wave = lambda f, castle=None: f.wave
    hueco.read_spots = lambda f, castle=None: hud.Counter(len(f.skulls), f.spots_b, f"{len(f.skulls)}/{f.spots_b}")
    hud.read_counter = lambda f, which, **kw: hud.Counter(len(f.skulls), f.spots_b, "x")
    hueco.pick_card = lambda f, pics=(), avoid=(): (2, "test")

    def read_map(f, prev=None):
        noise = lambda: f.rng.uniform(-0.4, 0.4)  # noqa: E731
        if (f.hide_spawn and math.hypot(f.x + 1, f.y + 1) < 3) or \
                (f.hide_beyond and math.hypot(f.x, f.y) > f.hide_beyond):
            return hueco.HMap(player=None, arrow=None, skulls=[(s[0], s[1]) for s in f.skulls], spawn=(-1.0, -1.0))
        # next to a skull your arrow sometimes merges with its face and can't be told apart
        # (11-01 18:06): you're "not on the map" then
        if any(5 < math.hypot(s[0] - f.x, s[1] - f.y) < 12 for s in f.skulls) and f.rng.random() < 0.6:
            return hueco.HMap(player=None, arrow=None, skulls=[(s[0], s[1]) for s in f.skulls], spawn=(-1.0, -1.0))
        return hueco.HMap(player=(f.x + noise(), f.y + noise()), arrow=hueco.wrap(f.cam + noise() * 0.05),
                          # a skull you stand on can't be seen (your arrow covers it: 11-01 17:59)
                          skulls=[(s[0], s[1]) for s in f.skulls if math.hypot(s[0] - f.x, s[1] - f.y) > 8],
                          spawn=(-1.0, -1.0))
    hueco.read_map = read_map
    # red is still there under your arrow until the group is dead (then a grey check)
    hueco.red_centroid = lambda f, pos, r=14: next(((s[0], s[1]) for s in f.skulls if math.hypot(s[0] - pos[0], s[1] - pos[1]) < r), None)
    hueco.red_near = lambda f, pos, r=11: 100 if any(math.hypot(s[0] - pos[0], s[1] - pos[1]) < 3 for s in f.skulls) else 0


# a run card turned the map dark: still in the run, so it leaves (11-02 12:25:40). Back in
# the lobby it's over
f = cv2.imread(os.path.join(HERE, "testdata", "hueco", "dark-map-wave11.jpg"))
c = hud.castle_x(f)
assert not hueco.is_hueco(f, c) and hueco.in_run(f, c, 10) and hueco.read_wave(f, c) == 11
assert not hueco.in_run(f, c, None)
f = cv2.imread(os.path.join(HERE, "testdata", "hueco", "run-ended-lobby.jpg"))
assert not hueco.in_run(f, hud.castle_x(f), 8)
print("still in the run: ok")
# Sealed Spots hides every skull for the rest of the run and it's red, so it got picked (11-02
# 14:30:35): now the next best card. Other red cards still count
avoid = hueco.card_pictures(pattern="hmavoid_*.png")
vote = cv2.imread(os.path.join(HERE, "testdata", "hueco", "sealed-spots-vote.jpg"))
assert hueco.pick_card(vote)[0] == 1 and hueco.pick_card(vote, (), avoid) == (2, "first card")
vote = cv2.imread(os.path.join(HERE, "testdata", "hueco", "vote-time-pressure.jpg"))
assert hueco.pick_card(vote, (), avoid) == (1, "risk & reward")
# Leave matches its picture only 89% on Blayne's PC: it stayed on wave 11 (11-02 13:08). No such
# button in the lobby
tpl = hud.Templates()
c = tpl.find(cv2.imread(os.path.join(HERE, "testdata", "hueco", "leave-89pct.jpg")), "leave", min_frac=0.8)
assert c and abs(c[0] - 909) < 4 and abs(c[1] - 115) < 4, c
assert tpl.find(f, "leave", min_frac=0.8) is None
# no match at all: its usual spot, and with the panel still there after the click it tries again
import types  # noqa: E402
f = cv2.imread(os.path.join(HERE, "testdata", "hueco", "leave-89pct.jpg"))
clicks = []
env = types.SimpleNamespace(find=lambda *a, **k: None, click=lambda x, y: clicks.append((x, y)), log=print,
                            shot=lambda *a, **k: None, sleep=lambda s: None, frame=lambda: f)
stub = types.SimpleNamespace(env=env, stop=lambda: None, wave=11)
assert hueco.HuecoRun.leave(stub, "test", f, 828) is False and clicks == [(909, 115)], clicks

patch()
results = []
for seed in range(1, 9):
    w = World(seed, rocks=seed % 2 == 0)
    env = Env(w)
    res = hueco.HuecoRun(env).run()
    results.append((seed, res, w.left_at, round(w.t / 60, 1), w.spawns, w.jumps, w.cards_picked[:2], env.presses))
    assert res == "left" and w.left_at in (10, 11), (seed, res, w.left_at, env.logs[-5:])
    assert w.cards_picked and set(w.cards_picked) == {2}, (seed, w.cards_picked)
    assert env.presses == 0 and not w.mounted, seed                # never touches the mount
# SPOTS goes down while still walking in (the group dies from further out): it moves on at once
w = World(13, aura=12.0)
env = Env(w)
assert hueco.HuecoRun(env).run() == "left"
assert any("on the way there" in m for m in env.logs), env.logs[-5:]
# a skull it can't reach, and it's the nearest: goes to the other one after a while (11-02 14:25:34)
w = World(14, rocks=False)
w.skulls, w.spots_b, w.x, w.y = [[130.0, 0.0, 2.0, False], [-20.0, 0.0, 2.0, False]], 2, 70.0, 0.0
env = Env(w)
real_log = env.log


class Reached(Exception):
    pass


def stop_log(m, *a, **k):
    real_log(m, *a, **k)
    if len(w.skulls) < 2:
        raise Reached


env.log = stop_log
try:
    hueco.HuecoRun(env).run()
    raise AssertionError("never got to the other spot")
except Reached:
    assert w.skulls[0][0] == 130.0 and any("couldn't reach the spot" in m for m in env.logs), env.logs[-5:]
# on the mount (you get on before the run): it stays on (M got you off it, 11-02 13:19:12)
w = World(9, mounted=True)
env = Env(w)
run = hueco.HuecoRun(env)
assert run.run() == "left" and env.presses == 0 and w.mounted
assert run.speed < 110, run.speed             # (80 here. A walk counted as a tap: 119 in game, 11-02 13:01)
# walks without turning the camera: no drags at all (131 s of a 7.7 min run, 11-02 13:24:50)
assert w.drags == 0 and "Hueco time: " in " ".join(env.logs), (w.drags, env.logs[-3:])
assert "turning" not in " ".join(env.logs)
# shuffling a little after each jump still counts toward pressing Spawn (11-02 12:16:30: 52 s)
w = World(12)
run = hueco.HuecoRun(Env(w))
run.hold({"w"})
for i in range(8):
    run.progress = (w.t - 1.0, 0.0, 0.0)
    run.stuck_check(w.t, 0.0, 0.0)
    run.stuck_check(w.t, 5.0, 0.0)              # (moved: the old count started again here)
assert w.spawns == 1 and run.keys == set(), (w.spawns, run.keys)   # (W gets pressed again after it)
# your arrow can't be seen, at spawn or out by the rim: it steps until it can (it stood still until
# the run was lost, 11-01 18:42 and 18:44-19:27)
for kw in ({"hide_spawn": True}, {"hide_beyond": 88}):
    for seed in (41, 42):
        w = World(seed, **kw)
        env = Env(w)
        res = hueco.HuecoRun(env).run()
        assert res == "left" and w.left_at in (10, 11), (kw, seed, res, w.wave, env.logs[-5:])
        print(f"arrow hidden {kw}, seed {seed}: left at wave {w.left_at} · {w.t / 60:.1f} min")
for r in results:
    print("seed %d: %s at wave %s · %.1f min · Spawn %d · jumps %d · cards %s · M presses %d" % r)
print("hueco run: ok")
