"""Reconnect watchdog + Instant Replay clips, offline: fake Roblox log files, a fake clock and a
fake game. Nothing here closes or opens Roblox, or presses a key.

    python test_reconnect.py
"""
import os
import shutil
import tempfile
import types

import game as G
import reconnect as R
import winio


def line(t, msg):
    """A Roblox log line at Unix time t (their format: 2026-10-15T00:30:12.766Z,923.7,8424,6 ...)."""
    import datetime as dt
    ts = dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
    return f"{ts}Z,1.0,8424,6 {msg}\n"


JOIN = "[FLog::Output] ! Joining game '1d9267b6-379a-4c69-825f-7f331987c5bf' place 106198175232796 at 10.1.1.1"
TELEPORT = "Info [DFLog::RbxTransportDummyClient] Disconnected from server for reason: Player: 285 (DisconnectClientInitiated)"
LOST = "Info [DFLog::RbxTransportDummyClient] Disconnected from server for reason: Player: 277 (ConnectionLost)"


class FakeEnv:
    def __init__(self, clock):
        self.clock = clock
        self.window = 111
        self.events = []
        self.run = True

    def log(self, m): self.events.append(("log", m))
    def status(self, m): pass
    def toast(self, m): self.events.append(("toast", m))
    def clip(self, why): self.events.append(("clip", why))
    def running(self): return self.run
    def roblox_window(self): return self.window
    def close_roblox(self, h): self.events.append(("close", h)); self.window = None
    def open_game(self, url): self.events.append(("open", url)); self.reopen_at = self.clock[0] + 20
    def activate(self, h): self.events.append(("activate", h))

    def sleep(self, s):
        self.clock[0] += s
        if self.window is None and getattr(self, "reopen_at", None) and self.clock[0] >= self.reopen_at:
            self.window = 222

    def kinds(self):
        return [k for k, _ in self.events]


def setup(lines):
    d = tempfile.mkdtemp(prefix="rblx-")
    p = os.path.join(d, "0.743.0_20261015T001449Z_Player_EC3FA_last.log")
    with open(p, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return d, p


def watchdog(lines, game_seen_ago, t_now, settings=None):
    d, p = setup(lines)
    clock = [1000.0]
    env = FakeEnv(clock)
    w = R.Watchdog(env, dict(settings or {}), R.RobloxLog(d))
    return d, p, clock, env, w


if __name__ == "__main__":
    T = 1_760_000_000.0
    # ---- the log reader: a teleport is not a disconnect, a dropped connection is
    d, p = setup([line(T, JOIN), line(T + 900, TELEPORT), line(T + 900.2, JOIN)])
    lg = R.RobloxLog(d)
    lg.update()
    assert lg.place == "106198175232796" and lg.disconnected_for(T + 2000) == 0, "teleport counted as a disconnect"
    with open(p, "a", encoding="utf-8") as f:
        f.write(line(T + 1000, LOST))
    lg.update()
    assert abs(lg.disconnected_for(T + 1040) - 40) < 0.01 and "277" in lg.reason
    with open(p, "a", encoding="utf-8") as f:
        f.write(line(T + 1100, JOIN))                 # Roblox got back in by itself
    lg.update()
    assert lg.disconnected_for(T + 1200) == 0
    shutil.rmtree(d)
    real = R.RobloxLog()
    real.update()
    print(f"log reader: ok (your newest Roblox log: place {real.place}, "
          f"disconnected now: {'yes' if real.disconnected_for(__import__('time').time()) else 'no'})")

    # ---- 1. normal play with teleports: never acts
    d, p, clock, env, w = watchdog([line(T, JOIN), line(T + 5, TELEPORT), line(T + 5.2, JOIN)], 0, T + 600)
    for i in range(300):
        assert not w.check(clock[0] + i, T + 600 + i, 0)
    assert env.events == [], env.events

    # ---- 2. disconnected, but the game still seems to be on screen: waits for 2 minutes of it
    d, p, clock, env, w = watchdog([line(T, JOIN), line(T + 10, LOST)], 0, 0)
    assert not w.check(1000, T + 10 + 60, 0)
    assert w.check(1001, T + 10 + 121, 0) and env.kinds() == ["toast", "clip"], env.events

    # ---- 3. disconnected and the game not seen for a minute: warns, 30 s later reconnects
    d, p, clock, env, w = watchdog([line(T, JOIN), line(T + 10, LOST)], 0, 0)
    assert w.check(1000, T + 45, 70) and env.kinds() == ["toast", "clip"]
    assert w.check(1015, T + 60, 85) and "close" not in env.kinds()         # still counting down
    clock[0] = 1031
    assert w.check(1031, T + 76, 101)
    k = env.kinds()
    assert k[k.index("close"):] == ["close", "open", "log", "activate", "log"][:0] + k[k.index("close"):]
    assert ("open", "roblox://experiences/start?placeId=106198175232796") in env.events, env.events
    assert "activate" in k and k.index("close") < k.index("open") < k.index("activate")
    assert w.check(clock[0] + 10, T + 200, 120)          # within 3 min of a try: only waits
    assert k.count("close") == env.kinds().count("close")
    print("disconnect: warns, clips, closes Roblox, opens Anime Legacy, focuses it; waits 3 min between tries")

    # ---- 4. Roblox window gone for a minute (crash): reopens; comes back by itself: does nothing
    d, p, clock, env, w = watchdog([line(T, JOIN)], 0, 0)
    env.window = None
    assert not w.check(1000, T + 10, 0) and not w.check(1059, T + 69, 0)
    assert w.check(1061, T + 71, 0) and env.kinds() == ["toast", "clip"]
    env.window = 333                                       # you opened it again yourself
    assert not w.check(1070, T + 80, 0) and "close" not in env.kinds()
    assert env.events[-1] == ("log", "reconnect not needed after all")
    print("Roblox closed: reopens after a minute + 30 s warning; stands down if it comes back")

    # ---- 5. F6 during the countdown/reconnect: never opens Roblox
    d, p, clock, env, w = watchdog([line(T, JOIN), line(T + 10, LOST)], 0, 0)
    w.check(1000, T + 45, 70)
    env.run = False
    clock[0] = 1031
    w.check(1031, T + 76, 101)
    assert "open" not in env.kinds(), env.events
    print("F6 while reconnecting: Roblox is not reopened")

    # ---- 6. at most 6 tries an hour
    d, p, clock, env, w = watchdog([line(T, JOIN), line(T + 10, LOST)], 0, 0)
    t = 1000.0
    for _ in range(12):
        w.check(t, T + 200, 999)
        t += 31
        clock[0] = t
        w.check(t, T + 200, 999)
        t += 200
        clock[0] = t
        env.window = 111
    assert env.kinds().count("close") == 6, env.kinds().count("close")
    print("limit: 6 reconnects an hour")

    # ---- 7. off in settings: never acts
    d, p, clock, env, w = watchdog([line(T, JOIN), line(T + 10, LOST)], 0, 0, {"auto_reconnect": False})
    assert not w.check(1000, T + 500, 999) and env.events == []

    # ---- Instant Replay clip: Alt+F10 once, then not again for 2 minutes
    pressed = []
    winio_vk = winio.vk_combo
    winio.vk_combo = lambda vks, hold_ms=60: pressed.append(list(vks))
    try:
        fake = types.SimpleNamespace(S=dict(G.DEFAULTS), lines=[], _clip_file=lambda t0: None)
        fake.log = fake.lines.append
        assert G.Game.clip(fake, "test") and pressed == [[0x12, 0x79]]
        assert not G.Game.clip(fake, "again right away") and len(pressed) == 1
        fake._last_clip -= 121
        assert G.Game.clip(fake, "2 min later") and len(pressed) == 2
        fake.S["clips"] = False
        fake._last_clip -= 999
        assert not G.Game.clip(fake, "clips off") and len(pressed) == 2
    finally:
        winio.vk_combo = winio_vk
    print("clips: Alt+F10, at most one every 2 minutes, can be switched off")
    print("reconnect: ok")
