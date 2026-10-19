"""The mount (M): dungeons get on it, judged by walking speed (sim); a known mount isn't
probed again (the game keeps you on it through teleports); trials get off it.
    python test_mount.py
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sim  # noqa: E402
import dungeon  # noqa: E402
import trial  # noqa: E402


def run(seed, **kw):
    known = kw.pop("known", None)
    env = sim.SimEnv(seed=seed, mount=2.2, **kw)
    env.mount_on = known
    env.log = lambda m, *a, **k: None
    dungeon.DungeonRun(env).run()
    return env


for seed in (1, 2):
    e = run(seed)                                   # off, unknown: gets on
    assert e.mounted and e.mount_on is True and e.mount_presses == 1, (seed, e.mount_presses)
    e = run(seed, mounted=True)                     # on, unknown: off by the probe, on again
    assert e.mounted and e.mount_on is True and e.mount_presses == 2, (seed, e.mount_presses)
    e = run(seed, mounted=True, known=True)         # on and known: left alone
    assert e.mounted and e.mount_presses == 0, (seed, e.mount_presses)
    e = sim.SimEnv(seed=seed)                       # no mount in the sim: sprint as before
    e.log = lambda m, *a, **k: None
    dungeon.DungeonRun(e).run()
    assert e.mount_presses == 0


class TrialEnv:
    def __init__(self, on):
        self.mount_on, self.sprint_on, self.presses = on, None, []
    def toggle_mount(self, why=""):
        self.presses.append(why)
        if self.mount_on is not None:
            self.mount_on = not self.mount_on
        return True
    def sleep(self, s): pass
    def log(self, m): pass


for on, want in ((True, 1), (False, 0), (None, 0)):
    t = TrialEnv(on)
    trial.sprint_off_for_trial(t, {"dungeon_mount": True})
    assert len(t.presses) == want and (on is not True or t.mount_on is False), (on, t.presses)
print("mount: ok")
