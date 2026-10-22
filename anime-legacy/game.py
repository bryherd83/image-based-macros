"""The real game behind the `env` interface used by dungeon.py / trial.py / culling.py."""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import threading
import time

import cv2
import numpy as np

import hud
import minimap as mm
import winio

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(HERE, "settings.json")
AHK_INI = os.path.expandvars(r"%USERPROFILE%\Downloads\anime-legacy-settings.ini")

DEFAULTS = {
    "mode": "dungeon",                 # culling | dungeon | both
    "join_trials": True,
    "trial_leave_after": 27,
    "leave_at_wave": 9,                # Culling Game: leave when the wave counter reaches this (0 = never)
    "skill_key": "",                   # e.g. "z" to press it every 1.5 s in runs ("" = never)
    "worlds_key": "t",
    "anti_afk_minutes": 10,
    "idle_click_sec": 0,               # was 45: clicking the world opened boss Drops panels
    "after_run_wait_sec": 12,
    # dungeons
    "walk_room_px": [41, 48],          # minimap zoom used while walking (room size in pixels)
    "scan_room_px": 13,                # zoom used to look at the whole map
    "face_doors": True,                # doors only open while you look at them
    "dungeon_sprint": True,
    # dungeons: ride the mount (moves like running, only faster - Blayne). F5 has a box. (The
    # circles on 10-19 15:32 came from a wall next to your room read as a door, not the mount.)
    "ride_mount": True,
    # world boss at the top of every hour (Map 4 Sins Kingdom), after the :00 dungeon; back to
    # Map 5 Dragon City afterwards. F5 has a box
    "world_boss": False,
    "mount_off_below": 0.5,             # moving slower than this share of mount speed = off it
    # try a few values of the navigation settings, a few dungeons each, keep the fastest
    # (autotune.py; F5 box)
    "learn_dungeons": False,
    # leaving a room: walk to its middle, stop, turn to the door, straight through (Blayne 10-22)
    "middle_then_turn": True,
    "spawn_shortcut": True,             # press Spawn when walking from the blue room is quicker
    "spawn_shortcut_rooms": 3.0,        # what pressing Spawn costs, in rooms of walking
    # while the new minimap is being sorted out: a small picture every 2 s during dungeons (the
    # game view + the minimap + what the farm is doing), sent to the PC with the log
    "dungeon_trace": True,
    # the new minimap's arrow shows where the CAMERA looks (laptop traces 10-19 17:00: every
    # mouse turn moved it by the same angle, and it stayed put while walking around a room), so
    # the camera direction is read straight off it instead of being guessed from walking
    "arrow_is_camera": True,
    "mount_key": "m",
    "sprint_key": "lctrl",
    "trial_sprint": False,             # trials: False = turn sprint off (dungeons always sprint)
    "cam_px_per_rad": 584,             # mouse movement per radian of camera turn (learned)
    "walk_rooms_per_sec": 0.27,        # learned
    "dungeon_stuck_spawn_sec": 40,
    "dungeon_room_timeout_sec": 60,
    "dungeon_leave_for_trial_sec": 120,   # Trial popup + no new room cleared this long = leave for the trial
    # NVIDIA Instant Replay clips when something goes wrong, and getting back in after a disconnect
    "clips": True, "clip_min_gap_sec": 120, "clip_hotkey_vk": [0x12, 0x79],   # Alt+F10
    "auto_reconnect": True, "reconnect_per_hour": 6,
    "sweep_after_sec": 6, "sweep_step_sec": 2.5, "sweep_dist": 0.22,
    # trials
    "trial_walk_in_sec": 2.0,          # W held into each room at most (learned)
    "trial_walk_extra_sec": 0.3,       # ...keeps walking this long past the first hit (learned)
    "trial_far_sec": 3.5,              # how far in the step-in goes (seconds of W from the door)
    "trial_spawn_wait_sec": 2.5,       # longest wait for Spawn to move you
    "trial_dps_settle_sec": 2.0,       # longest extra wait for the DPS meter to drop to 0 after a room
    "trial_respawn_sec": 10,           # walked all the way in, nothing hit this long: Spawn again
    "trial_give_up_sec": 180,
    "defense_leave_after": 10,
    "defense_not_before_popup_sec": 300,   # Defense: don't start one this close to a dungeon / trial         # Defense mode: leave after this wave, then start it again          # this long retrying one room without a hit: leave the trial
    "trial_step_ms": 300,              # one step further in = W held this long
    "trial_max_steps": 8,
    "trial_side_ms": 750,              # sideways move between zigzag lanes (~0.2 of a room)
    "trial_step_wait_sec": 1.2,        # wait after a step for the DPS meter to react
    "trial_step_wait_blind_sec": 4,    # ...if the DPS meter can't be read (waits for kills instead)
    "trial_empty_room_sec": 5, "trial_room_walk_sec": 3.0,
    # logging
    "log_enabled": True, "log_shot_minutes": 5, "log_keep_hours": 24,
}


# defaults that changed after settings.json was written: a saved value still equal to the old
# default (never changed by hand) takes the new one
CHANGED_DEFAULTS = {
    "trial_respawn_sec": (20, 10),
    "idle_click_sec": (45, 0),         # 10-17: idle clicks in the lobby opened a boss's Drops panel     # 10-16: stood 20 s doing nothing at the far end of a room
}


def load_settings():
    s = dict(DEFAULTS)
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                s.update(json.load(f))
            for k, (old, new) in CHANGED_DEFAULTS.items():
                if s.get(k) == old:
                    s[k] = new
            if not s.get("reset_1022"):
                # 10-22: dungeons back to how they ran on 10-20 evening (Blayne: "what we had two
                # days ago was good"): drop what the learning changed and switch it off
                for k in ("stop_lead_sec", "lineup_start", "turn_tol", "turn_retol", "mount_lineup_taps",
                          "spawn_shortcut_rooms", "turn_settle_sec", "autotune"):
                    s.pop(k, None)
                s["learn_dungeons"] = False
                s["reset_1022"] = True
            return s
        except (OSError, ValueError):
            # unreadable: keep a copy instead of silently overwriting what was learned
            try:
                os.replace(SETTINGS_FILE, SETTINGS_FILE + f".bad-{int(time.time())}")
            except OSError:
                pass
    # first run: take over what the AutoHotkey version learned
    if os.path.exists(AHK_INI):
        try:
            import configparser
            cp = configparser.ConfigParser()
            for enc in ("utf-16", "utf-8"):
                try:
                    cp.read(AHK_INI, encoding=enc)
                    break
                except Exception:
                    continue
            m = cp["main"] if cp.has_section("main") else {}
            if "mode" in m:
                s["mode"] = m["mode"]
            if "trials" in m:
                s["join_trials"] = m["trials"] == "1"
            if "trialleave" in m:
                s["trial_leave_after"] = int(m["trialleave"])
            if "campxperrad" in m and 60 <= abs(float(m["campxperrad"])) <= 4000:
                s["cam_px_per_rad"] = float(m["campxperrad"])
            if "roomwalksec" in m and float(m["roomwalksec"]) > 0:
                s["walk_rooms_per_sec"] = round(1 / float(m["roomwalksec"]), 3)
                s["trial_room_walk_sec"] = float(m["roomwalksec"])
        except Exception:
            pass
    save_settings(s)
    return s


_save_lock = threading.Lock()


def save_settings(s):
    with _save_lock:
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
        os.replace(tmp, SETTINGS_FILE)


class Logger:
    def __init__(self, settings):
        self.S = settings
        self.dir = os.path.expandvars(r"%USERPROFILE%\Pictures\Screenshots\anime-legacy-log")
        try:
            os.makedirs(self.dir, exist_ok=True)
        except Exception:
            self.dir = os.path.join(HERE, "log")
            os.makedirs(self.dir, exist_ok=True)
        self.file = os.path.join(self.dir, "log-py.txt")
        self.last_shot = 0.0
        self.lock = threading.Lock()

    def line(self, msg):
        if not self.S.get("log_enabled", True):
            return
        stamp = dt.datetime.now().strftime("%m-%d %H:%M:%S")
        with self.lock:
            try:
                if os.path.exists(self.file) and os.path.getsize(self.file) > 2_000_000:
                    os.replace(self.file, self.file.replace(".txt", "-old.txt"))
                with open(self.file, "a", encoding="utf-8") as f:
                    f.write(f"{stamp}  {msg}\n")
            except Exception:
                pass

    def shot(self, frame, tag, force=False):
        if not self.S.get("log_enabled", True) or frame is None:
            return
        now = time.monotonic()
        if not force and now - self.last_shot < 15:
            return
        self.last_shot = now
        safe = "".join(c if c.isalnum() else "-" for c in tag)[:28].strip("-")
        path = os.path.join(self.dir, f"{dt.datetime.now():%m%d-%H%M%S}-py-{safe}.jpg")
        try:
            cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            self.line(f"screenshot: {path}")
        except Exception:
            pass

    def cleanup(self):
        hours = self.S.get("log_keep_hours", 24)
        if not hours:
            return
        cut = time.time() - hours * 3600
        n = 0
        for name in os.listdir(self.dir):
            if name.endswith(".jpg"):
                p = os.path.join(self.dir, name)
                try:
                    if os.path.getmtime(p) < cut:
                        os.remove(p)
                        n += 1
                except Exception:
                    pass
        if n:
            self.line(f"cleanup: deleted {n} screenshot(s) older than {hours}h")


class Game:
    """Everything the farm needs from the game: frames, readers, input. Thread: the farm worker."""

    def __init__(self, settings, ui_status, stop_flag):
        self.settings = settings
        self.S = settings
        self.ui_status = ui_status         # callable(dict) to update the overlay
        self.stop_flag = stop_flag          # callable() -> True when the user stopped the farm
        self.logger = Logger(settings)
        self.cap = winio.Capture(log=self.log)
        self.tpl = hud.Templates()
        self.reader = mm.MapReader()
        self.hwnd = None
        self.rect = None
        self.held = set()
        self._sprint_on = settings.get("last_sprint_on")            # sprint: True/False once a dungeon has checked, None = unknown
        # on the mount: True/False once a dungeon has checked, None = unknown. The game keeps you
        # on it (also through teleports) until M is pressed again
        self._mount_on = settings.get("last_mount_on")
        self.zoom_hover = None
        self.info = {}
        self.last_rect_check = 0.0
        self._last_status = ""

    # ---------------- window / frames ----------------
    def window(self):
        now = time.monotonic()
        if self.hwnd is None or now - self.last_rect_check > 1.0:
            self.last_rect_check = now
            h = winio.find_roblox()
            self.hwnd = h
            self.rect = winio.client_rect(h) if h else None
        return self.hwnd

    def active(self):
        h = self.window()
        return bool(h) and winio.is_foreground(h)

    def frame(self):
        """The whole client area (BGR) or None."""
        if not self.window() or not self.rect:
            return None
        f = self.cap.grab(self.rect)
        if f is not None:
            self.last_frame = f        # for the live status page (read by another thread)
        return f

    def grab(self, x, y, w, h):
        """Part of the client area (client pixels)."""
        if not self.window() or not self.rect:
            return None
        X, Y, W, H = self.rect
        x, y = max(0, x), max(0, y)
        w, h = min(w, W - x), min(h, H - y)
        if w <= 0 or h <= 0:
            return None
        return self.cap.grab((X + x, Y + y, w, h))

    def size(self):
        return (self.rect[2], self.rect[3]) if self.rect else (1920, 1080)

    def to_screen(self, x, y):
        X, Y, _, _ = self.rect
        return X + x, Y + y

    # ---------------- env interface ----------------
    def now(self):
        return time.monotonic()

    def sleep(self, s):
        end = time.monotonic() + s
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(left, 0.05))

    def running(self):
        if self.stop_flag():
            return False
        if not self.active():
            self.release_all()
            return False
        return True

    def map_crop(self, r):
        W, H = self.size()
        sx, sy = W / 1920, H / 1080
        cx, cy, R = round(mm.MAP_CX * sx), round(mm.MAP_CY * sy), round(r * sy)
        return self.grab(cx - R, cy - R, 2 * R + 1, 2 * R + 1)

    def view(self):
        img = self.map_crop(mm.MAP_R)
        if img is None:
            return None
        v = self.reader.parse(img)
        if v is not None:
            self.info["map"] = f"rooms {len(v.cells)} · size {v.s}px · you {v.offx:+.0f},{v.offy:+.0f}"
        return v

    def arrow(self):
        img = self.map_crop(20)
        return None if img is None else mm.read_arrow(img)

    def dps(self):
        """The DPS meter (top left): True = something is being hit, False = 'DPS: 0', None = can't read."""
        f = self.frame()
        return hud.dps_hitting(f) if f is not None else None

    def enemies(self):
        f = self.frame()
        if f is None:
            return None
        en = hud.read_counter(f, "enemies")
        self.info["enemies"] = en.text if en else "?"
        return en

    def wave(self, f=None):
        f = self.frame() if f is None else f
        return None if f is None else hud.read_counter(f, "wave")

    def find(self, name, f=None, **kw):
        f = self.frame() if f is None else f
        if f is None:
            return None
        return self.tpl.find(f, name, **kw)

    def in_dungeon(self):
        """The castle icon of the ROOM counter (only in dungeons and trials)."""
        return self.find("roomhud") is not None

    def has_minimap(self):
        f = self.frame()
        return f is not None and hud.has_minimap(f)

    def covered(self):
        """A black full-screen animation (trait roll) is hiding the HUD right now."""
        f = self.frame()
        return f is not None and hud.covered(f)

    def popup(self):
        """The Dungeon / Trial popup (green check + pink X) on screen now, or None."""
        f = self.frame()
        return hud.find_popup(f) if f is not None else None

    def housekeeping(self):
        """Closes the Roblox 'Join Event' popup and any menu. True if it did something."""
        f = self.frame()
        if f is None:
            return False
        if self.close_join_event(f):
            return True
        if self.close_drops(f):
            return True
        c = self.tpl.find(f, "close")
        if c:
            self.release_all()
            self.close_menu(*c)
            return True
        return False

    def set_keys(self, keys):
        keys = {k for k in keys if k in "wasd"}
        if not self.active():
            keys = set()
        for k in sorted(self.held - keys):
            winio.key(k, False)
        for k in sorted(keys - self.held):
            winio.key(k, True)
        self.held = keys

    def release_all(self):
        for k in list(self.held):
            winio.key(k, False)
        self.held = set()

    def tap(self, key, ms=50):
        if self.active():
            winio.tap(key, ms)

    def cam_drag(self, px, slow=False):
        if not self.active() or not self.rect:
            return
        W, H = self.size()
        self.zoom_hover = None
        winio.move_to(*self.to_screen(W // 2, round(H * 0.45)))
        time.sleep(0.04)
        winio.right_drag(px, slow=slow)

    def zoom(self, d):
        if not self.active():
            return
        W, H = self.size()
        bx = mm.MAP_MINUS_X if d < 0 else mm.MAP_PLUS_X
        x, y = self.to_screen(round(bx * W / 1920), round(mm.MAP_BUTTONS_Y * H / 1080))
        if self.zoom_hover != (x, y):
            winio.move_to(x - 25, y + 25)
            winio.glide_to(x, y)
            winio.wiggle()
            time.sleep(0.04)
            self.zoom_hover = (x, y)
        else:
            winio.mouse_rel(1, 0)            # a tiny move: Roblox ignores clicks on a still mouse
            time.sleep(0.02)
            winio.mouse_rel(-1, 0)
            time.sleep(0.02)
        winio.mouse_button("left", True)
        time.sleep(0.045)
        winio.mouse_button("left", False)
        self.reader.reset()
        time.sleep(0.03)

    def press_spawn(self, wait=1.0):
        c = self.find("spawn")
        if not c:
            return False
        self.spawn_xy = c                 # the button doesn't move: remembered for spawn_spot()
        self.release_all()
        self.click(*c)
        self.sleep(wait)
        return True

    def spawn_spot(self):
        """Clicks where the Spawn button was last seen, for when the picture of it doesn't match
        (laptop trials, 10-15). trial.py checks afterwards that you were really moved.
        Returns False if it has never been seen."""
        c = getattr(self, "spawn_xy", None)
        if not c:
            return False
        self.release_all()
        self.click(*c)
        return True

    def spawn_why(self):
        """Why the Spawn picture wasn't found, for the log: how well the best spot matched."""
        f = self.frame()
        if f is None:
            return "no picture from the screen"
        frac, c = self.tpl.match(f, "spawn")
        return f"best match {frac:.0%} at {c} (needs 97%), screen {f.shape[1]}x{f.shape[0]}"

    def wait_moved(self, before, most=2.5, least=0.2):
        """After Spawn: waits until the middle of the screen has changed from `before` (you were
        moved) and then holds still for a moment. Returns the seconds it took, or None if it saw
        no change within `most` seconds (it has waited that long then)."""
        t0 = self.now()
        ref = hud.view_sig(before) if before is not None else None
        prev, moved = None, False
        while self.now() - t0 < most:
            f = self.frame()
            if f is not None and ref is not None:
                s = hud.view_sig(f)
                if not moved:
                    moved = hud.view_diff(s, ref) > hud.VIEW_MOVED
                elif prev is not None and hud.view_diff(s, prev) < hud.VIEW_STILL and self.now() - t0 >= least:
                    return self.now() - t0
                prev = s
            self.sleep(0.04)
        return None

    def set_sprint(self, on):
        """(Old: turned sprint on/off by keeping count of taps. Sprint is a toggle that stays on,
        and a tap the game missed made the count wrong for the rest of the run, so the farm no
        longer turns it off; dungeons check the walking speed and call toggle_sprint.)"""
        return

    def toggle_sprint(self, why=""):
        """Taps the sprint key (a toggle in the game). Only while Roblox is in front and moving."""
        if not self.active():
            return False
        winio.tap(self.S.get("sprint_key", "lctrl"), 60)
        if self.sprint_on is not None:
            self.sprint_on = not self.sprint_on
        self.log(f"sprint key pressed{' · ' + why if why else ''}")
        time.sleep(0.12)
        return True

    # mount / sprint state: remembered in settings.json, because the game keeps them through a
    # restart of the macro (a trial right after a restart ran on the mount, laptop 10-21 22:15)
    @property
    def mount_on(self):
        return self._mount_on

    @mount_on.setter
    def mount_on(self, v):
        if v != self._mount_on:
            self._mount_on = v
            self.save_setting("last_mount_on", v, quiet=True)

    @property
    def sprint_on(self):
        return self._sprint_on

    @sprint_on.setter
    def sprint_on(self, v):
        if v != self._sprint_on:
            self._sprint_on = v
            self.save_setting("last_sprint_on", v, quiet=True)

    def toggle_mount(self, why=""):
        """Taps the mount key (gets on / off the mount). Only while Roblox is in front."""
        if not self.active():
            return False
        try:
            winio.tap(self.S.get("mount_key", "m"), 60)
        except KeyError:
            self.log(f"mount key {self.S.get('mount_key')!r} isn't a key the farm can press · not using the mount")
            return False
        if self.mount_on is not None:
            self.mount_on = not self.mount_on
        self.log(f"mount key pressed{' · ' + why if why else ''}")
        time.sleep(0.15)
        return True

    def status(self, msg):
        self._last_status = msg
        self.info["doing"] = msg
        self.ui_status(self.info)

    def log(self, msg):
        self.logger.line(msg)

    def clip(self, why):
        """Saves an NVIDIA Instant Replay clip of the last few minutes (the Alt+F10 shortcut;
        Instant Replay has to be on in NVIDIA App). At most one every clip_min_gap_sec. Then logs
        where the file landed, or that none showed up."""
        S = self.S
        now = time.monotonic()
        if not S.get("clips", True) or now - getattr(self, "_last_clip", -1e9) < float(S.get("clip_min_gap_sec", 120)):
            return False
        if getattr(getattr(self, "cap", None), "_stale", False):
            return False          # monitor off: NVIDIA only records the last picture before it went off
        if getattr(self, "_clip_misses", 0) >= 2:
            return False          # two saves in a row made no file: no Instant Replay on this PC
        self._last_clip = now
        winio.vk_combo([int(v) for v in S.get("clip_hotkey_vk", [0x12, 0x79])])   # Alt+F10
        self.log(f"saving an Instant Replay clip ({why})")
        threading.Thread(target=self._clip_file, args=(time.time(),), daemon=True).start()
        return True

    def _clip_file(self, t0):
        roots = winio.videos_folders() or [os.path.expandvars(r"%USERPROFILE%\Videos")]
        for _ in range(20):
            time.sleep(2)
            new = []
            for root in roots:
                try:
                    new += [p for p in glob.glob(os.path.join(root, "*", "*.mp4")) if os.path.getmtime(p) >= t0 - 1]
                except OSError:
                    pass
            if new:
                self._clip_misses = 0
                self.log(f"clip saved: {max(new, key=os.path.getmtime)}")
                return
        self._clip_misses = getattr(self, "_clip_misses", 0) + 1
        if self._clip_misses >= 2:
            self.log("no clip showed up twice in a row · no more clips until the farm is restarted"
                     " (they need NVIDIA Instant Replay on, save = Alt+F10)")
        else:
            self.log("no clip showed up in Videos within 40 s · is Instant Replay on in NVIDIA App? (save = Alt+F10)")

    def shot(self, tag, force=False):
        self.logger.shot(self.frame(), tag, force)

    def trace(self, text):
        """Small debugging picture: game view (640x360) + minimap (2x) + the farm's state."""
        if not self.S.get("dungeon_trace", True) or not self.S.get("log_enabled", True):
            return
        f = self.frame()
        if f is None:
            return
        try:
            view = cv2.resize(f, (640, 360), interpolation=cv2.INTER_AREA)
            mm_img = cv2.resize(hud.minimap_crop(f), (360, 360), interpolation=cv2.INTER_NEAREST)
            pic = np.hstack([view, mm_img])
            pic = cv2.copyMakeBorder(pic, 0, 44, 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0))
            for i, line in enumerate(str(text).split("\n")[:2]):
                cv2.putText(pic, line[:120], (6, 378 + 20 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                            (255, 255, 255), 1, cv2.LINE_AA)
            path = os.path.join(self.logger.dir, f"{dt.datetime.now():%m%d-%H%M%S}-py-trace.jpg")
            cv2.imwrite(path, pic, [cv2.IMWRITE_JPEG_QUALITY, 70])
        except Exception:
            pass

    def save_setting(self, key, value, quiet=False):
        if self.S.get(key) != value:
            self.S[key] = value
            if not quiet or not hasattr(self, "_last_quiet_save") or time.monotonic() - self._last_quiet_save > 30:
                self._last_quiet_save = time.monotonic()
                save_settings(self.S)

    # ---------------- clicking ----------------
    def park(self):
        W, H = self.size()
        return self.to_screen(round(W * 0.92), round(H * 0.62))

    def park_mouse(self):
        """Mouse off the minimap buttons (hovering changes how they look)."""
        if self.rect and self.active():
            winio.move_to(*self.park())
        self.zoom_hover = None

    def click(self, x, y, park=True, slow=False):
        """Client coordinates."""
        if not self.active():
            return
        self.zoom_hover = None
        sx, sy = self.to_screen(x, y)
        winio.click_screen(sx, sy, park=self.park() if park else None, slow=slow)

    def hover(self, x, y):
        """Puts the mouse over (x, y) so Roblox 'feels' it (menus only scroll after that)."""
        if not self.active():
            return
        winio.glide_to(*self.to_screen(x, y))
        time.sleep(0.08)
        winio.wiggle()

    def scroll(self, notches):
        if self.active():
            winio.wiggle()
            winio.wheel(notches)

    def close_menu(self, x, y):
        """Clicks a menu's X and makes sure it closed (retries if Roblox ignored the click; the
        retries hover slowly first, which Roblox sometimes needs before it takes a click)."""
        for i in range(4):
            self.click(x, y, slow=i > 0)
            self.sleep(0.6)
            c = self.find("close")
            if not c:
                self.status("closed a menu")
                return True
            x, y = c
        return False

    def close_drops(self, f=None):
        """Closes a boss's "Drops" panel (pink X top right of it). The game hides the minimap and
        counters while it's open, so the farm couldn't tell it was in a dungeon (laptop 10-17:
        the 03:00 and 04:00 dungeons and the 12:15 trial were joined but never played)."""
        c = self.find("dropsx", f, min_frac=0.9)
        if not c:
            return False
        self.release_all()
        now = time.monotonic()
        if now - getattr(self, "_drops_logged", -1e9) > 60:
            self._drops_logged = now
            self.log("closed a boss 'Drops' panel (it hides the game's map and counters)")
            self.shot("drops-panel", force=True)
        self.click(*c)
        self.status("closed the Drops panel")
        self.sleep(0.4)
        return True

    def close_join_event(self, f=None):
        c = self.find("joinevent", f)
        if not c:
            return False
        self.release_all()
        w, _ = self.tpl.size("joinevent")
        self.click(c[0] - w // 2 - 107, c[1])
        self.status("closed the Join Event popup")
        self.sleep(0.4)
        return True
