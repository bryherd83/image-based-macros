"""Culling Game loop (port of the AHK Tick + OpenCulling) and the idle helpers."""
from __future__ import annotations

import datetime as dt
import random

import hud

# When the popups show up: Dungeons on the hour and half hour, Trials 15 minutes later, plus a
# few seconds. Each PC's clock is off by its own amount (the gaming PC's ran 1:44 fast: popups at
# :01:40 by its clock, the laptop's at :00:02), so the seconds past the quarter hour are learned
# from the real joins (setting popup_offset_sec). Used to tell you what's next, and to watch for
# a popup that never came; the farm still waits for the actual popup.
POPUP_TIMES = {"dungeon": (0, 30), "trial": (15, 45)}
DEFAULT_OFFSET = 100          # the gaming PC's clock, Oct 13-15


def popup_offset(when):
    """Seconds past the quarter hour of a popup seen at `when`, or None if too far from one."""
    sec = (when.minute % 15) * 60 + when.second
    return sec if sec < 300 else None


def next_popup(kinds, now=None, offset=DEFAULT_OFFSET):
    """(kind, time) of the next Dungeon / Trial popup going by the usual times."""
    now = now or dt.datetime.now()
    best = None
    for kind in kinds:
        for m in POPUP_TIMES[kind]:
            t = now.replace(minute=m, second=0, microsecond=0) + dt.timedelta(seconds=offset)
            while t > now + dt.timedelta(hours=1):
                t -= dt.timedelta(hours=1)
            while t <= now:
                t += dt.timedelta(hours=1)
            if best is None or t < best[1]:
                best = (kind, t)
    return best


class Culling:
    def __init__(self, env):
        self.env = env
        self.last_start = 0.0
        self.last_in_run = 0.0
        self.last_open_try = 0.0
        self.last_leave = 0.0
        self.last_nav = 0.0
        self.last_afk = env.now()
        self.last_idle = env.now()

    # ---- keep the game from kicking you for being idle ----
    def anti_afk(self):
        e = self.env
        mins = float(e.settings.get("anti_afk_minutes", 10))
        if mins > 0 and e.now() - self.last_afk > mins * 60:
            e.tap("space")
            self.last_afk = e.now()

    def idle_click(self, f):
        e = self.env
        sec = float(e.settings.get("idle_click_sec", 45))
        if sec <= 0 or e.now() - self.last_idle < sec:
            return
        self.last_idle = e.now()
        if e.find("worlds", f) is None:        # a menu is open: don't click into it
            return
        W, H = e.size()
        e.click(round(W * random.uniform(0.42, 0.58)), round(H * random.uniform(0.22, 0.32)))
        e.status("clicked to stay active")

    def waiting_room(self, f):
        """Dungeon mode, between dungeons (and trials)."""
        e = self.env
        c = e.find("close", f)
        if c:
            e.close_menu(*c)
            return
        kind, t = next_popup(("dungeon", "trial") if e.settings.get("join_trials") else ("dungeon",),
                             offset=float(e.settings.get("popup_offset_sec", DEFAULT_OFFSET)))
        left = max(0, int((t - dt.datetime.now()).total_seconds()))
        e.status(f"waiting · next: {kind} popup at {t:%H:%M:%S} (in {left // 60}:{left % 60:02d})")
        self.anti_afk()
        self.idle_click(f)

    # ---- one step of the Culling Game loop ----
    def tick(self, f):
        e = self.env
        S = e.settings
        now = e.now()
        just_started = self.last_start and now - self.last_start < 45
        in_run = e.find("leave", f) is not None or e.find("spawn", f) is not None
        if in_run:
            self.last_in_run = now
            c = e.find("close", f)
            if c:                              # no menu should be open during a run
                e.release_all()
                e.close_menu(*c)
                return
            if e.find("worlds", f) is None:
                e.status("waiting: a menu seems to be open")
                return
            leave_at = int(S.get("leave_at_wave", 9))
            if leave_at > 0 and now - self.last_leave > 6:
                wv = hud.read_counter(f, "wave")
                e.info["wave"] = wv.text if wv else "?"
                hit = (wv is not None and wv.a >= leave_at) or \
                      (wv is None and e.find("wave9", f, min_frac=1.0) is not None)
                if hit:
                    c = e.find("leave", f)
                    if c:
                        e.release_all()
                        e.click(*c)
                        self.last_leave = now
                        self.last_start = 0
                        e.status(f"wave {leave_at} reached · leaving")
                        e.log(f"Culling Game: wave {leave_at} reached · leaving")
                        return
            skill = S.get("skill_key", "")
            if skill and now - getattr(e, "_last_skill", 0) > 1.0:
                e.tap(skill)
                e._last_skill = now
            e.status("Culling Game run")
            self.anti_afk()
            return
        # ---- menus we opened ourselves
        navigating = self.last_nav and now - self.last_nav < 15
        if not just_started and navigating:
            for name, msg in (("play", "pressed Play"), ("create", "pressed Create"), ("dice", "opened Culling Game")):
                c = e.find(name, f)
                if c:
                    e.click(*c)
                    if name == "play":
                        self.last_start, self.last_nav = now, 0
                    else:
                        self.last_nav = now
                    e.status(msg)
                    e.log(msg)
                    return
        c = e.find("close", f)
        if c:                                   # any other menu: close it
            e.release_all()
            e.close_menu(*c)
            return
        if just_started:
            return
        if self.last_in_run and now - self.last_in_run < float(S.get("after_run_wait_sec", 12)):
            return
        self.anti_afk()
        self.idle_click(f)
        if now - self.last_open_try < 8:
            return
        self.last_open_try = now
        self.open_culling(f)

    def open_culling(self, f):
        e = self.env
        w = e.find("worlds", f)
        if w is None:
            e.status("can't see the Worlds button")
            return
        opened = False
        for how in ("key", "click"):
            if how == "key":
                e.tap(e.settings.get("worlds_key", "t"), 80)
            else:
                e.click(*w)
            self.last_nav = e.now()
            for _ in range(6):
                e.sleep(0.4)
                if e.find("close") is not None:
                    opened = True
                    break
            if opened:
                break
        if not opened:                          # don't scroll with no menu (it would zoom the camera)
            e.status("Worlds menu didn't open · retrying")
            return
        W, H = e.size()
        # Roblox only scrolls a menu after it has 'felt' the mouse on it
        e.click(W // 2, round(H * 0.215), park=False)
        e.hover(W // 2, round(H * 0.45))
        for notch in (-1, 1):                   # down first, then up
            for _ in range(25):
                fr = e.frame()
                d = e.find("dice", fr)
                if d:
                    e.click(*d)
                    self.last_nav = e.now()
                    e.status("opened Culling Game")
                    e.log("opened Culling Game")
                    return
                if e.find("close", fr) is None:   # menu closed somehow: stop scrolling
                    return
                e.scroll(notch)
                e.sleep(0.3)
        e.status("couldn't find Cursed Academy's dice · retrying")
        c = e.find("close")
        if c:
            e.close_menu(*c)
