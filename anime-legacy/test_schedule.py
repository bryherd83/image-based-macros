"""Dungeon + Trial on the same half hour: the Trial pops up 15 minutes after the Dungeon.
Runs the dungeon simulator with a Trial popup appearing part way through and checks the rule:
finish a dungeon that is still clearing rooms; leave for the trial only once it has gone
dungeon_leave_for_trial_sec (2 min) without a new room cleared. Also checks the "next popup"
clock. Nothing here touches the game.

    python test_schedule.py
"""
import datetime as dt
import statistics

import minimap as mm
import sim
from culling import next_popup
from dungeon import DungeonRun
from hud import Popup


def dungeon_with_trial(seed, popup_at, limit, **kw):
    env = sim.SimEnv(seed=seed, **kw)
    env.settings.update(join_trials=True, dungeon_leave_for_trial_sec=limit)
    clicks = []
    if popup_at is not None:
        env.popup = lambda: Popup("trial", 960, 800) if env.t >= popup_at else None
    env.click = lambda x, y, park=True: clicks.append(round(env.t, 1))
    run = DungeonRun(env)
    finished = run.run()
    total = sum(1 for c in env.rooms.values() if c in (mm.TODO, mm.TREASURE, mm.CLEARED))
    done = sum(1 for c in env.rooms.values() if c == mm.CLEARED)
    return finished, run, clicks, env, done, total


if __name__ == "__main__":
    # ---- the clock: what's next after a given time
    D = dt.datetime
    both = ("dungeon", "trial")
    assert next_popup(both, D(2026, 10, 14, 20, 5)) == ("trial", D(2026, 10, 14, 20, 16, 40))
    assert next_popup(both, D(2026, 10, 14, 20, 16, 40)) == ("dungeon", D(2026, 10, 14, 20, 31, 40))
    assert next_popup(both, D(2026, 10, 14, 20, 50)) == ("dungeon", D(2026, 10, 14, 21, 1, 40))
    assert next_popup(("dungeon",), D(2026, 10, 14, 20, 5)) == ("dungeon", D(2026, 10, 14, 20, 31, 40))
    assert next_popup(both, D(2026, 10, 14, 23, 50)) == ("dungeon", D(2026, 10, 15, 0, 1, 40))
    print("next popup clock: ok")

    seeds = range(101, 109)
    # ---- 1. no popup: the dungeon runs exactly as before
    for s in seeds[:3]:
        a = dungeon_with_trial(s, None, 120)
        env_b, total_b, done_b = sim.run_one(seed=s)
        assert a[0] and not a[2] and a[4] == done_b and abs(a[3].t - env_b.t) < 1e-6, f"seed {s} changed"
    print("no popup: same runs as before")

    # ---- 2. popup 4 min in, dungeon still clearing rooms: it finishes, never clicks
    rs = [dungeon_with_trial(s, 240, 120) for s in seeds]
    assert all(r[0] and not r[2] for r in rs), [(r[0], r[2]) for r in rs]
    gap = max(max(b - a for a, b in zip([0.0] + [t for t, _ in r[3].cleared_order],
                                         [t for t, _ in r[3].cleared_order])) for r in rs)
    print(f"popup while rooms keep getting cleared: {len(rs)}/{len(rs)} dungeons finished, no clicks "
          f"(longest gap between cleared rooms {gap:.0f}s, mean {statistics.mean(r[3].t for r in rs) / 60:.1f} min)")

    # ---- 3. stalled: same popup, but every gap counts as 'stuck' (limit 5 s): it leaves for the trial
    rs = [dungeon_with_trial(s, 240, 5) for s in seeds]
    assert all((not r[0]) and len(r[2]) == 1 and r[1].left_for == "trial" for r in rs), [(r[0], r[2]) for r in rs]
    assert all(240 <= r[2][0] <= 240 + 5 + 30 for r in rs), [r[2] for r in rs]
    lines = [m for _, m in rs[0][3].last_msgs if "trial" in m]
    print(f"popup + no new room for the limit: {len(rs)}/{len(rs)} left for the trial (clicked at "
          f"{min(r[2][0] for r in rs):.0f}-{max(r[2][0] for r in rs):.0f}s, popup at 240s)")
    print("   log:", lines)
    print("schedule: ok")
