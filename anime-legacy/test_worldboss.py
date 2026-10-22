"""World boss (worldboss.py): the 'World Boss' bar is read on Blayne's screenshots, the trip waits
for the :00 dungeon, and the whole trip (teleport, walk, fight, back) runs on a fake game.
    python test_worldboss.py
"""
import datetime as dt
import glob
import os
import sys

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import worldboss as wbm  # noqa: E402

S = os.path.join(HERE, "testdata", "screens")
# 1. the bar: only the fight screenshot has it (58 has a different, small 'Boss' bar)
for name, want in (("pc-1021-worldboss-bar.png", True), ("pc-1021-worldboss-nearby.png", False),
                   ("pc-1021-worldboss-otherboss.png", False), ("pc-1021-worldboss-landing.png", False)):
    got = wbm.boss_bar(cv2.imread(os.path.join(S, name)))
    assert got == want, (name, got)
bad = [p for p in glob.glob(os.path.join(S, "*")) if "worldboss" not in p
       and (lambda f: f is not None and f.shape[1] == 1920 and wbm.boss_bar(f))(cv2.imread(p))]
assert not bad, bad[:3]
print("1: bar read right, no false bars in", len(glob.glob(os.path.join(S, "*"))), "pictures")


class Fake:
    def __init__(self):
        self.settings = {"world_boss": True, "popup_offset_sec": 0}
        self.t = 0.0
        self.where, self.lines, self.keys = "dragon", [], set()
        self.fight_until = None

    def now(self): return self.t
    def sleep(self, s): self.t += s
    def running(self): return True
    def release_all(self): self.keys = set()
    def set_keys(self, k): self.keys = set(k)
    def popup(self): return None
    def log(self, m): self.lines.append(m)
    def status(self, m): pass
    def shot(self, *a, **k): pass
    def frame(self):
        if self.where == "sins" and self.keys and self.t > self.walk_from + 4:
            self.near = True
        if self.where == "sins" and getattr(self, "near", False):
            return "bar" if self.t < self.fight_until else "nobar"
        return "nobar"
    def dps(self):
        return self.where == "dragon" and self.keys == {"w"} and self.t > self.walk_from + 3

    def find(self, name, f=None, **k):
        return (78, 619) if name == "worlds" else None


class FakeCulling:
    def __init__(self, g): self.g = g
    def open_card(self, f, card, what, where, click_below=0):
        self.g.where = {"sinskingdom": "sins", "dragoncity": "dragon"}[card]
        self.g.walk_from, self.g.near = self.g.t, False
        self.g.fight_until = self.g.t + 120
        return True
    def anti_afk(self): pass


wbm.boss_bar = lambda f: f == "bar"
real = wbm.dt.datetime


def at(minute):
    class C(real):
        @classmethod
        def now(cls, tz=None):
            return real(2026, 10, 21, 7, minute, 0)
    wbm.dt.datetime = C


g = Fake(); b = wbm.WorldBoss(g, FakeCulling(g))
at(1); assert not b.due(), "went before the :00 dungeon"
b.dungeon_finished(); assert b.due()
at(14); b.done_hour = None; assert not b.due(), "went too late"
at(6); g.t = 100
assert b.tick("x") and g.where == "dragon", (g.where, g.lines)
assert any("hitting Goku Black" in m for m in g.lines), g.lines
assert any("at the boss" in m for m in g.lines) and any("over" in m for m in g.lines), g.lines
assert not b.tick("x"), "went twice in one hour"
g.settings["world_boss"] = False; b.done_hour = None; g.t += 100
assert not b.tick("x"), "went with the setting off"
wbm.dt.datetime = real
print("2: trip:", " | ".join(m for m in g.lines))
# 3. the F5 test walk: teleports, walks, stays on Map 4
g = Fake(); b = wbm.WorldBoss(g, FakeCulling(g))
res = b.test_walk()
assert g.where == "sins" and "health bar showed" in res, (g.where, res)
print("3: test walk ->", res)
print("world boss: ok")
