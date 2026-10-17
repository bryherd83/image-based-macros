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
