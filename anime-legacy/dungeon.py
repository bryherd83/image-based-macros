"""Dungeon runner: map memory, route planning, camera direction and steering.

Works through an `env` object (the real game, or the simulator in sim.py):
    env.now() env.sleep(s) env.running()
    env.view() -> MapView | None      env.arrow() -> radians | None
    env.enemies() -> Counter | None   env.in_dungeon() -> bool   env.has_minimap() -> bool
    env.set_keys({'w', 'a'...})       env.tap(key, ms)           env.cam_drag(px)
    env.zoom(-1 | +1)                 env.press_spawn() -> bool  env.housekeeping() -> bool
    env.set_sprint(bool)              env.status(msg)            env.log(msg)   env.shot(tag)
    env.settings (dict)               env.save_setting(key, value)

Positions are in room units: (x, y) = rooms east / south of the spawn room, measured
at the room's centre, so they don't change when the minimap zoom changes.
"""
from __future__ import annotations

import math
import re
from collections import deque

import minimap as mm

TODO_KINDS = (mm.TODO, mm.TREASURE)
SWEEP_SPOTS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def dir_name(d):
    return {(1, 0): "east", (-1, 0): "west", (0, 1): "south", (0, -1): "north"}.get(tuple(d), "?")


# ======================= What the macro remembers of the dungeon =======================
class Memory:
    def __init__(self):
        self.rooms: dict = {}          # (x, y) -> class
        self.doors: set = set()        # ((x,y),(x2,y2)) both ways
        self.walls: set = set()        # gaps seen with no door (both ways)
        self.sure: set = set()         # doors actually walked through
        self.wall_seen: dict = {}
        self.cx = self.cy = 0          # the room you're in
        self.prev_off = None           # (offx, offy, p) of the last read, to see room changes
        self.blocked: dict = {}        # edge -> until (time)
        self.skip: dict = {}           # room -> until
        self.anchored = False
        self.via_unknown = False       # the last plan() goes through a gap not known as a door

    # ---- where you are ----
    def track(self, v: mm.MapView):
        """Notices walking into the next room (your offset inside the room jumps by a room)."""
        if self.prev_off is not None and abs(self.prev_off[2] - v.p) < 1.0:
            ox, oy = self.cx, self.cy
            dx, dy = v.offx - self.prev_off[0], v.offy - self.prev_off[1]
            if dx < -v.p / 2:
                self.cx += 1
            elif dx > v.p / 2:
                self.cx -= 1
            if dy < -v.p / 2:
                self.cy += 1
            elif dy > v.p / 2:
                self.cy -= 1
            if abs(self.cx - ox) + abs(self.cy - oy) == 1:
                self.sure.add(((ox, oy), (self.cx, self.cy)))
                self.sure.add(((self.cx, self.cy), (ox, oy)))
        self.prev_off = (v.offx, v.offy, v.p)

    def forget_offset(self):
        self.prev_off = None

    def merge(self, v: mm.MapView, now: float):
        """Puts the minimap into memory. Spawn on screen = exact position; otherwise check the
        view lines up with memory and correct by one room if it clearly doesn't."""
        moved = False
        for (a, b), c in v.cells.items():
            if c == mm.SPAWN:
                nx, ny = -a, -b
                moved = (nx, ny) != (self.cx, self.cy)
                self.cx, self.cy = nx, ny
                self.anchored = True
                break
        else:
            if self.rooms:
                best, bx, by, s0 = -999, 0, 0, 0
                for dx in (0, -1, 1):
                    for dy in (0, -1, 1):
                        sc = 0
                        for (a, b), c in v.cells.items():
                            if c == mm.HIDDEN:
                                continue
                            mc = self.rooms.get((self.cx + dx + a, self.cy + dy + b))
                            if mc is not None:
                                sc += 1 if (mc == c or (mc in TODO_KINDS and c == mm.CLEARED)) else -1
                        if dx == 0 and dy == 0:
                            s0 = sc
                        if sc > best:
                            best, bx, by = sc, dx, dy
                if (bx or by) and best >= s0 + 3:
                    self.cx += bx
                    self.cy += by
                    moved = True
        for (a, b), c in v.cells.items():
            if c == mm.HIDDEN:
                continue
            self.rooms[(self.cx + a, self.cy + b)] = c
        self.rooms.setdefault((self.cx, self.cy), mm.HIDDEN)
        for (p, q) in v.doors:
            g = ((self.cx + p[0], self.cy + p[1]), (self.cx + q[0], self.cy + q[1]))
            self.doors.add(g)
            self.wall_seen[g] = 0
            self.walls.discard(g)
        for (p, q) in v.walls:
            g = ((self.cx + p[0], self.cy + p[1]), (self.cx + q[0], self.cy + q[1]))
            if g not in self.doors:
                self.walls.add(g)
                continue
            self.wall_seen[g] = self.wall_seen.get(g, 0) + 1
            if self.wall_seen[g] >= (10 if g in self.sure else 3):
                self.doors.discard(g)
                self.doors.discard((g[1], g[0]))
                self.wall_seen.pop(g, None)
        return moved

    def here_kind(self, v: mm.MapView | None = None):
        if v is not None and v.here() != mm.HIDDEN:
            return v.here()
        return self.rooms.get((self.cx, self.cy), mm.HIDDEN)

    # ---- where to go ----
    def is_blocked(self, a, b, now):
        return self.blocked.get((a, b), 0) > now

    def block(self, a, b, now, sec):
        self.blocked[(a, b)] = now + sec
        self.blocked[(b, a)] = now + sec

    def skipped(self, r, now):
        return self.skip.get(r, 0) > now

    def plan(self, now):
        """Shortest route through known doors to the nearest unfinished room: a list of rooms
        starting with yours, or None. With no such route, one that also uses gaps not seen as
        walls (tiny door tabs on the zoomed-out map are easy to miss: laptop 10-19 16:35, 7
        rooms left and no known way to them, so it sat in spawn)."""
        p = self._plan(now, False)
        self.via_unknown = False
        if p is None:
            p = self._plan(now, True)
            self.via_unknown = p is not None
        return p

    def _plan(self, now, unknown_ok):
        start = (self.cx, self.cy)
        if self.rooms.get(start) in TODO_KINDS and not self.skipped(start, now):
            return [start]
        prev = {start: None}
        q = deque([start])
        while q:
            n = q.popleft()
            for d in DIRS:
                k = (n[0] + d[0], n[1] + d[1])
                if k in prev or k not in self.rooms:
                    continue
                if (n, k) not in self.doors and (not unknown_ok or (n, k) in self.walls):
                    continue
                if self.is_blocked(n, k, now):
                    continue
                prev[k] = n
                if self.rooms[k] in TODO_KINDS and not self.skipped(k, now):
                    path = [k]
                    while prev[path[0]] is not None:
                        path.insert(0, prev[path[0]])
                    return path
                q.append(k)
        return None

    def counts(self):
        todo = sum(1 for c in self.rooms.values() if c in TODO_KINDS)
        done = sum(1 for c in self.rooms.values() if c == mm.CLEARED)
        return todo, done


# ======================= Which way the camera looks =======================
class Heading:
    """Camera direction (radians, 0 = east, +pi/2 = south on the minimap), learned from how
    the map moves while walking, and from the mouse movement used to turn the camera.

    W walks where the camera looks, so: direction walked = camera + angle of the keys held."""

    def __init__(self, px_per_rad: float, log, walk_speed: float = 0.0):
        self.psi = None
        self.k = px_per_rad if 60 <= abs(px_per_rad) <= 4000 else 400.0
        self.log = log
        self.seg = None                # (t0, x0, y0, keys)
        # walking speed, rooms per second (normal, not sliding); starts from the learned value so
        # a noisy first reading can't make sliding along a wall look like normal walking
        self.nominal = walk_speed if 0.05 <= walk_speed <= 2.0 else 0.0
        self.recent = deque(maxlen=10)  # latest straight walking (distance, seconds): sprint check
        self.raw_speeds = deque(maxlen=8)  # latest speeds, whatever the direction
        self.odd = 0
        self.turn_pending = None       # (psi_before, px) waiting to be checked by walking
        self.confident = False
        self.k_changed = False
        self.arrow_votes = 0           # >0: the arrow turns with the camera, <0: it doesn't

    @staticmethod
    def key_angle(keys):
        f = ("w" in keys) - ("s" in keys)
        r = ("d" in keys) - ("a" in keys)
        if f == 0 and r == 0:
            return None
        return math.atan2(r, f)

    def reset_segment(self):
        self.seg = None

    def observe(self, t, x, y, keys):
        """Called every frame with your position (rooms) and the keys held."""
        keys = frozenset(keys)
        if self.seg is None or self.seg[3] != keys:
            self.seg = (t, x, y, keys)
            return None
        t0, x0, y0, _ = self.seg
        dt = t - t0
        dx, dy = x - x0, y - y0
        dist = math.hypot(dx, dy)
        ka = self.key_angle(keys)
        if ka is None:
            self.seg = (t, x, y, keys)
            return None
        if dt < 0.18 or (dist < 0.05 and dt < 0.6):
            return None
        self.seg = (t, x, y, keys)
        if dt > 1.5:
            return None
        speed = dist / dt
        if speed < 0.02:
            return None
        self.raw_speeds.append(speed)             # any direction (the mount check uses it)
        # walking the way the keys say (not sliding along a wall): remember the speed, so the
        # dungeon can tell whether sprint is on (sprint stays at nominal, plain walking ~0.6x)
        raw = wrap(math.atan2(dy, dx) - ka)
        if self.psi is not None and abs(wrap(raw - self.psi)) < 0.35:
            self.recent.append((dist, dt))
        if self.nominal == 0:
            self.nominal = speed
        elif speed > 0.7 * self.nominal:
            self.nominal = 0.85 * self.nominal + 0.15 * speed
        if speed < 0.65 * self.nominal:
            return None                           # sliding along a wall: says nothing
        if speed > 3.0 * self.nominal:
            return None                           # a jump in the reading, not walking
        meas = wrap(math.atan2(dy, dx) - ka)
        self._measured(meas)
        return meas

    def _measured(self, meas):
        if self.psi is None:
            self.psi = meas
            self.confident = True
            self.log(f"camera direction learned: {math.degrees(meas):.0f} deg")
            return
        err = wrap(meas - self.psi)
        if self.turn_pending is not None:
            # first good measurement after turning the camera: learn how far the mouse turns it
            # (only from a big turn that started from a measured direction)
            before, px = self.turn_pending
            self.turn_pending = None
            turned = wrap(meas - before)
            if abs(turned) > 0.6 and abs(px) > 150:
                k = px / turned
                if 60 <= abs(k) <= 4000 and abs(k) <= 2 * abs(self.k) and abs(k) >= abs(self.k) / 2 \
                        and (k > 0) == (self.k > 0):
                    self.k = 0.7 * self.k + 0.3 * k
                    self.k_changed = True
            self.psi = meas
            self.odd = 0
            self.confident = True
            return
        if abs(err) > 0.6:
            self.odd += 1
            if self.odd >= 2:                     # keeps happening: believe it
                self.psi, self.odd = meas, 0
            return
        self.odd = 0
        self.psi = math.atan2(2 * math.sin(self.psi) + math.sin(meas), 2 * math.cos(self.psi) + math.cos(meas))
        self.confident = True

    def turned_by_mouse(self, px):
        if self.psi is None:
            return
        # learn from this turn only if the direction before it was measured, not guessed
        self.turn_pending = (self.psi, px) if self.confident else None
        self.psi = wrap(self.psi + px / self.k)
        self.confident = False
        self.seg = None

    def learn_from_arrow(self, px, turned):
        """The arrow turns with the camera: learn the mouse-to-turn ratio from it directly."""
        if abs(turned) > 0.6 and abs(px) > 150:
            k = px / turned
            if 60 <= abs(k) <= 4000 and abs(self.k) / 2 <= abs(k) <= 2 * abs(self.k) and (k > 0) == (self.k > 0):
                self.k = 0.7 * self.k + 0.3 * k
                self.k_changed = True

    def from_arrow(self, a):
        """Arrow reading while standing still (only used when it's known to follow the camera)."""
        if a is not None and self.arrow_votes >= 2:
            self.psi = a
            self.confident = True


# ======================= Steering =======================
def keys_for(vx, vy, psi, tol=0.0, lat_tol=0.0):
    """Keys that move along map vector (vx, vy) given camera direction psi."""
    fx, fy = math.cos(psi), math.sin(psi)
    fw = vx * fx + vy * fy
    rt = -vx * fy + vy * fx
    big = max(abs(fw), abs(rt))
    keys = set()
    if fw > tol and fw >= 0.38 * big:
        keys.add("w")
    if fw < -tol and -fw >= 0.38 * big:
        keys.add("s")
    if rt > tol and (rt >= 0.38 * big or (lat_tol and rt > lat_tol)):
        keys.add("d")
    if rt < -tol and (-rt >= 0.38 * big or (lat_tol and -rt > lat_tol)):
        keys.add("a")
    return keys


# ======================= The run =======================
class DungeonRun:
    def __init__(self, env, resume_from=None):
        self.env = env
        S = env.settings
        self.S = S
        self.mem = resume_from.mem if resume_from else Memory()
        self.head = resume_from.head if resume_from else Heading(
            float(S.get("cam_px_per_rad", 584)), env.log, float(S.get("walk_rooms_per_sec", 0.27)))
        if resume_from:
            self.head.reset_segment()
            self.mem.forget_offset()
        self.resumed = resume_from is not None
        self.keys = set()
        self.walk_lo, self.walk_hi = S.get("walk_room_px", [41, 48])
        self.last_scan = -1e9
        self.room_enter_t = env.now()
        self.cell = None
        self.clear_key, self.clear_t = None, 0
        self.door_fail = {}            # edge -> attempts
        self.attempt = None            # current door attempt
        self.last_spawn = -1e9
        self.last_progress_t = env.now()
        self.progress_ref = None
        self.recover_until = 0
        self.recover_vec = (0.0, 0.0)
        self.recover_why = ""
        self.sprint = False
        self.sprint_t, self.sprint_pause, self.sprint_taps = -1e9, 0.0, []
        self.sprint_check = None        # speed just before a sprint press (to check it helped)
        # sprint speed (rooms/s), learned; starts from the walking speed saved before this
        # change (those runs sprinted)
        self.sprint_ref = float(env.settings.get("sprint_rooms_per_sec", 0) or
                                env.settings.get("walk_rooms_per_sec", 0.4))
        # the mount: much faster than sprinting. M gets on and off it and nothing on screen says
        # which, so like sprint it's judged by the walking speed: the first check presses M and
        # the next one sees if that made it faster (if slower, it was already on: press again)
        self.mount = bool(env.settings.get("ride_mount", True)) and hasattr(env, "toggle_mount")
        self.dismount_tried = False
        self.arrow_cam = bool(env.settings.get("arrow_is_camera", True)) and hasattr(env, "arrow")
        self.dismount_check = None
        # (known to be on already - the game keeps you mounted through teleports - no probe)
        self.mount_probe = self.mount and getattr(env, "mount_on", None) is not True
        if self.mount:
            self.sprint_ref = max(self.sprint_ref, float(env.settings.get("mount_rooms_per_sec", 0) or 0))
        self.covered_since = None
        self.v = None
        self.misses = 0
        self.no_map = 0
        self.rooms_cleared = 0
        self.last_here = None
        self.lineup = False
        self.centred = False
        self.last_status = ""
        self.finished = False
        self.arrow_check = None
        self.last_turn = (None, -1e9)  # (edge, time) of the last camera turn
        self.turns_here = 0
        self.leave_t = None            # when it started trying to leave this room
        self.fight_since = None
        self.hold_room_until = 0.0
        self.last_zoom_fix = -1e9
        self.stuck_here = 0            # unstick attempts since it last got somewhere
        # a Trial popup while the dungeon is still going (see trial_check)
        self.last_clear_t = resume_from.last_clear_t if resume_from else env.now()
        self.done_seen = resume_from.done_seen if resume_from else 0
        self.cleared_seen = 0
        self.trial_seen_t = resume_from.trial_seen_t if resume_from else None
        self.trial_gone = False
        self.left_for = None           # "trial" = it clicked the Trial popup and left
        self.last_popup_check = -1e9
        # DPS meter (top left): is anything being hit? None = can't tell (old way: by the clock)
        self.hitting = None
        self.last_hit_t = -1e9
        self.en_text, self.en_change_t = None, -1e9
        self.sweep_i, self.sweep_since = 0, None

    # ---------------- helpers ----------------
    def say(self, msg):
        if msg != self.last_status:
            self.last_status = msg
            self.env.status(msg)
            norm = re.sub(r"[\d.]+", "#", msg)
            if norm != getattr(self, "_last_norm", None):
                self._last_norm = norm
                self.env.log(msg)

    def hold(self, keys):
        keys = set(keys)
        if keys != self.keys:
            self.keys = keys
            self.env.set_keys(keys)

    def stop(self):
        self.hold(set())

    def clip(self, why):
        """NVIDIA Instant Replay clip of what just happened (the real game only)."""
        clip = getattr(self.env, "clip", None)
        if clip:
            clip(why)

    def trial_check(self, now):
        """The Trial pops up 15 minutes after the Dungeon. If the dungeon is still going then,
        finish it (the farm joins the trial afterwards if its popup is still up), unless the
        dungeon has gone dungeon_leave_for_trial_sec (2 min) without a new room cleared: then
        click the Trial popup and leave. True if it left."""
        popup = getattr(self.env, "popup", None)
        if popup is None or not self.S.get("join_trials", False):
            return False
        _, done = self.mem.counts()
        if done > self.done_seen or self.rooms_cleared > self.cleared_seen:
            self.done_seen, self.cleared_seen = max(done, self.done_seen), self.rooms_cleared
            self.last_clear_t = now
        p = popup()
        if p is None or p.kind != "trial":
            if self.trial_seen_t is not None and not self.trial_gone:
                self.trial_gone = True
                self.env.log(f"the trial popup went away after {now - self.trial_seen_t:.0f}s · finishing the dungeon")
            return False
        quiet = now - self.last_clear_t
        if self.trial_seen_t is None:
            self.trial_seen_t = now
            self.env.log(f"trial popped up · dungeon still going ({done} rooms cleared, the last one "
                         f"{quiet:.0f}s ago) · finishing it unless 2 min go by without a new room")
            self.env.shot("trial-popup-in-dungeon")
        if quiet < float(self.S.get("dungeon_leave_for_trial_sec", 120)):
            return False
        self.stop()
        self.clip("dungeon stalled when the trial popped up")
        self.env.click(p.x, p.y)
        self.env.log(f"leaving the dungeon for the trial · no new room cleared for {quiet / 60:.1f} min")
        self.left_for = "trial"
        return True

    def pos(self):
        v = self.v
        return self.mem.cx + v.offx / v.p, self.mem.cy + v.offy / v.p

    def read(self):
        """One fresh minimap read: updates memory, position and camera direction."""
        v = self.env.view()
        if v is None:
            return None
        self.v = v
        self.mem.track(v)
        if self.mem.merge(v, self.env.now()):
            self.head.reset_segment()
        x, y = self.pos()
        self.head.observe(self.env.now(), x, y, self.keys)
        if self.arrow_cam:
            a = self.env.arrow()
            if a is not None:
                self.head.psi, self.head.confident, self.head.turn_pending = a, True, None
        if self.head.k_changed:
            self.head.k_changed = False
            self.env.save_setting("cam_px_per_rad", round(self.head.k))
        if self.head.nominal:
            self.env.save_setting("walk_rooms_per_sec", round(self.head.nominal, 3), quiet=True)
            if 0.1 <= self.sprint_ref <= 3.0:
                self.env.save_setting("mount_rooms_per_sec" if self.mount else "sprint_rooms_per_sec",
                                      round(self.sprint_ref, 3), quiet=True)
        return v

    # ---------------- minimap zoom ----------------
    def zoom_to(self, lo, hi, max_clicks=18):
        self.stop()
        last_s, same, last_dir = None, 0, 0
        for _ in range(max_clicks):
            v = self.env.view()
            if v is None:
                self.env.sleep(0.15)
                v = self.env.view()
                if v is None:
                    break
            if lo <= v.s <= hi:
                break
            same = same + 1 if v.s == last_s else 0
            if same >= 2:                  # clicks aren't changing the zoom: stop trying
                # (at the end of a dungeon the map goes away mid-zoom: that's not a problem)
                if self.env.has_minimap():
                    self.env.log(f"minimap zoom stuck at {v.s}px rooms (clicks not registering?)")
                break
            d = -1 if v.s > hi else +1
            if last_dir and d != last_dir:
                # overshot (no zoom step lands in lo..hi, or a misread size): stay here rather
                # than clicking - and + back and forth (PC 10-19 16:0x: a 10 s burst of that)
                if d == +1:
                    self.env.zoom(+1)      # (prefer the bigger of the two sizes)
                    self.env.sleep(0.12)
                break
            last_s, last_dir = v.s, d
            self.env.zoom(d)
            self.env.sleep(0.12)
        self.mem.forget_offset()
        self.head.reset_segment()
        park = getattr(self.env, "park_mouse", None)
        if park:
            park()

    def scan(self, why):
        """Zoom all the way out, remember everything visible, zoom back in."""
        self.say(f"{why} · looking at the whole map")
        self.stop()
        lo = int(self.S.get("scan_room_px", 10))
        last_s = None
        for _ in range(18):
            v = self.env.view()
            if v is not None:
                self.mem.forget_offset()
                self.mem.track(v)
                self.mem.merge(v, self.env.now())
                if v.s <= lo or v.s == last_s:
                    break
                last_s = v.s
            self.env.zoom(-1)
            self.env.sleep(0.12)
        self.env.sleep(0.2)
        for _ in range(2):              # two reads at the widest zoom
            v = self.env.view()
            if v is not None:
                self.mem.forget_offset()
                self.mem.track(v)
                self.mem.merge(v, self.env.now())
            self.env.sleep(0.08)
        self.zoom_to(self.walk_lo, self.walk_hi)
        self.last_scan = self.env.now()
        todo, done = self.mem.counts()
        self.env.log(f"map: {len(self.mem.rooms)} rooms known, {todo} to do, {done} cleared, "
                     f"{len(self.mem.doors) // 2} doors")

    # ---------------- camera ----------------
    def measure_heading(self):
        """Step forward and back a little and watch the map (W walks where the camera looks)."""
        self.stop()
        if self.arrow_cam:
            a = self.env.arrow()
            if a is not None:
                self.head.psi, self.head.confident = a, True
                return True
        for keys in ({"w"}, {"s"}, {"d"}, {"a"}):
            self.head.reset_segment()
            t0 = self.env.now()
            self.hold(keys)
            got = False
            while self.env.now() - t0 < 0.45:
                self.env.sleep(0.04)
                if self.read() is None:
                    continue
                if self.head.psi is not None and self.head.seg is not None and self.head.confident \
                        and self.env.now() - t0 > 0.2:
                    got = True
            self.stop()
            self.env.sleep(0.08)
            self.read()
            if got and self.head.psi is not None:
                return True
        a = self.env.arrow()
        if a is not None and self.head.psi is None:
            self.head.psi = a
            self.env.log("camera direction from the minimap arrow (couldn't walk)")
            return True
        return self.head.psi is not None

    def face(self, target, edge, min_err=0.12):
        """Turn the camera to look along `target` (map angle). One drag, checked while walking."""
        h = self.head
        if h.psi is None:
            return
        d = wrap(target - h.psi)
        if abs(d) < min_err:
            return
        self.stop()
        a0 = self.env.arrow()
        px = round(d * h.k)
        self.say(f"turning the camera to face the door ({math.degrees(d):+.0f} deg)")
        self.env.cam_drag(px)
        h.turned_by_mouse(px)
        if self.arrow_cam and a0 is not None:
            # check the turn on the arrow (Roblox drops part of a drag at a low frame rate) and
            # correct it, at most twice; learn the mouse-to-turn ratio from it
            for i in range(3):
                self.env.sleep(0.2)
                a1 = self.env.arrow()
                if a1 is None:
                    break
                turned = wrap(a1 - a0)
                if i == 0 and abs(d) > 0.6 and abs(turned) > 0.3:
                    h.learn_from_arrow(px, turned)
                h.psi, h.confident, h.turn_pending = a1, True, None
                left = wrap(target - a1)
                if abs(left) < 0.12 or i == 2:
                    break
                a0, px = a1, round(left * h.k)
                self.env.cam_drag(px)
            self.last_turn = (edge, self.env.now())
            self.turns_here += 1
            self.progress_ref = None        # (turning took a moment: not 'stuck')
            return
        self.last_turn = (edge, self.env.now())
        self.turns_here += 1
        # does the minimap arrow turn with the camera? (then it tells us the direction for free)
        self.env.sleep(0.12)
        a1 = self.env.arrow()
        if a0 is not None and a1 is not None and abs(d) > 0.6:
            da = wrap(a1 - a0)
            if abs(wrap(da - d)) < 0.35:
                h.arrow_votes = min(5, h.arrow_votes + 1)
            elif abs(da) < 0.15:
                h.arrow_votes = max(-5, h.arrow_votes - 1)
            if h.arrow_votes >= 2:
                h.learn_from_arrow(px, da)
                h.from_arrow(a1)
                h.turn_pending = None

    # ---------------- unsticking ----------------
    def start_recovery(self, path):
        """Not getting anywhere: a different move each time; give the door up after a few."""
        e = self.env
        now = e.now()
        self.stuck_here += 1
        if self.stuck_here >= 9 and now - self.last_spawn > 60 and e.press_spawn():
            # nothing works from here (trapped, or the map reading is off): start over from spawn
            e.log("stuck over and over in the same place · pressed Spawn")
            e.shot("stuck-pressed-spawn")
            self.clip("dungeon: stuck over and over")
            if len(path) > 1:
                self.mem.block(path[0], path[1], now, 180)
            self.last_spawn = e.now()
            self.stuck_here = 0
            self.mem.forget_offset()
            self.head.reset_segment()
            self.stop()
            e.sleep(1.5)
            self.scan("after Spawn")
            return
        edge = (path[0], path[1]) if len(path) > 1 else None
        n = self.door_fail.get(edge, 0) + 1
        self.door_fail[edge] = n
        if edge is None:
            e.tap("space", 80)
            # no door to aim for: just jump
            self.recover_vec, self.recover_until, self.recover_why = (0, 0), now + 0.8, "stuck · jumping"
            return
        dx, dy = path[1][0] - path[0][0], path[1][1] - path[0][1]
        side = (-dy, dx)
        if n == 1:
            # most likely the camera direction is off: measure it again, then line up again
            self.recover_why = "stuck · checking which way the camera looks"
            self.stop()
            self.measure_heading()
            self.recover_vec, self.recover_until = (-dx * 0.18, -dy * 0.18), now + 0.9
        elif n == 2:
            e.tap("space", 80)
            self.recover_vec, self.recover_until = (-dx * 0.2, -dy * 0.2), now + 1.0
            self.recover_why = "stuck · jumping and backing up"
        elif n <= 4:
            off = (0.07 if n <= 3 else 0.14) * (1 if n % 2 else -1)
            self.recover_vec = (-dx * 0.2 + side[0] * off, -dy * 0.2 + side[1] * off)
            self.recover_until = now + 1.2
            self.recover_why = f"stuck ({n}) · backing up and stepping {'right' if off > 0 else 'left'}"
            e.tap("space", 80)
        else:
            self.mem.block(path[0], path[1], now, 45)
            self.door_fail[edge] = 0
            self.recover_until = 0
            self.say(f"door {dir_name((dx, dy))} won't open · trying another way for 45s")
            e.shot("door-blocked")
            return
        e.log(self.recover_why)
        if n >= 3:
            e.shot(f"stuck-{n}")

    # ---------------- main loop ----------------
    def run(self):
        e = self.env
        S = self.S
        self.left_for = None
        self.say("dungeon: reading the minimap")
        if not self.resumed:
            self.scan("dungeon started")
        else:
            self.zoom_to(self.walk_lo, self.walk_hi)
        stuck_spawn_sec = float(S.get("dungeon_stuck_spawn_sec", 40))
        room_timeout = float(S.get("dungeon_room_timeout_sec", 60))
        sweep_after = float(S.get("sweep_after_sec", 6))
        sweep_step = float(S.get("sweep_step_sec", 2.5))
        sweep_dist = float(S.get("sweep_dist", 0.22))
        sweep_far = float(S.get("sweep_far", 0.25))          # how far out the round goes
        sweep_quiet = float(S.get("sweep_quiet_sec", 1.5))   # nothing hit this long: go and look
        sweep_dwell = float(S.get("sweep_dwell_sec", 0.6))   # at each spot, once nothing is hit
        # a route longer than this many rooms = look at the whole map first (at most every
        # far_scan_sec): something unfinished may be closer than the rooms remembered
        far_scan_rooms = int(S.get("far_scan_rooms", 8))     # was 4: 5 looks per dungeon, ~5 s each
        far_scan_sec = float(S.get("far_scan_sec", 60))
        face_doors = bool(S.get("face_doors", True))
        use_sprint = bool(S.get("dungeon_sprint", True))
        last_hud = 0.0
        last_house = 0.0
        last_far = -1e9
        en = None
        while e.running():
            now = e.now()
            # ---- still in the dungeon? (checked a few times a second)
            if now - last_hud > 0.35:
                last_hud = now
                # a black full-screen animation (auto trait roll) hides the HUD for a few
                # seconds: that's not the dungeon ending. Wait it out (30 s at most).
                cov = getattr(e, "covered", None)
                if cov and cov():
                    self.stop()
                    self.covered_since = self.covered_since or now
                    if now - self.covered_since < 30:
                        self.misses = self.no_map = 0
                        self.say("screen covered (trait roll?) · waiting")
                        e.sleep(0.3)
                        continue
                else:
                    self.covered_since = None
                if not e.in_dungeon():
                    self.stop()
                    self.misses += 1
                    if self.misses >= 6:
                        self.finished = True
                        break
                    e.sleep(0.3)
                    continue
                self.misses = 0
                if now - last_house > 1.0:
                    last_house = now
                    if e.housekeeping():      # closed a popup / menu
                        self.stop()
                        continue
                    if not e.has_minimap():
                        self.no_map += 1
                        if self.no_map >= 3:
                            self.say("no minimap · this isn't a dungeon")
                            break
                    else:
                        self.no_map = 0
                if now - self.last_popup_check > 2.0:
                    self.last_popup_check = now
                    if self.trial_check(now):
                        break
                    tr = getattr(e, "trace", None)
                    if tr and self.v is not None:
                        pth = self.mem.plan(now)
                        tr(f"{getattr(e, '_last_status', '')}\nroom {self.mem.cx},{self.mem.cy} "
                           f"off {self.v.offx:+.0f},{self.v.offy:+.0f} cam "
                           f"{'?' if self.head.psi is None else round(math.degrees(self.head.psi))} "
                           f"route {pth} doors {len(self.mem.doors) // 2} walls {len(self.mem.walls) // 2}")
                en = e.enemies()
                dps = getattr(e, "dps", None)
                self.hitting = dps() if dps else None
                if self.hitting:
                    self.last_hit_t = now
                if en is not None and en.text != self.en_text:
                    self.en_text, self.en_change_t = en.text, now
                info = getattr(e, "info", None)
                if isinstance(info, dict):        # (the live status page)
                    todo, done = self.mem.counts()
                    info["rooms"] = f"{done} cleared · {todo} to do · {len(self.mem.rooms)} seen"
            v = self.read()
            if v is None:
                self.stop()
                self.say("can't read the minimap")
                e.sleep(0.1)
                continue
            if v.s < 24 and now - self.last_zoom_fix > 5:
                # too far out to walk precisely (zoom clicks can get lost): zoom in again,
                # but don't insist - any zoom from about 24 px rooms up works for walking
                self.last_zoom_fix = now
                self.zoom_to(self.walk_lo, self.walk_hi)
                continue
            if self.head.psi is None:
                self.say("learning which way the camera faces")
                if not self.measure_heading():
                    e.sleep(0.2)
                continue
            cell = (self.mem.cx, self.mem.cy)
            if cell != self.cell:
                self.cell, self.room_enter_t = cell, now
                self.lineup = self.centred = False
                self.turns_here = 0
                self.leave_t = None
                self.stuck_here = 0
            here = self.mem.here_kind(v)
            if self.last_here in TODO_KINDS and here == mm.CLEARED:
                self.rooms_cleared += 1
            self.last_here = here
            fight = en is not None and en.b > 0 and en.a < en.b
            if here in (mm.SPAWN, mm.CLEARED):
                # nothing to fight in the spawn room or a cleared one: the ENEMIES counter can
                # still show the last room's enemies (PC 10-19 14:32: after Spawn it showed 3/4
                # and the farm "fought" in the spawn room for a minute instead of leaving)
                fight = False
            if fight and self.fight_since is None:
                self.fight_since = now
            elif not fight:
                self.fight_since = None
            path = self.mem.plan(now)
            # nothing unfinished known (or only far away): look at the whole map
            if not fight and ((path is None and now - self.last_scan > 15)
                              or (path is not None and len(path) > far_scan_rooms
                                  and now - self.last_scan > far_scan_sec)):
                self.scan("next room is far" if path else "no unfinished rooms known")
                continue
            # enemies alive: doors stay shut until they're dead, so wait in this room - unless the
            # route's next room is the one to clear (then the fight is probably in there: go in)
            fighting_here = fight and (path is None or len(path) > 2 or now < self.hold_room_until) \
                and now - self.fight_since < room_timeout
            if fighting_here:
                path = [cell]
                self.leave_t = None
            if path is None:
                self.stop()
                if now - last_far > 20 and now - self.last_spawn > 60:
                    last_far = now
                    if e.press_spawn():
                        self.last_spawn = e.now()
                        self.mem.forget_offset()
                        self.head.reset_segment()
                        e.sleep(1.5)
                        self.scan("pressed Spawn to look from there")
                        continue
                todo, done = self.mem.counts()
                self.say(f"no unfinished rooms found · waiting ({len(self.mem.rooms)} rooms known)")
                e.sleep(0.3)
                continue
            x, y = self.pos()
            fx, fy = x - cell[0], y - cell[1]               # position inside this room (rooms)
            if self.mem.via_unknown and not fighting_here and len(path) > 1 \
                    and (cell, path[1]) not in self.mem.doors and now >= self.recover_until:
                # the only way on is a gap with no door seen in it (PC 10-19 20:09: the arrow
                # covered the wall south of the room, so it counted as maybe a door and the farm
                # kept running into it). Like Blayne would: look at the whole map first, then
                # stand in the middle of the room (the arrow can't cover a door from there) and
                # read the doors again
                if now - self.last_scan > 15:
                    self.scan("no door seen to the next room")
                    continue
                if math.hypot(fx, fy) > 0.15:
                    self.recover_vec, self.recover_until = (0.0, 0.0), now + 0.6
                    self.recover_why = "no door seen there · checking from the middle of the room"
            lat_tol = 0.0
            tol = 0.0
            # standing in a doorway (just came through it)? walk straight into the room first:
            # moving sideways in there only scrapes the doorway's walls
            gap = None
            if abs(fx) > 0.36 and abs(fx) >= abs(fy):
                gap = (1 if fx > 0 else -1, 0)
            elif abs(fy) > 0.36:
                gap = (0, 1 if fy > 0 else -1)
            toward_next = len(path) > 1 and gap == (path[1][0] - cell[0], path[1][1] - cell[1])
            if now < self.recover_until:
                vx, vy = self.recover_vec[0] - fx, self.recover_vec[1] - fy
                what = self.recover_why
            elif gap is not None and not toward_next:
                vx, vy = (-fx, 0.0) if gap[0] else (0.0, -fy)
                what = "walking into the room"
            elif len(path) == 1:
                # ---- in the room to clear: stand in the middle; if it doesn't clear, walk a square
                if self.clear_key != cell:
                    self.clear_key, self.clear_t = cell, now
                    self.sweep_i, self.sweep_since = 0, None
                waited = now - self.clear_t
                tx = ty = 0.0
                what = (f"enemies left ({en.text})" if fight else f"clearing a {mm.NAMES.get(here, '?')} room")
                # nothing hit and nothing killed for a moment while enemies are left: they're out
                # of reach, so go and look (don't stand in the middle for sweep_after first)
                quiet = now - max(self.clear_t, self.last_hit_t, self.en_change_t)
                out_of_reach = self.hitting is False and fight and waited >= 1.5 and quiet >= sweep_quiet
                if self.sweep_since is None and (waited >= sweep_after or out_of_reach):
                    self.sweep_since = self.sweep_t = now
                if self.sweep_since is not None and self.hitting is None:
                    # DPS meter unreadable: the four corners in turn, by the clock (as before)
                    i = int((now - self.sweep_since) // sweep_step) % 4
                    cx_, cy_ = ((-1, -1), (1, -1), (1, 1), (-1, 1))[i]
                    tx, ty = cx_ * sweep_dist, cy_ * sweep_dist
                    what += " · walking around the room"
                elif self.sweep_since is not None:
                    # all round the room; stay wherever something is being hit, move on once
                    # nothing has been for a moment (or the spot can't be reached)
                    cx_, cy_ = SWEEP_SPOTS[self.sweep_i % len(SWEEP_SPOTS)]
                    tx, ty = cx_ * sweep_far, cy_ * sweep_far
                    there = math.hypot(tx - fx, ty - fy) <= 0.06
                    if (there and now - max(self.sweep_t, self.last_hit_t) > sweep_dwell) \
                            or now - max(self.sweep_t, self.last_hit_t) > 3.0:
                        self.sweep_i += 1
                        self.sweep_t = now
                        cx_, cy_ = SWEEP_SPOTS[self.sweep_i % len(SWEEP_SPOTS)]
                        tx, ty = cx_ * sweep_far, cy_ * sweep_far
                    what += " · walking around the room"
                if waited > room_timeout:
                    self.mem.skip[cell] = now + 120
                    self.clear_key = None
                    e.log("room won't clear · skipping it for 2 minutes")
                    continue
                vx, vy = tx - fx, ty - fy
                dc = math.hypot(vx, vy)
                self.centred = dc <= (0.06 if self.centred else 0.03)
                if self.centred:
                    self.stop()
                    self.say(f"{what} · {waited:.0f}s")
                    self.progress_ref = None
                    e.sleep(0.05)
                    continue
                what += " · walking to the middle" if self.sweep_since is None else ""
            else:
                # ---- go through the door to the next room on the route
                self.clear_key = None
                if self.leave_t is None:
                    self.leave_t = now
                nx, ny = path[1][0] - cell[0], path[1][1] - cell[1]
                perp = fy if nx else fx                     # off the door's centre line
                along = fx * nx + fy * ny                   # how far toward the door
                want = math.atan2(ny, nx)
                yaw_err = wrap(want - self.head.psi)
                # look at the door first (doors open while you look at them, and walking
                # straight with W is the most precise way through a narrow doorway)
                if face_doors and self.turns_here < 6 and along < 0.42 and (
                        abs(yaw_err) > 0.35 or (abs(yaw_err) > 0.13 and self.head.confident)):
                    self.face(want, (path[0], path[1]))
                    continue
                if not self.lineup and abs(perp) > 0.05 and along < 0.3:
                    self.lineup = True
                if self.lineup and (abs(perp) <= 0.018 or along >= 0.3):
                    self.lineup = False
                if self.lineup:
                    # step sideways onto the door's centre line (not back to the middle)
                    vx, vy = (0.0, -fy) if nx else (-fx, 0.0)
                    what = "lining up with the door"
                else:
                    # straight at the door; small sideways corrections on the way (part-time
                    # diagonal: the more off the centre line, the longer the diagonal key is held)
                    vx, vy = float(nx), float(ny)
                    duty = 0.0 if abs(perp) < 0.006 else min(1.0, abs(perp) / 0.035)
                    if duty > ((now * 5.0) % 1.0):
                        sx_, sy_ = (0.0, -math.copysign(1, perp)) if nx else (-math.copysign(1, perp), 0.0)
                        vx, vy = vx + sx_, vy + sy_
                    what = f"going through the door {dir_name((nx, ny))}"
                what += f" · {len(path) - 1} room(s) to go"
            # ---- move
            dist = math.hypot(vx, vy)
            near = dist < 0.12
            keys = keys_for(vx, vy, self.head.psi, tol, lat_tol)
            if near and keys:
                # close to the spot: short presses sized to the distance, so it stops on it
                spd = self.head.nominal or float(S.get("walk_rooms_per_sec", 0.27))
                ms = max(30, min(160, 0.75 * dist / max(spd, 0.05) * 1000))
                self.hold(keys)
                e.sleep(ms / 1000)
                self.stop()
                e.sleep(0.05)
                self.progress_ref = None
                self.say(what)
                continue
            self.hold(keys)
            if keys:
                self.check_dismount(now)
            if use_sprint and keys:
                self.check_sprint(now)
            self.say(what)
            # ---- not getting anywhere? (keys held but the position doesn't change)
            if keys and now >= self.recover_until:
                if self.progress_ref is None:
                    self.progress_ref = (now, x, y)
                else:
                    t0, x0, y0 = self.progress_ref
                    if math.hypot(x - x0, y - y0) > 0.06:
                        self.progress_ref = (now, x, y)
                    elif now - t0 > 0.9:
                        self.progress_ref = None
                        if fight and len(path) > 1:
                            # door shut because of the fight: wait in the middle instead
                            self.hold_room_until = now + 6
                        else:
                            self.start_recovery(path)
            else:
                self.progress_ref = None
            # ---- been trying to leave this room for too long: Spawn and avoid that door
            if len(path) > 1 and self.leave_t is not None and now - self.leave_t > stuck_spawn_sec \
                    and now - self.last_spawn > 60:
                if e.press_spawn():
                    e.log(f"stuck in a room for {stuck_spawn_sec:.0f}s · pressed Spawn")
                    e.shot("stuck-pressed-spawn")
                    self.clip("dungeon: stuck in a room")
                    self.mem.block(path[0], path[1], e.now(), 180)
                    self.last_spawn = e.now()
                    self.mem.forget_offset()
                    self.head.reset_segment()
                    self.stop()
                    e.sleep(1.5)
                    self.room_enter_t = e.now()
                    self.scan("after Spawn")
                    continue
            e.sleep(0.02)
        self.stop()
        return self.finished

    def check_dismount(self, now):
        """Riding switched off but still on the mount (the game keeps you on it through
        teleports): moving far faster than sprinting, in whatever direction (a mount doesn't go
        where the keys say, so the straight-walking speeds can't be used) - press M, once per
        dungeon, and once more if that made it faster (it was off: back off it)."""
        e, h = self.env, self.head
        if self.mount or not hasattr(e, "toggle_mount") or len(h.raw_speeds) < 6:
            return
        sp = sorted(h.raw_speeds)[len(h.raw_speeds) // 2]
        ref = self.sprint_ref
        if self.dismount_check is not None:
            if now - self.dismount_check[0] < 2.5:
                return
            before = self.dismount_check[1]
            self.dismount_check = None
            if sp > 1.2 * before:
                e.toggle_mount("faster after that press, so it got on the mount · getting off again")
            e.mount_on = False
            return
        if self.dismount_tried or sp < 1.35 * ref:
            return
        self.dismount_tried = True
        h.raw_speeds.clear()
        if e.toggle_mount(f"moving at {sp / ref:.1f}x sprint speed, so still on the mount · getting off"):
            self.dismount_check = (now, sp)

    def check_mount(self, now, med, ref):
        """check_sprint with the mount key instead of sprint (the "fast speed" is then the
        mount's)."""
        h, e = self.head, self.env
        if self.sprint_check is not None:
            before, self.sprint_check = self.sprint_check, None
            h.recent.clear()
            self.sprint_t = now
            if med < 0.95 * before:
                e.toggle_mount("slower after that press, so it was already on the mount · pressing again")
                self.sprint_pause = now + 120
                e.mount_on = True
            else:
                if med >= 0.78 * self.sprint_ref or med > 1.15 * before:
                    e.mount_on = True
                if med > 1.15 * before:
                    e.log(f"on the mount · {med / max(before, 1e-6):.1f}x as fast as before")
                    self.sprint_ref = max(ref, med)
                if med >= 0.78 * self.sprint_ref:
                    self.sprint_taps.clear()
            return
        if not self.mount_probe and med >= 0.82 * ref:
            e.mount_on = True
            if med >= 0.92 * ref:                # on the mount: keep its speed up to date
                self.sprint_ref = med if med > 1.25 * ref else 0.9 * ref + 0.1 * med
            return
        self.sprint_taps = [t for t in self.sprint_taps if now - t < 120]
        if len(self.sprint_taps) >= 3:
            self.sprint_pause = now + 120
            e.log("walking stays slow after 3 mount presses · leaving the mount alone for 2 minutes")
            return
        why = "getting on the mount" if self.mount_probe else \
            f"walking at {med / ref:.0%} of mount speed, so not on the mount"
        self.mount_probe = False
        if e.toggle_mount(why):
            self.sprint_taps.append(now)
            self.sprint_check = med
        elif why == "getting on the mount":
            self.mount = False                   # no mount here: look after sprint instead
            return
        self.sprint_t = now
        h.recent.clear()

    def check_sprint(self, now):
        """Sprint is a toggle that stays on (also through teleports), and nothing on screen says
        whether it is. So: if the last straight-walking speeds are well under the sprint speed
        (the learned walking speed), sprint is off: tap it (while walking - the game needs
        that). At most every 8 s; 3 taps in 2 minutes that didn't help = leave it for 2 min."""
        h, e = self.head, self.env
        if len(h.recent) < 10 or now - self.sprint_t < 8 or now < self.sprint_pause:
            return
        dist, secs = sum(d for d, _ in h.recent), sum(t for _, t in h.recent)
        if secs < 1.5:
            return
        med = dist / secs                        # average straight-walking speed lately
        ref = self.sprint_ref
        if self.mount:
            return self.check_mount(now, med, ref)

        if self.sprint_check is not None:
            # just pressed it: faster now = it was off (good); slower = it had been on and
            # that press turned it off (an enemy or wall slowed the walk): press again
            before, self.sprint_check = self.sprint_check, None
            h.recent.clear()
            if med < 0.95 * before:
                toggle = getattr(e, "toggle_sprint", None)
                if toggle:
                    toggle("slower after that press, so sprint had been on · pressing again")
                self.sprint_pause = now + 120
            elif med >= 0.78 * ref:
                self.sprint_taps.clear()
            e.sprint_on = True                   # (trials use this to turn it off)
            return
        if med >= 0.82 * ref:
            # sprinting: keep the sprint speed up to date (the walking-speed estimate can't be
            # used - it slowly follows whatever speed you walk at, sprint on or off). Only from
            # clearly-sprinting stretches, so it can't drift down to plain walking speed.
            if med >= 0.92 * ref:
                self.sprint_ref = med if med > 1.25 * ref else 0.9 * ref + 0.1 * med
            e.sprint_on = True
            return
        self.sprint_taps = [t for t in self.sprint_taps if now - t < 120]
        if len(self.sprint_taps) >= 3:
            self.sprint_pause = now + 120
            self.env.log("walking stays slow after 3 sprint presses · leaving sprint alone for 2 minutes")
            return
        toggle = getattr(e, "toggle_sprint", None)
        e.sprint_on = False                      # (the press below turns it on)
        if toggle and toggle(f"walking at {med / ref:.0%} of sprint speed, so sprint was off"):
            self.sprint_taps.append(now)
            self.sprint_check = med
        self.sprint_t = now
        h.recent.clear()
