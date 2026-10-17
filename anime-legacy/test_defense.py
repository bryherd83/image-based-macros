"""Defense in between dungeons and trials: from the lobby the farm opens the Worlds menu, scrolls
to Dragon City's key, presses Create and Play, then leaves Defense to the game. It doesn't start
Defense right before a popup, and backs off if Defense won't open. Fake game, nothing real.

    python test_defense.py
"""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import culling  # noqa: E402


class FakeGame:
    """Lobby -> Worlds menu (key card 6 scroll notches down) -> party screen -> Play -> Defense."""
    def __init__(self, card_at=6, key_works=True):
        self.t = 0.0
        self.state = "lobby"
        self.scroll_pos = 0
        self.card_at, self.key_works = card_at, key_works
        self.settings = {"join_trials": True, "popup_offset_sec": 2}
        self.info = {}
        self.lines, self.clicks = [], []

    # what's on screen
    def find(self, name, f=None, **kw):
        s = self.state
        if name == "worlds":
            return (78, 619) if s in ("lobby", "worlds") else None
        if name == "close":
            return (1700, 230) if s in ("worlds", "party") else None
        if name == "key":
            return (1300, 702) if s == "worlds" and abs(self.scroll_pos) == self.card_at else None
        if name == "create":
            return (960, 800) if s == "party" else None
        if name == "play":
            return (960, 900) if s == "started" else None
        return None

    def frame(self):
        return self

    def size(self):
        return 1920, 1080

    # actions
    def tap(self, key, ms=50):
        if key == "t" and self.state == "lobby":
            self.state = "worlds"
        self.t += ms / 1000

    def click(self, x, y, park=True):
        self.clicks.append((self.state, (x, y)))
        if self.state == "worlds" and (x, y) == (1300, 702) and self.key_works:
            self.state = "party"
        elif self.state == "party" and (x, y) == (960, 800):
            self.state = "started"
        elif self.state == "started" and (x, y) == (960, 900):
            self.state = "defense"
        elif (x, y) == (1700, 230):
            self.state = "lobby"

    def close_menu(self, x, y):
        self.click(x, y)

    def hover(self, x, y):
        pass

    def scroll(self, n):
        self.scroll_pos += 1 if n < 0 else -1

    def sleep(self, s):
        self.t += s

    def now(self):
        return self.t

    def release_all(self):
        pass

    def status(self, msg):
        self.last_status = msg

    def log(self, msg):
        self.lines.append(msg)

    def shot(self, *a, **k):
        self.lines.append("(screenshot)")


def run(game, clock, ticks=60):
    c = culling.Culling(game)
    real = culling.dt.datetime

    class Clock(real):
        @classmethod
        def now(cls, tz=None):
            return clock + dt.timedelta(seconds=game.t)
    culling.dt.datetime = Clock
    try:
        for _ in range(ticks):
            if game.state == "defense":
                break
            c.defense_tick(game)
            game.t += 0.5
    finally:
        culling.dt.datetime = real
    return c


# 1. 10 minutes before the next popup: it gets into Defense
g = FakeGame()
run(g, dt.datetime(2026, 10, 17, 17, 5, 0))
print("1:", g.state, g.lines)
assert g.state == "defense" and "opened Defense" in g.lines

# 2. 30 s before a popup: it waits instead of starting Defense
g = FakeGame()
run(g, dt.datetime(2026, 10, 17, 17, 14, 32), ticks=40)
print("2:", g.state, "clicks", len(g.clicks))
assert g.state == "lobby" and not g.clicks

# 3. the key never opens Defense: it backs off to once every 2 minutes and says so once
g = FakeGame(key_works=False)
c = run(g, dt.datetime(2026, 10, 17, 17, 1, 0), ticks=400)
tries = sum(1 for m in g.lines if m == "opened Defense")
print("3:", g.state, f"{tries} tries in {g.t:.0f}s", [m for m in g.lines if "couldn't" in m])
assert g.state != "defense" and tries <= 6 and sum("couldn't open it 4 times" in m for m in g.lines) == 1
print("defense: ok")

# 4. the real farm tick on the laptop's Defense screenshot (wave 12/50): reads the wave, presses
#    Leave when leaving at wave 10, keeps hands off when leaving at wave 20 or in another mode
import cv2  # noqa: E402
import time  # noqa: E402
import farm  # noqa: E402
import hud  # noqa: E402

shot = cv2.imread(os.path.join(HERE, "testdata", "screens", "laptop-1017-defense-run.png"))
print("4: wave read", hud.read_counter(shot, "wave", bx=hud.DEFENSE_WAVE_X))


class ShotGame:
    def __init__(self):
        self.tpl = hud.Templates()
        self.info, self.clicks, self.lines = {}, [], []
    def find(self, name, f=None, **kw): return self.tpl.find(shot if f is None else f, name, **kw)
    def frame(self): return shot
    def active(self): return True
    def now(self): return time.monotonic()
    def click(self, x, y, park=True): self.clicks.append((x, y))
    def release_all(self): pass
    def status(self, m): self.status_line = m
    def log(self, m): self.lines.append(m)
    def shot(self, *a, **k): pass
    def close_join_event(self, f=None): return False
    def close_drops(self, f=None): return False
    class cap: mode = "test"


def farm_tick(mode, leave_at):
    F = object.__new__(farm.Farm)
    F.S = {"mode": mode, "join_trials": True, "defense_leave_after": leave_at, "log_shot_minutes": 0}
    now = time.monotonic()
    F.last_watch = F.last_clean = F.last_seen_check = F.last_shot = now
    F.last_game_seen = now
    F.popup_watch = lambda g, m: None
    g = ShotGame()
    c = culling.Culling(g)
    sleep, farm.time.sleep = farm.time.sleep, lambda s: None
    try:
        F.tick(g, c)
    finally:
        farm.time.sleep = sleep
    return g


g = farm_tick("defense", 10)
print("   leave at 10:", g.clicks, g.lines)
assert g.clicks == [(840, 122)] and "wave 12 reached" in g.lines[0] and g.info["wave"] == "12/50"
g = farm_tick("defense", 20)
print("   leave at 20:", g.clicks, g.status_line)
assert not g.clicks and "wave 12/50" in g.status_line
g = farm_tick("dungeon", 10)                 # Defense started by hand in another mode: left alone
assert not g.clicks
print("defense leave: ok")

# 5. the "Dragon Defense" window stays open after Play (PC 10-17 17:12): closed with its X
end = cv2.imread(os.path.join(HERE, "testdata", "screens", "laptop-1017-defense-end.png"))


class EndGame(ShotGame):
    def __init__(self):
        super().__init__()
        self.settings = {"join_trials": True, "popup_offset_sec": 2}
        self.t = 100.0
    def find(self, name, f=None, **kw): return self.tpl.find(end, name, **kw)
    def now(self): return self.t
    def close_menu(self, x, y): self.clicks.append(("X", x, y))
    def hover(self, x, y): pass
    def tap(self, *a, **k): pass
    def sleep(self, s): self.t += s


real_dt = culling.dt.datetime


class Clock(real_dt):
    @classmethod
    def now(cls, tz=None):
        return real_dt(2026, 10, 17, 17, 5, 0)


culling.dt.datetime = Clock
try:
    g = EndGame(); c = culling.Culling(g)
    c.last_start = 98.0                    # Play pressed 2 s ago: give it time
    c.defense_tick(end)
    assert not g.clicks, g.clicks
    g.t = 103.0                            # 5 s after Play, still open: close it
    c.defense_tick(end)
    print("5: play stuck ->", g.clicks, g.lines)
    assert g.clicks == [("X", 1540, 252)] and "closing the windows left open" in g.lines[0]
    g = EndGame(); c = culling.Culling(g)  # just left Defense at wave 10, screen open: close it at once
    c.last_in_run = 99.0
    c.defense_tick(end)
    print("   after leaving ->", g.clicks)
    assert g.clicks == [("X", 1540, 252)]
finally:
    culling.dt.datetime = real_dt
print("defense screen: ok")

# 6. the Teleport (Worlds) menu left open behind the Dragon Defense window (PC 10-17 17:20):
#    no Play button on it, closed anyway 3 s after Play
end = cv2.imread(os.path.join(HERE, "testdata", "screens", "pc-1017-teleport-menu-after-defense.png"))
culling.dt.datetime = Clock
try:
    g = EndGame(); c = culling.Culling(g)
    c.last_start = 96.0
    c.defense_tick(end)
    print("6: teleport menu ->", g.clicks)
    assert g.clicks == [("X", 1540, 252)]
finally:
    culling.dt.datetime = real_dt
print("teleport menu: ok")
