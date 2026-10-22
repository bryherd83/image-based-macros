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
            self.done_hour = self._game_now().strftime("%m%d%H")
            self.run()
            return True
        if self.need_home and e.popup() is None:
            self.last_try = e.now()
            if self.teleport("dragoncity", "Dragon City"):
                self.need_home = False
            return True
        return False

    # ---- pieces ----
    def teleport(self, card, name):
        """Worlds -> Teleport menu -> the card -> its Teleport button. True once the lobby is back."""
        e = self.env
        f = e.frame()
        ok = self.culling.open_card(f, card, name, name, click_below=392)
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
            e.log("world boss: couldn't teleport to Sins Kingdom · skipping this hour")
            e.shot("worldboss-no-teleport", force=True)
            return
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
        while e.running():
            if e.popup() is not None:           # a trial / dungeon: farm.tick joins it
                e.log("world boss: a popup came up · leaving the boss for it")
                return
            f = e.frame()
            now = e.now()
            if boss_bar(f):
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

    def go_home(self):
        if self.teleport("dragoncity", "Dragon City"):
            self.need_home = False
            self.env.log("world boss: back in Dragon City")

    def walk_to_boss(self):
        """From the landing spot: straight ahead, then ahead-right (the boss is off to the top
        right), until the bar shows; a few more steps in, then stop."""
        e = self.env
        S = e.settings
        plan = S.get("world_boss_walk", [["w", 6.0], ["wd", 6.0], ["w", 4.0]])
        t_trace = 0
        for keys, sec in plan:
            e.set_keys(set(keys))
            t0 = e.now()
            while e.now() - t0 < float(sec):
                if not e.running():
                    e.release_all()
                    return False
                f = e.frame()
                if boss_bar(f):
                    e.sleep(float(S.get("world_boss_extra_walk", 0.6)))
                    e.release_all()
                    return True
                if e.now() - t_trace > 2 and hasattr(e, "trace"):
                    t_trace = e.now()
                    e.trace(f"world boss: walking {keys} · {e.now() - t0:.0f}s")
                e.sleep(0.1)
        e.release_all()
        return boss_bar(e.frame())
