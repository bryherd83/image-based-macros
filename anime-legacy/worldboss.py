"""World boss (top of every hour, Map 4 Sins Kingdom, up for 15 minutes; Blayne 10-21).

After the :00 dungeon (or from wherever the farm idles), if the 'world_boss' setting is on:
Worlds -> Teleport -> Sins Kingdom, walk straight from the landing spot (the boss is ahead, off to
the right) until his "World Boss" health bar shows, stand there (the game attacks by itself) until
the bar has been gone for a while (defeated, or "has left Sins Kingdom"), then Teleport back to
Map 5 Dragon City and stand where you land.

The bar is found by its cyan "World Boss" lettering (assets/worldboss_mask.png, its shape), so
blue sky behind doesn't count.
"""
from __future__ import annotations

import datetime as dt
import os

import cv2
import numpy as np

import hud

HERE = os.path.dirname(os.path.abspath(__file__))
_MASK = None


def _cyan(img):
    t = img.astype(np.int16)
    return ((t[..., 0] > 190) & (t[..., 1] > 190) & (t[..., 2] < 140)).astype(np.float32)


def boss_bar(frame) -> bool:
    """The world boss's health bar ('World Boss' in cyan at the top centre) is on screen."""
    global _MASK
    if frame is None:
        return False
    if _MASK is None:
        m = cv2.imread(os.path.join(HERE, "assets", "worldboss_mask.png"), cv2.IMREAD_GRAYSCALE)
        if m is None:
            return False
        _MASK = (m > 127).astype(np.float32)
    H, W = frame.shape[:2]
    f = frame if (W, H) == (1920, 1080) else cv2.resize(frame, (1920, 1080))
    reg = _cyan(f[40:120, 760:1160])
    T = _MASK
    on = cv2.matchTemplate(reg, T, cv2.TM_CCORR)                      # template pixels lit
    tot = cv2.matchTemplate(reg, np.ones_like(T), cv2.TM_CCORR)      # all lit pixels
    hit = on / T.sum()
    extra = (tot - on) / (T.size - T.sum())
    return float((hit - 2 * extra).max()) >= 0.5


class WorldBoss:
    def __init__(self, env, culling):
        self.env = env
        self.culling = culling
        self.done_hour = None          # game hour already handled
        self.dungeon_done_hour = None  # game hour whose dungeon finished
        self.need_home = False         # back to Dragon City at the next chance
        self.last_try = -1e9

    def _game_now(self):
        off = float(self.env.settings.get("popup_offset_sec", 100))
        return dt.datetime.now() - dt.timedelta(seconds=off)

    def dungeon_finished(self):
        self.dungeon_done_hour = self._game_now().strftime("%m%d%H")
        # first try ~10 s later: right after a dungeon the game is still bringing you back and
        # the Worlds menu doesn't open (laptop 10-21 22:06 and 23:06, both 3 s after the end)
        self.last_try = self.env.now() - 10

    def due(self):
        S = self.env.settings
        if not S.get("world_boss", False):
            return False
        g = self._game_now()
        hour = g.strftime("%m%d%H")
        if self.done_hour == hour or g.minute >= 13:
            return False
        # the :00 dungeon first (it pops up at the same time): go once it's done, or once it
        # clearly isn't coming (3 minutes in)
        return self.dungeon_done_hour == hour or g.minute >= 3

    def tick(self, f):
        """Called when the farm is idle (not in a run). True if it did something."""
        e = self.env
        if e.now() - self.last_try < 20:
            return False
        if self.due():
            self.last_try = e.now()
            hour = self._game_now().strftime("%m%d%H")
            self.tries = self.tries if getattr(self, "tries_hour", None) == hour else 0
            self.tries_hour = hour
            self.tries += 1
            if self.run() is not False or self.tries >= 4:
                self.done_hour = hour
            return True
        if self.need_home and e.popup() is None:
            self.last_try = e.now()
            self.go_home()
            return True
        return False

    def _ok(self):
        """False only when the farm is stopped. Roblox not being the active window (e.g. you
        clicked another window) pauses here until it is again, instead of ending the walk at
        once (laptop 10-21 23:08: both walks ended after 0 s)."""
        e = self.env
        stop = getattr(e, "stop_flag", None)
        active = getattr(e, "active", None)
        if active is None:
            return e.running()
        waited = 0.0
        while not active():
            if stop and stop():
                return False
            if waited == 0.0:
                e.release_all()
                e.status("world boss: paused · click on the Roblox window to go on")
            e.sleep(0.5)
            waited += 0.5
            if waited > 120:
                return False
        return not (stop and stop())

    # ---- pieces ----
    def teleport(self, card, name):
        """Worlds -> Teleport menu -> the card -> its Teleport button. True once the lobby is back."""
        e = self.env
        ok = False
        for _ in range(2):                      # (the first Worlds press can be missed: PC 21:18)
            ok = self.culling.open_card(e.frame(), card, name, name, click_below=392)
            if ok:
                break
            e.sleep(1.0)
        if not ok:
            return False
        e.log(f"world boss: teleporting to {name}")
        for _ in range(30):                     # loading screen, then the HUD again
            e.sleep(0.5)
            fr = e.frame()
            if fr is not None and e.find("worlds", fr) and e.find("close", fr) is None:
                e.sleep(1.0)
                return True
        return False

    def run(self):
        e = self.env
        S = e.settings
        e.release_all()
        if not self.teleport("sinskingdom", "Sins Kingdom"):
            last = getattr(self, "tries", 1) >= 4
            e.log("world boss: couldn't teleport to Sins Kingdom · "
                  + ("skipping this hour" if last else "trying again in 20 s"))
            e.shot("worldboss-no-teleport", force=True)
            return False
        self.need_home = True
        if not self.walk_to_boss():
            e.log("world boss: didn't find him from the landing spot · going back")
            e.shot("worldboss-not-found", force=True)
            self.go_home()
            return
        e.log("world boss: at the boss · the game attacks by itself")
        e.shot("worldboss-fight", force=True)
        gone_since = None
        t0 = e.now()
        while self._ok():
            if e.popup() is not None:           # a trial / dungeon: farm.tick joins it
                e.log("world boss: a popup came up · leaving the boss for it")
                return
            f = e.frame()
            now = e.now()
            if boss_bar(f) or self._hitting_him(f):
                gone_since = None
                e.status(f"world boss: fighting · {(now - t0) / 60:.1f} min")
            else:
                gone_since = gone_since or now
                e.status("world boss: bar gone · waiting a moment")
                if now - gone_since > float(S.get("world_boss_gone_sec", 8)):
                    e.log(f"world boss: over (defeated or left) after {(now - t0) / 60:.1f} min")
                    break
            if self._game_now().minute >= 15 and now - t0 > 30:
                e.log("world boss: 15 minutes are up")
                break
            self.culling.anti_afk()
            e.sleep(0.5)
        self.go_home()

    def test_walk(self):
        """F5 test button: teleport to Sins Kingdom and do the walk, then stay there so you can
        see where it ended up (no boss needed: without one it walks the whole plan)."""
        e = self.env
        e.release_all()
        if not self.teleport("sinskingdom", "Sins Kingdom"):
            e.log("world boss test: couldn't teleport to Sins Kingdom")
            e.shot("worldboss-test-no-teleport", force=True)
            return "couldn't teleport to Sins Kingdom"
        t0 = e.now()
        found = self.walk_to_boss()
        msg = (f"world boss test: walked {e.now() - t0:.0f}s · "
               + ("the boss's health bar showed, stopped there" if found else
                  "no health bar (no boss up, or not reached) · this is where the walk ends"))
        e.log(msg)
        e.shot("worldboss-test-end", force=True)
        return msg.replace("world boss test: ", "")

    def go_home(self):
        if self.teleport("dragoncity", "Dragon City"):
            self.need_home = False
            self.env.log("world boss: back in Dragon City")
            self.walk_to_goku()

    def walk_to_goku(self):
        """Map 5: walk forward from the landing spot until you start hitting Goku Black (the DPS
        meter goes above 0), then stand there (Blayne 10-21)."""
        e = self.env
        S = e.settings
        most = float(S.get("home_walk_sec", 12))
        dps = getattr(e, "dps", None)
        e.set_keys({"w"})
        t0 = e.now()
        hit = False
        try:
            while self._ok() and e.now() - t0 < most:
                if dps and dps():
                    hit = True
                    break
                e.sleep(0.15)
        finally:
            e.release_all()
        e.log(f"world boss: walked {e.now() - t0:.1f}s on Map 5 · "
              + ("hitting Goku Black, standing here" if hit else "no hits on the DPS meter · stopped"))
        if not hit:
            e.shot("map5-no-hits", force=True)
        return hit

    def walk_to_boss(self):
        """From the landing spot: straight ahead, then ahead-right (the boss is off to the top
        right), until the bar shows; a few more steps in, then stop."""
        e = self.env
        S = e.settings
        # (PC 10-21 21:19 test: the whole 16 s walk ended against the house just past the
        # campfire where he spawns: the last leg is 1.5 s shorter now)
        plan = S.get("world_boss_walk", [["w", 6.0], ["wd", 6.0], ["w", 1.0]])
        # the plan was timed with sprint ON (test 21:19, "damn near perfect"): sprint goes on for
        # the walk (it's a toggle, pressed while moving) unless it's known to be on already, and
        # back off once there, so trials still start without it (Blayne 10-21)
        toggled = False
        tog = getattr(e, "toggle_sprint", None)
        if tog and getattr(e, "sprint_on", None) is not True:
            e.set_keys({"w"})
            e.sleep(0.15)
            toggled = bool(tog("world boss walk: sprint on"))
        try:
            return self._walk(plan)
        finally:
            if toggled:
                ok = False
                for _ in range(20):            # Roblox may not be the active window this moment
                    e.set_keys({"s"})          # (only switches while moving: a tiny step back)
                    e.sleep(0.12)
                    ok = bool(tog("world boss walk: sprint off again"))
                    e.release_all()
                    if ok:
                        break
                    e.sleep(0.5)
                if not ok:
                    e.log("world boss walk: couldn't switch sprint off again (Roblox wasn't the active window)")

    def _walk(self, plan):
        e = self.env
        S = e.settings
        t_trace = 0
        for keys, sec in plan:
            e.set_keys(set(keys))
            t0 = e.now()
            while e.now() - t0 < float(sec):
                if not self._ok():
                    e.release_all()
                    return False
                f = e.frame()
                # his own "World Boss" bar, or the small DPS number he gives (1-20-odd; the
                # normal boss two steps from the landing spot gives billions, PC 10-21 21:22).
                # The laptop walked past him at 23:10 while already hitting him for 7 DPS
                if boss_bar(f) or self._hitting_him(f):
                    e.sleep(float(S.get("world_boss_extra_walk", 0.6)))
                    e.release_all()
                    return True
                if e.now() - t_trace > 2 and hasattr(e, "trace"):
                    t_trace = e.now()
                    e.trace(f"world boss: walking {keys} · {e.now() - t0:.0f}s")
                e.sleep(0.1)
        e.release_all()
        # at the end of the walk (by the campfire where he stands): his bar can take a few
        # seconds to show up once you're there
        t0 = e.now()
        while self._ok() and e.now() - t0 < float(S.get("world_boss_bar_wait_sec", 15)):
            f = e.frame()
            if boss_bar(f) or self._hitting_him(f):
                return True
            e.sleep(0.3)
        return False

    @staticmethod
    def _hitting_him(f):
        try:
            return f is not None and not isinstance(f, str) and hud.dps_kind(f) == "small"
        except Exception:
            return False
