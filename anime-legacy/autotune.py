"""Learning from every dungeon (Blayne 10-21: "start learning from every dungeon and figure out
the way to make them as fast as possible").

One setting at a time is tried at a few values; each value gets a few dungeons; the one with the
lowest NAVIGATION seconds per room (walking + turning + lining up + stuck + looking at the map,
divided by the rooms the farm cleared - fighting time depends on your damage, and the dungeon
size and other players change the total) wins and is kept, then the next setting is tried.
Runs that got stuck more than the kept value's average don't count as better.
State lives in settings.json under "autotune"; every decision goes in the log.
"""
from __future__ import annotations

import statistics

# (setting, values to try, default). Bounded to what's been seen to work.
KNOBS = [
    ("turn_tol", [0.06, 0.08, 0.11], 0.08),
    ("stop_lead_sec", [0.06, 0.12, 0.2], 0.12),
    ("lineup_start", [0.05, 0.07, 0.1], 0.07),
    ("mount_lineup_taps", [True, False], True),
    ("spawn_shortcut_rooms", [2.0, 3.0, 4.5], 3.0),
    ("turn_settle_sec", [0.15, 0.25, 0.35], 0.25),
]
RUNS_EACH = 3
NAV = ("walking", "turning", "lining up", "stuck", "map")


def nav_per_room(time_in, rooms):
    if rooms < 15:
        return None
    return sum(time_in.get(k, 0.0) for k in NAV) / rooms


class AutoTune:
    def __init__(self, settings, save, log):
        self.S = settings
        self.save = save
        self.log = log
        st = self.S.setdefault("autotune", {})
        st.setdefault("knob", 0)
        st.setdefault("value", 0)
        st.setdefault("results", {})          # "knob=value" -> [[sec_per_room, stucks], ...]
        st.setdefault("best", {})             # knob -> chosen value
        self.st = st
        self.trying = None

    def enabled(self):
        return bool(self.S.get("learn_dungeons", True))

    def _key(self, name, val):
        return f"{name}={val}"

    def before(self):
        """Put the value under test in the settings for this dungeon."""
        if not self.enabled():
            return
        if self.trying:                         # the last one never finished: put it back
            n0 = self.trying[0]
            self.S[n0] = self.st["best"].get(n0, dict((k[0], k[2]) for k in KNOBS)[n0])
            self.trying = None
        name, vals, default = KNOBS[self.st["knob"] % len(KNOBS)]
        # (not self.S[name]: after a crash mid-test it holds the value under test)
        self.base = self.st["best"].get(name, default)
        val = vals[self.st["value"] % len(vals)]
        self.trying = (name, val)
        self.S[name] = val

    def after(self, time_in, rooms, stucks):
        """Record the finished dungeon; move on / decide. Leaves the settings at the kept values."""
        if not self.trying:
            return
        name, val = self.trying
        self.trying = None
        self.S[name] = self.st["best"].get(name, self.base)
        spr = nav_per_room(time_in, rooms)
        if spr is None:
            self.save()
            return
        k = self._key(name, val)
        self.st["results"].setdefault(k, []).append([round(spr, 3), stucks])
        self.log(f"learning: {name} = {val} · {spr:.2f}s of moving per room, {stucks} stucks "
                 f"(try {len(self.st['results'][k])} of {RUNS_EACH})")
        _, vals, default = KNOBS[self.st["knob"] % len(KNOBS)]
        if len(self.st["results"][k]) >= RUNS_EACH:
            self.st["value"] += 1
            if self.st["value"] >= len(vals):
                self._decide(name, vals, default)
                self.st["value"] = 0
                self.st["knob"] = (self.st["knob"] + 1) % len(KNOBS)
        self.save()

    def _decide(self, name, vals, default):
        rows = []
        for v in vals:
            r = self.st["results"].get(self._key(name, v), [])
            if r:
                rows.append((statistics.median(x[0] for x in r), sum(x[1] for x in r) / len(r), v))
        if not rows:
            return
        cur = self.st["best"].get(name, default)
        cur_row = next((r for r in rows if r[2] == cur), None)
        ok = [r for r in rows if cur_row is None or r[1] <= cur_row[1] + 1.0]
        win = min(ok or rows)
        # keep the current value unless the winner is clearly (3%+) faster
        if cur_row and win[0] > 0.97 * cur_row[0]:
            win = cur_row
        self.st["best"][name] = win[2]
        self.S[name] = win[2]
        table = ", ".join(f"{v}: {m:.2f}s" for m, _, v in sorted(rows, key=lambda r: r[2] if not isinstance(r[2], bool) else int(r[2])))
        self.log(f"learning: decided {name} = {win[2]} ({table} of moving per room)")
        for v in vals:                          # fresh numbers next round (the game changes)
            self.st["results"].pop(self._key(name, v), None)
