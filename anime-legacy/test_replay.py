"""Smoke test: the real Game class, fed saved screenshots instead of the screen, with every
input replaced by a no-op. Catches crashes in code paths the simulator doesn't use."""
import glob
import os
import time

import cv2

import game as G
from culling import Culling
from dungeon import DungeonRun
from trial import run_trial

# a kept copy of the log screenshots (the farm deletes its own screenshots after 24 h)
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "testdata", "screens")
if not os.path.isdir(LOG_DIR):
    LOG_DIR = os.path.expandvars(r"%USERPROFILE%\Pictures\Screenshots\anime-legacy-log")


class ReplayGame(G.Game):
    def __init__(self, images, seconds):
        S = dict(G.DEFAULTS)
        super().__init__(S, lambda info: None, lambda: time.monotonic() > self.deadline)
        self.images = images
        self.i = 0
        self.deadline = time.monotonic() + seconds
        self.calls = {}
        self.rect = (0, 0, 1920, 1080)
        self.hwnd = 1
        self.logger.line = lambda msg: self.lines.append(msg)
        self.logger.shot = lambda *a, **k: None
        self.lines = []

    def _count(self, k):
        self.calls[k] = self.calls.get(k, 0) + 1

    def window(self):
        return 1

    def active(self):
        return True

    def frame(self):
        self._count("frame")
        img = self.images[self.i % len(self.images)]
        self.i += 1
        return img

    def grab(self, x, y, w, h):
        img = self.images[self.i % len(self.images)]
        return img[y:y + h, x:x + w]

    def set_keys(self, keys):
        self._count("keys")
        self.held = set(keys)

    def release_all(self):
        self.held = set()

    def tap(self, key, ms=50):
        self._count("tap")

    def cam_drag(self, px):
        self._count("drag")

    def zoom(self, d):
        self._count("zoom")

    def click(self, x, y, park=True):
        self._count("click")

    def hover(self, x, y):
        pass

    def scroll(self, n):
        self._count("scroll")

    def park_mouse(self):
        pass

    def set_sprint(self, on):
        self.sprint_on = on

    def clip(self, why):
        self._count("clip")
        return True

    def save_setting(self, key, value, quiet=False):
        self.S[key] = value          # never touch the real settings.json from a test


def load(pattern, n=12):
    files = sorted(glob.glob(os.path.join(LOG_DIR, pattern)))[:n]
    return [cv2.imread(f) for f in files]


if __name__ == "__main__":
    dungeon_imgs = load("*stuck*") + load("*learning-which*")
    assert dungeon_imgs, f"no dungeon screenshots in {LOG_DIR}"
    g = ReplayGame(dungeon_imgs, 8)
    run = DungeonRun(g)
    run.run()
    print("dungeon run on screenshots: ok ·", g.calls, "·", len(g.lines), "log lines; last:", g.lines[-3:])
    trial_imgs = load("*Joining-the-trial*", 3) + load("*rial-started*") + load("*Trial-wave*")
    assert trial_imgs, f"no trial screenshots in {LOG_DIR}"
    g = ReplayGame(trial_imgs, 6)
    print("trial run:", run_trial(g, "dungeon", 21), g.calls, g.lines[-2:])
    lobby = load("1014-104458*") + load("*Joining-the-trial*", 2)
    assert lobby, f"no lobby screenshots in {LOG_DIR}"
    g = ReplayGame(lobby, 3)
    c = Culling(g)
    for _ in range(5):
        c.tick(g.frame())
    c.waiting_room(g.frame())
    print("culling ticks: ok", g.calls, g.lines[-3:])
