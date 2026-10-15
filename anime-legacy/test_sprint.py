"""Sprint (a toggle that stays on) and the black trait-roll screen, offline.

    python test_sprint.py
"""
import glob
import os

import cv2

import hud
import sim

if __name__ == "__main__":
    # ---- sprint: off at the start -> the speed check turns it on; on -> never touched
    for seed in (1, 2, 3, 5):
        env, total, done = sim.run_one(seed=seed, sprint_on=False)
        assert env.sprint and done == total, (seed, env.sprint, done, total)
        assert 1 <= env.sprint_presses <= 2, env.sprint_presses
        on, t2, d2 = sim.run_one(seed=seed, sprint_on=True)
        assert on.sprint and on.sprint_presses == 0 and d2 == t2, (seed, on.sprint_presses)
        print(f"seed {seed}: sprint off at start -> turned on ({env.sprint_presses} press), "
              f"{env.t / 60:.1f} min; already on -> 0 presses, {on.t / 60:.1f} min")

    # ---- after a dungeon that sprinted, the dungeon reports sprint as on
    env, _, _ = sim.run_one(seed=7, sprint_on=False)
    assert getattr(env, "sprint_on", None) is True, "dungeon should report sprint on"

    # ---- trials: sprint known on -> walk a step and press it once (off); unknown -> untouched
    import test_trial as tt
    tt.trial_new.hud = tt.FAKE_HUD
    for known, presses in ((True, 1), (None, 0), (False, 0)):
        pressed = []
        orig = tt.TrialSim.__init__

        def init(self, *a, _k=known, **kw):
            orig(self, *a, **kw)
            self.sprint_on = _k
            self.toggle_sprint = lambda why="", s=self: (pressed.append((why, set(s.keys))), True)[1]
        tt.TrialSim.__init__ = init
        try:
            r = tt.run(tt.trial_new, "deep (like your 19:47 trial)", 0)
        finally:
            tt.TrialSim.__init__ = orig
        assert len(pressed) == presses and r.left, (known, pressed, r.left)
        if presses:
            assert pressed[0][1] == {"w"}, "sprint must be pressed while walking"
    print("trials: sprint turned off once when the dungeon saw it on (while walking); left alone if unknown")

    # ---- the black "MYTHICAL TRAIT" screen counts as covered; normal game screens don't
    here = os.path.dirname(os.path.abspath(__file__))
    trait = os.path.expandvars(r"%USERPROFILE%\Pictures\Screenshots\anime-legacy-log\1015-103510-py-dungeon-finished.jpg")
    if os.path.exists(trait):
        assert hud.covered(cv2.imread(trait)), "trait roll screen should count as covered"
        print("trait roll screen: covered")
    shots = sorted(glob.glob(os.path.join(here, "testdata", "screens", "*.jpg")))
    bad = [os.path.basename(p) for p in shots if hud.covered(cv2.imread(p))]
    print(f"normal screenshots counted as covered: {len(bad)} of {len(shots)} {bad[:8]}")
    assert len(bad) <= max(3, len(shots) // 100), bad
    print("sprint: ok")
