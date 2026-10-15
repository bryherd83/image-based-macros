"""Gets back into Anime Legacy after a disconnect or a Roblox crash.

Two signals; it only acts on one of them, so a normal teleport (lobby -> dungeon -> trial)
never counts:
- Roblox's own log (%LOCALAPPDATA%\\Roblox\\logs, newest *_Player_*.log) shows "Disconnected
  from server" with no "Joining game" after it for 30 s (a teleport rejoins within about a
  second), and the farm hasn't seen the game's buttons for a minute;
- or there's been no Roblox window at all for a minute (crashed or closed).
Then: a 30 s warning (F6 stops the farm), an Instant Replay clip, close Roblox, open it
straight into the game (roblox://experiences/start?placeId=...), wait for the window.
At most once every 3 minutes and 6 times an hour; after that it waits and says so.
"""
from __future__ import annotations

import datetime as dt
import glob
import os
import re

ANIME_LEGACY_PLACE = "106198175232796"      # from "Joining game ... place ..." in Roblox's log
LOG_DIR = os.path.expandvars(r"%LOCALAPPDATA%\Roblox\logs")
_TS = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)Z")
_JOIN = re.compile(r"! Joining game '[^']*' place (\d+)")
_DISC = re.compile(r"Disconnected from server for reason: (.*)$")


def _utc(line):
    m = _TS.match(line)
    if not m:
        return None
    return dt.datetime.fromisoformat(m.group(1)).replace(tzinfo=dt.timezone.utc).timestamp()


class RobloxLog:
    """Follows the newest Roblox player log: when you last joined a game, and when (and why)
    the connection to the server last dropped. Times are Unix seconds."""

    def __init__(self, folder=LOG_DIR):
        self.folder = folder
        self.path, self.pos = None, 0
        self.last_join = self.last_disc = None
        self.reason = ""
        self.place = None

    def newest(self):
        logs = [p for p in glob.glob(os.path.join(self.folder, "*_Player_*.log")) if "CrashHandler" not in p]
        return max(logs, key=os.path.getmtime) if logs else None

    def update(self):
        p = self.newest()
        if p is None:
            return
        if p != self.path:                       # a new Roblox session: read it from the start
            self.path, self.pos = p, 0
            self.last_join = self.last_disc = None
        try:
            with open(p, "rb") as f:
                f.seek(self.pos)
                data = f.read()
                self.pos = f.tell()
        except OSError:
            return
        for line in data.decode("utf-8", "replace").splitlines():
            m = _JOIN.search(line)
            if m:
                self.last_join, self.place = _utc(line) or self.last_join, m.group(1)
                continue
            m = _DISC.search(line)
            if m:
                self.last_disc, self.reason = _utc(line) or self.last_disc, m.group(1).strip()

    def disconnected_for(self, now):
        """Seconds since the connection dropped with no rejoin after it, or 0."""
        if self.last_disc is None or (self.last_join is not None and self.last_join >= self.last_disc):
            return 0.0
        return max(0.0, now - self.last_disc)


class Watchdog:
    """Called by the farm about once a second. `env` needs: log, status, toast, clip (optional),
    running(), roblox_window() -> hwnd or None, close_roblox(hwnd), open_game(url), activate(hwnd),
    sleep."""

    def __init__(self, env, settings, log=None):
        self.env, self.S = env, settings
        self.log = log or RobloxLog()
        self.no_window_since = None
        self.warn_since = None
        self.why = ""
        self.attempts = []                      # times it reconnected (for the hourly limit)

    def check(self, now, wall, game_seen_ago):
        """now = monotonic seconds, wall = Unix time, game_seen_ago = seconds since the farm
        last saw the game's buttons. Returns True while it's busy reconnecting/warning."""
        S = self.S
        if not S.get("auto_reconnect", True):
            return False
        hwnd = self.env.roblox_window()
        self.no_window_since = None if hwnd else (self.no_window_since or now)
        self.log.update()
        why = ""
        if not hwnd and now - self.no_window_since >= float(S.get("reconnect_no_window_sec", 60)):
            why = "Roblox has been closed for a minute"
        else:
            off = self.log.disconnected_for(wall)
            # the farm can't see the game (a disconnect box covers it) for a minute, or Roblox's
            # log has said "disconnected" for 2 minutes with no rejoin, whatever the screen shows
            if hwnd and ((off >= 30 and game_seen_ago >= float(S.get("reconnect_no_game_sec", 60))) or off >= 120):
                why = f"disconnected from the game ({self.log.reason or 'no reason given'})"
        if not why:
            if self.warn_since is not None:
                self.env.log("reconnect not needed after all")
            self.warn_since = None
            return False
        self.attempts = [t for t in self.attempts if now - t < 3600]
        if self.attempts and now - self.attempts[-1] < 180:
            return True                         # just tried: give it time to load
        if len(self.attempts) >= int(S.get("reconnect_per_hour", 6)):
            self.env.status(f"{why} · tried {len(self.attempts)} times this hour · waiting")
            return True
        if self.warn_since is None:
            self.warn_since, self.why = now, why
            self.env.toast(f"{why}.\nReopening Anime Legacy in 30 s. Press F6 to stop.")   # (also logged)
            clip = getattr(self.env, "clip", None)
            if clip:
                clip("disconnected")
            return True
        left = 30 - (now - self.warn_since)
        if left > 0:
            self.env.status(f"{why} · reopening the game in {left:.0f}s (F6 stops)")
            return True
        self.reconnect(hwnd, now)
        return True

    def reconnect(self, hwnd, now):
        place = self.log.place or ANIME_LEGACY_PLACE
        self.attempts.append(now)
        self.warn_since = None
        self.env.log(f"reconnecting: closing Roblox and opening Anime Legacy (place {place})")
        self.env.close_roblox(hwnd)
        self.env.sleep(5)
        if not self.env.running():
            return False
        self.env.open_game(f"roblox://experiences/start?placeId={place}")
        for _ in range(90):                     # up to 3 minutes for the window
            self.env.sleep(2)
            if not self.env.running():
                return False
            h = self.env.roblox_window()
            if h:
                self.env.sleep(5)
                self.env.activate(h)
                self.env.log("Roblox is back · waiting for the game to load")
                return True
        self.env.log("Roblox didn't open within 3 minutes · will try again")
        return False
