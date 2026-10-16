"""Trial where the Spawn button can't be found while stuck in a room (laptop 10-15: it logged
"nothing hit ... pressing Spawn" every second for 2.5 minutes and stood still). Now it must
search the room on foot (further in, then the side lanes), try Spawn at most every trial_respawn_sec,
and still reach the leave wave (every retry here has no Spawn button: the worst case).

    python test_nospawn.py
"""
import re
import test_trial as t

t.trial_new.hud = t.FAKE_HUD


class NoSpawnSim(t.TrialSim):
    """The Spawn button is missing whenever you'd press it to retry a room (not after a clear)."""
    def press_spawn(self, wait=1.0):
        if not self.cleared and self.t > 3:
            self.sleep(wait)
            self.missing = getattr(self, "missing", 0) + 1
            return False
        return super().press_spawn(wait)


def run(scene, seed):
    sim = NoSpawnSim(scene, seed, limit=25 * 60)
    t.trial_new.run_trial(sim, "dungeon", sim.leave_after)
    return sim


ok = True
for scene in ["near the side walls", "spread over the room"]:
    sims = [run(scene, s) for s in range(6)]
    for s in sims:
        presses = [tm for tm, m in s.lines if "pressing Spawn" in m]
        gaps = [b - a for a, b in zip(presses, presses[1:])]
        if gaps and min(gaps) < float(s.settings['trial_respawn_sec']) - 0.5:
            ok = False
            print(f"  seed: Spawn pressed again after {min(gaps):.1f}s")
        once = sum(1 for _, m in s.lines if "can't see the Spawn button" in m)
        assert once <= 1, "the 'can't see Spawn' line should be logged once per trial"
    longest = max(max(s.clear_times) for s in sims)
    print(f"{scene:22s} {sum(s.left for s in sims)}/6 reached wave 22 · longest room {longest:.0f}s"
          f" · Spawn button missing {sum(getattr(s, 'missing', 0) for s in sims) // 3}x")
    ok = ok and all(s.left for s in sims)
assert ok, "stalled or pressed Spawn too often"
print("no-spawn: ok")


class MismatchSim(t.TrialSim):
    """Laptop 10-15: the Spawn picture matches at the start of the trial, then stops matching
    although the button is still there. Clicking where it was seen works."""
    def press_spawn(self, wait=1.0):
        if getattr(self, "spawn_xy", None):
            self.sleep(wait)
            return False
        self.spawn_xy = (1080, 122)
        return super().press_spawn(wait)

    def spawn_spot(self):
        if not getattr(self, "spawn_xy", None):
            return False
        t.TrialSim.press_spawn(self, 0)
        self.spots = getattr(self, "spots", 0) + 1
        return True

    def spawn_why(self):
        return "best match 80%"


before = [t.run(t.trial_new, "deep (like your 19:47 trial)", s) for s in range(6)]
after = []
for s in range(6):
    sim = MismatchSim("deep (like your 19:47 trial)", s)
    t.trial_new.run_trial(sim, "dungeon", sim.leave_after)
    after.append(sim)
    assert sim.left, "didn't reach the leave wave"
    assert sum("didn't match" in m for _, m in sim.lines) == 1, "the mismatch line should be logged once"
    assert not any("can't see the Spawn" in m for _, m in sim.lines)
mean = lambda sims: sum(x for s in sims for x in s.clear_times) / sum(len(s.clear_times) for s in sims)
print(f"Spawn picture stops matching: 6/6 reached wave 22 · {mean(after):.1f} s/room"
      f" (normal {mean(before):.1f}) · clicked the usual spot {sum(s.spots for s in after)}x")
assert mean(after) < mean(before) * 1.3, "clicking the usual spot should be about as fast as normal"
print("spawn mismatch: ok")


class UnreachableSim(t.TrialSim):
    """Laptop 10-16 09:18: in wave 21 one enemy can't be reached from anywhere (12 minutes of
    Spawn retries). It must leave the trial after trial_give_up_sec, not stay forever."""
    def _room(self):
        super()._room()
        if self.wave == 5:
            self.en[0][:2] = [5.0, 5.0]       # far outside the room


sim = UnreachableSim("deep (like your 19:47 trial)", 1, limit=25 * 60)
res = t.trial_new.run_trial(sim, "dungeon", sim.leave_after)
gave = [(tm, m) for tm, m in sim.lines if "leaving the trial" in m]
print("unreachable enemy:", res, gave[:1], f"at {sim.t:.0f}s")
assert res == "gave up" and gave and sim.wave == 5
assert 180 < gave[0][0] - min(tm for tm, m in sim.lines if "pressing Spawn" in m) < 200
print("give up: ok")
