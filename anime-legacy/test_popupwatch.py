"""A popup that never comes leaves screenshots + one log line; a joined one leaves nothing. python test_popupwatch.py"""
import sys, datetime as dt; sys.path.insert(0, r"C:\Users\bryhe\Downloads\anime-legacy-farmpy")
import farm, time
class G:
    def __init__(s): s.shots, s.logs = [], []
    def shot(s, tag, force=False): s.shots.append((now[0], tag))
    def log(s, m): s.logs.append(m)
now = [None]
class FakeDT(dt.datetime):
    @classmethod
    def now(cls): return now[0]
farm.dt.datetime = FakeDT
mono = [0.0]; farm.time.monotonic = lambda: mono[0]
w = farm.Worker.__new__(farm.Worker) if hasattr(farm, "Worker") else None
cls = [c for c in vars(farm).values() if isinstance(c, type) and hasattr(c, "popup_watch")][0]
w = cls.__new__(cls); w.S = {"join_trials": True, "popup_offset_sec": 2}
w.last_join, w.popup_shot, w.popup_missed = None, 0.0, None
g = G()
start = FakeDT(2026, 10, 15, 22, 59, 50)
for i in range(0, 200):           # 23:00:02 dungeon never joined
    now[0] = start + dt.timedelta(seconds=i); mono[0] = 1000 + i
    w.popup_watch(g, "dungeon")
print(len(g.shots), [t.strftime("%H:%M:%S") for t, _ in g.shots]); print(g.logs)
assert len(g.logs) == 1 and 4 <= len(g.shots) <= 5
# joined at 23:30:03: nothing
g2 = G(); w.last_join = FakeDT(2026, 10, 15, 23, 30, 3); w.popup_shot = 0
for i in range(0, 150):
    now[0] = FakeDT(2026, 10, 15, 23, 29, 50) + dt.timedelta(seconds=i); mono[0] = 5000 + i
    w.popup_watch(g2, "dungeon")
print(g2.shots, g2.logs); assert not g2.shots and not g2.logs
print("popup watch: ok")
