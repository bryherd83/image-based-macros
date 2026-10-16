"""Trial with a flickering enemy/wave counter (unreadable half the time, e.g. bright effects
behind it): it must not stand still. Before the fix it stalled ("nothing in reach · 172s").

    python test_flicker.py
"""
import random, statistics as st, sys
import test_trial as t
t.trial_new.hud = t.FAKE_HUD

def flicker_run(scene, seed, p=0.5, reach=None):
    rng = random.Random(seed + 77)
    kw = {} if reach is None else {"reach": reach}
    sim = t.TrialSim(scene, seed, limit=12 * 60, **kw)
    real = sim.counter
    sim.counter = lambda which: None if rng.random() < p else real(which)
    t.trial_new.run_trial(sim, "dungeon", sim.leave_after)
    return sim

for scene in ["deep (like your 19:47 trial)"]:
    for p in (0.0, 0.5):
        r = [flicker_run(scene, s, p) for s in range(4)]
        longest = max((max(s.clear_times) if s.clear_times else s.t) for s in r)
        print(f"{scene:32s} counter unreadable {p:.0%}: {sum(s.left for s in r)}/4 reached wave 22,"
              f" waves {[s.wave for s in r]}, longest room {longest:.0f}s")
        assert all(s.left for s in r), "trial stalled"
print("flicker: ok")
