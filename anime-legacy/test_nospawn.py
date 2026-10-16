"""Trial where the Spawn button can't be found while stuck in a room (laptop 10-15: it logged
"nothing hit ... pressing Spawn" every second for 2.5 minutes and stood still). Now it must
search the room on foot (further in, then the side lanes), try Spawn at most every 20 s,
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
        if gaps and min(gaps) < 19.5:
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
