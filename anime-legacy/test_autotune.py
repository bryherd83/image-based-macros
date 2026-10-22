"""Learning from every dungeon (autotune.py): values are tried in turn, the fastest kept, a value
that gets stuck more doesn't win, unfinished dungeons don't count, settings end at the kept value.
    python test_autotune.py
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import autotune as at  # noqa: E402

S = {}
lines = []
t = at.AutoTune(S, lambda: None, lines.append)
# fake game: turn_tol 0.11 is fastest; stop_lead 0.2 is fastest but gets stuck a lot
speed = {("turn_tol", 0.06): 2.4, ("turn_tol", 0.08): 2.2, ("turn_tol", 0.11): 1.9,
         ("stop_lead_sec", 0.06): 2.0, ("stop_lead_sec", 0.12): 2.0, ("stop_lead_sec", 0.2): 1.7}
stuck = {("stop_lead_sec", 0.2): 5}
for i in range(9 + 9):
    t.before()
    name, val = t.trying
    assert S[name] == val
    sec = speed.get((name, val), 2.0) * 40
    t.after({"walking": sec * 0.6, "turning": sec * 0.4, "fighting": 999}, 40, stuck.get((name, val), 0))
    assert S[name] == t.st["best"].get(name, dict((k[0], k[2]) for k in at.KNOBS)[name])
assert S["turn_tol"] == 0.11, S
assert S["stop_lead_sec"] == 0.12, S                # 0.2 was faster but got stuck far more
print([m for m in lines if "decided" in m])
# a dungeon that wasn't finished doesn't count; an interrupted test is put back
t.before(); n, v = t.trying
before = dict(t.st["results"])
t.after({}, 0, 0)
assert t.st["results"] == before
t.before(); t.before()
assert t.trying and S[t.trying[0]] == t.trying[1]
print("autotune: ok")
