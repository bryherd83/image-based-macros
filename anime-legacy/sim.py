"""A small dungeon simulator to test dungeon.py's decisions without the game.

Rooms sit on a grid (centres at whole numbers, 'room units'); each is a square of
half-size 0.37 with walls; neighbouring rooms joined by a door have a narrow opening
in the middle of the wall. Doors stay shut while the room you're in still has enemies,
and (optionally) only open while the camera looks at them. The camera turns by
px / k_true radians per mouse pixel, which the macro doesn't know exactly.

    .venv\\Scripts\\python.exe sim.py            # a few dungeons, summary
    .venv\\Scripts\\python.exe sim.py --verbose  # print what the macro says
"""
from __future__ import annotations

import math
import random
import sys

import minimap as mm
from dungeon import DungeonRun, wrap
from hud import Counter

HALF = 0.37            # room half-size (room units)
LEVELS = [10, 14, 17, 21, 24, 28, 32, 34, 38, 41, 45, 48, 52, 57, 60]


class SimEnv:
    def __init__(self, seed=1, n_rooms=50, door_w=0.14, look_doors=True, k_true=650.0, k_guess=584.0,
                 drag_fail=0.0, speed=0.27, sprint=1.5, verbose=False, time_limit=25 * 60,
                 arrow_follows="character", noise_px=0.35, sprint_on=True, treasure_far=2, fog=True,
                 mount=0.0, mounted=False, mount_turn=0.0, mount_lag=0.0):
        self.rng = random.Random(seed)
        self.t = 0.0
        self.verbose = verbose
        self.time_limit = time_limit
        self.door_w = door_w
        self.look_doors = look_doors
        self.k_true = k_true
        self.drag_fail = drag_fail
        self.speed = speed
        self.sprint_mult = sprint
        self.sprint = sprint_on        # sprint is a toggle in the game that stays on
        self.sprint_presses = 0
        self.mount_mult = mount        # 0 = no mount (the macro then never presses M)
        self.mounted = mounted
        self.mount_presses = 0
        # a mount that turns toward the way you steer at mount_turn rad/s (0 = at once) and moves
        # the way it faces, and speeds up / slows down over mount_lag seconds (0 = at once)
        self.mount_turn, self.mount_lag = mount_turn, mount_lag
        self.mfacing, self.mspeed = None, 0.0
        self.arrow_follows = arrow_follows
        self.noise_px = noise_px
        self.settings = {"cam_px_per_rad": k_guess, "walk_room_px": [41, 48], "scan_room_px": 10,
                         "face_doors": True, "dungeon_sprint": True,
                         "walk_rooms_per_sec": speed * sprint}   # learned while sprinting
        self.saved = {}
        # (the real game's new arrow shows the camera; the old one, simulated by default, didn't)
        self.settings["arrow_is_camera"] = arrow_follows == "camera"
        self.build(n_rooms)
        # fog: the map only shows rooms you've been in and the ones next to them (live: the
        # first look at the whole map shows 2 rooms; more appear as you go)
        self.fog = fog
        self.revealed = set()
        self.visited = {(0, 0)}
        self.reveal((0, 0))
        self.x, self.y = 0.0, 0.0
        self.cam = self.rng.uniform(-math.pi, math.pi)
        self.facing = self.cam
        self.keys = set()
        self.level = len(LEVELS) - 1
        self.enemies_left = 0
        self.enemy_room = None
        self.kill_t = 0
        # enemy positions in the room being fought (offsets from its middle). Normal rooms: 4 in
        # the middle. Treasure rooms: 5, `treasure_far` of them anywhere in the room (live: the
        # last one or two of a treasure room are often away from the middle)
        self.treasure_far = treasure_far
        self.en_pos = []
        self.en_total = 4
        self.last_hit_t = -9.0
        self.stats = {"drags": 0, "spawns": 0, "zoom_clicks": 0, "taps": 0, "jumps": 0}
        self.cleared_order = []
        self.last_msgs = []
        self.open_until = {}

    # ---------------- world ----------------
    def build(self, n):
        rooms = {(0, 0): mm.SPAWN}
        doors = set()
        frontier = [(0, 0)]
        while len(rooms) < n:
            a = self.rng.choice(list(rooms))
            d = self.rng.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
            b = (a[0] + d[0], a[1] + d[1])
            if b in rooms:
                if self.rng.random() < 0.15:
                    doors.add((a, b)); doors.add((b, a))
                continue
            rooms[b] = mm.TREASURE if self.rng.random() < 0.06 else mm.TODO
            doors.add((a, b)); doors.add((b, a))
        self.rooms, self.doors = rooms, doors

    def reveal(self, c):
        self.revealed.add(c)
        for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            k = (c[0] + d[0], c[1] + d[1])
            if (c, k) in self.doors:
                self.revealed.add(k)

    def room_of(self, x, y):
        c = (round(x), round(y))
        if abs(x - c[0]) <= HALF and abs(y - c[1]) <= HALF and c in self.rooms:
            return c
        return None

    def free(self, x, y):
        """Can you stand here?"""
        c = (round(x), round(y))
        if c in self.rooms and abs(x - c[0]) <= HALF and abs(y - c[1]) <= HALF:
            return True
        # in a doorway between two rooms?
        for d in ((1, 0), (0, 1)):
            for base in ((math.floor(x), round(y)) if d[0] else (round(x), math.floor(y)),):
                a, b = base, (base[0] + d[0], base[1] + d[1])
                if (a, b) not in self.doors:
                    continue
                if d[0] and a[0] < x < b[0] and abs(y - a[1]) <= self.door_w / 2:
                    return self.door_open(a, b, d)
                if d[1] and a[1] < y < b[1] and abs(x - a[0]) <= self.door_w / 2:
                    return self.door_open(a, b, d)
        return False

    def door_open(self, a, b, d):
        if self.enemies_left > 0:
            return False
        if self.look_doors:
            # a door opens while you look at it from close by, and stays open a few seconds
            key = (min(a, b), max(a, b))
            if self.open_until.get(key, 0) > self.t:
                return True
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            dist = math.hypot(mx - self.x, my - self.y)
            if dist > 0.35:
                return False
            # already inside the doorway: it can't trap you
            in_gap = (abs(self.x - mx) < 0.14 and abs(self.y - my) < self.door_w) if a[0] != b[0] else \
                     (abs(self.y - my) < 0.14 and abs(self.x - mx) < self.door_w)
            want = math.atan2(my - self.y, mx - self.x)
            if not in_gap and dist > 0.02 and abs(wrap(want - self.cam)) > math.radians(50):
                return False
            self.open_until[key] = self.t + 3
        return True

    def physics(self, dt):
        f = ("w" in self.keys) - ("s" in self.keys)
        r = ("d" in self.keys) - ("a" in self.keys)
        if self.mounted and (self.mount_turn or self.mount_lag):
            want_sp = self.speed * self.mount_mult if (f or r) else 0.0
            if f or r:
                want = self.cam + math.atan2(r, f)
                if self.mfacing is None:
                    self.mfacing = want
                d = wrap(want - self.mfacing)
                step = self.mount_turn * dt if self.mount_turn else abs(d)
                self.mfacing = wrap(self.mfacing + max(-step, min(step, d)))
            a = min(1.0, dt / self.mount_lag) if self.mount_lag else 1.0
            self.mspeed += (want_sp - self.mspeed) * a
            if self.mspeed > 1e-3 and self.mfacing is not None:
                ang = self.mfacing
                self.facing = ang
                dx, dy = math.cos(ang) * self.mspeed * dt, math.sin(ang) * self.mspeed * dt
                if self.free(self.x + dx, self.y + dy):
                    self.x += dx; self.y += dy
                elif self.free(self.x + dx, self.y):
                    self.x += dx
                elif self.free(self.x, self.y + dy):
                    self.y += dy
            f = r = 0
        if f or r:
            ang = self.cam + math.atan2(r, f)
            self.facing = ang
            sp = self.speed * (self.mount_mult if self.mounted else (self.sprint_mult if self.sprint else 1))
            dx, dy = math.cos(ang) * sp * dt, math.sin(ang) * sp * dt
            if self.free(self.x + dx, self.y + dy):
                self.x += dx; self.y += dy
            elif self.free(self.x + dx, self.y):
                self.x += dx
            elif self.free(self.x, self.y + dy):
                self.y += dy
        # enemies: a room you're in that isn't done spawns 4; your aura kills them near the middle
        c = self.room_of(self.x, self.y)
        if c is not None and c not in self.visited:
            self.visited.add(c)
            self.reveal(c)
        if c is not None and self.rooms[c] in (mm.TODO, mm.TREASURE):
            if self.enemy_room != c:
                self.enemy_room = c
                if self.rooms[c] == mm.TODO:
                    self.en_pos = [(0.0, 0.0)] * 4
                else:
                    er = random.Random(c[0] * 1000 + c[1] + 7)
                    self.en_pos = [(er.uniform(-0.06, 0.06), er.uniform(-0.06, 0.06))
                                   for _ in range(5 - self.treasure_far)]
                    self.en_pos += [(er.uniform(-0.3, 0.3), er.uniform(-0.3, 0.3)) for _ in range(self.treasure_far)]
                self.enemies_left = self.en_total = len(self.en_pos)
                self.kill_t = 0
            if self.enemies_left > 0:
                px, py = self.x - c[0], self.y - c[1]
                near = [i for i, (ex, ey) in enumerate(self.en_pos) if math.hypot(px - ex, py - ey) < 0.2]
                if near:
                    self.last_hit_t = self.t
                    self.kill_t += dt
                    if self.kill_t > 0.9:
                        self.kill_t = 0
                        self.en_pos.pop(near[0])
                        self.enemies_left -= 1
            if self.enemies_left == 0 and math.hypot(self.x - c[0], self.y - c[1]) < 0.3:
                self.rooms[c] = mm.CLEARED
                self.cleared_order.append((round(self.t), c))

    # ---------------- env interface ----------------
    def now(self):
        return self.t

    def sleep(self, s):
        end = self.t + max(0.0, s)
        while self.t < end:
            step = min(0.01, end - self.t)
            self.physics(step)
            self.t += step

    def running(self):
        return self.t < self.time_limit + 5

    def in_dungeon(self):
        self.sleep(0.002)
        return self.t < self.time_limit and any(c in (mm.TODO, mm.TREASURE) for c in self.rooms.values())

    def has_minimap(self):
        return True

    def housekeeping(self):
        return False

    def enemies(self):
        if self.enemy_room is not None:
            n = self.en_total
            return Counter(n - self.enemies_left, n, f"{n - self.enemies_left}/{n}")
        return Counter(0, 0, "0/0")

    def dps(self):
        """The DPS meter: something was hit in the last half second."""
        return self.t - self.last_hit_t < 0.5

    def view(self):
        self.sleep(0.006)                         # capture + parse time
        s = LEVELS[self.level]
        p = s * 1.34
        cx, cy = round(self.x), round(self.y)
        n = self.rng.gauss
        offx = (self.x - cx) * p + n(0, self.noise_px)
        offy = (self.y - cy) * p + n(0, self.noise_px)
        if abs(self.x - cx) > 0.5 or abs(self.y - cy) > 0.5:
            pass
        reach = mm.MAP_R / p + 0.6
        cells = {}
        for (a, b), c in self.rooms.items():
            if math.hypot(a - self.x, b - self.y) <= reach and (not self.fog or (a, b) in self.revealed):
                cells[(a - cx, b - cy)] = c
        if (0, 0) not in cells:
            cells[(0, 0)] = mm.HIDDEN
        elif s >= 30 and self.rng.random() < 0.3:
            cells[(0, 0)] = mm.HIDDEN            # sometimes hidden under the arrow
        doors, walls = set(), set()
        for (a, b), c in cells.items():
            for d in ((1, 0), (0, 1)):
                k2 = (a + d[0], b + d[1])
                if k2 not in cells:
                    continue
                g = ((a + cx, b + cy), (k2[0] + cx, k2[1] + cy))
                if g in self.doors:
                    doors.add(((a, b), k2)); doors.add((k2, (a, b)))
                elif cells[(a, b)] != mm.HIDDEN and cells[k2] != mm.HIDDEN:
                    walls.add(((a, b), k2)); walls.add((k2, (a, b)))
        return mm.MapView(s=s, p=p, cells=cells, doors=doors, walls=walls, offx=offx, offy=offy, edges=8)

    def arrow(self):
        a = self.cam if self.arrow_follows == "camera" else self.facing
        return wrap(round(math.degrees(a) / 3) * 3 * math.pi / 180)

    def set_keys(self, keys):
        self.keys = set(keys)
        self.sleep(0.001)

    def tap(self, key, ms=50):
        self.stats["taps"] += 1
        if key == "space":
            self.stats["jumps"] += 1
        self.sleep(ms / 1000)

    def cam_drag(self, px):
        self.stats["drags"] += 1
        held = self.keys
        self.keys = set()
        self.sleep(0.06 + abs(px) / 20 * 0.009 + 0.11)
        if self.rng.random() >= self.drag_fail:
            self.cam = wrap(self.cam + px / self.k_true)
        self.keys = held

    def zoom(self, d):
        self.stats["zoom_clicks"] += 1
        self.level = max(0, min(len(LEVELS) - 1, self.level + (1 if d > 0 else -1)))
        self.sleep(0.1)

    def press_spawn(self):
        self.stats["spawns"] += 1
        self.sleep(0.25)
        self.x, self.y = 0.0, 0.0
        self.enemies_left = 0
        self.enemy_room = None
        self.en_pos = []
        return True

    def set_sprint(self, on):
        self.sprint = on
        self.sleep(0.06)

    def toggle_mount(self, why=""):
        if not self.mount_mult:
            return False
        self.mounted = not self.mounted
        self.mount_presses += 1
        self.log(f"mount key pressed · {why}")
        self.sleep(0.15)
        return True

    def toggle_sprint(self, why=""):
        self.sprint = not self.sprint
        self.sprint_presses += 1
        self.log(f"sprint key pressed · {why}")
        self.sleep(0.06)
        return True

    def status(self, msg):
        pass

    def log(self, msg):
        self.last_msgs.append((round(self.t, 1), msg))
        if self.verbose:
            print(f"{self.t:7.1f}  {msg}")

    def shot(self, tag):
        pass

    def save_setting(self, k, v, quiet=False):
        self.saved[k] = v


def run_one(**kw):
    env = SimEnv(**kw)
    total = sum(1 for c in env.rooms.values() if c in (mm.TODO, mm.TREASURE))
    run = DungeonRun(env)
    run.run()
    done = sum(1 for c in env.rooms.values() if c == mm.CLEARED)
    return env, total, done


if __name__ == "__main__":
    verbose = "--verbose" in sys.argv
    cases = [
        dict(seed=1),
        dict(seed=2),
        dict(seed=3, k_true=900.0),                     # camera turns less per pixel than guessed
        dict(seed=4, k_true=420.0),                     # ...or more
        dict(seed=5, drag_fail=0.25),                   # a quarter of the camera drags don't register
        dict(seed=6, arrow_follows="camera"),
        dict(seed=7, door_w=0.09),                      # narrow doors
        dict(seed=8, look_doors=False),
        dict(seed=9, noise_px=1.0),                     # noisy minimap
    ]
    if verbose:
        cases = cases[:1]
    for kw in cases:
        env, total, done = run_one(verbose=verbose, **kw)
        t_all = env.cleared_order[-1][0] if done == total and env.cleared_order else None
        print(f"{str(kw):45s} cleared {done:2d}/{total} in "
              f"{(str(round(t_all / 60, 1)) + ' min') if t_all else 'the 25 min limit'} · "
              f"drags {env.stats['drags']}, jumps {env.stats['jumps']}, spawns {env.stats['spawns']}, "
              f"zoom clicks {env.stats['zoom_clicks']}, k learned {env.saved.get('cam_px_per_rad', '-')}")
