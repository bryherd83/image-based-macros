"""Builds dist/anime-legacy-hueco.zip: a copy of the macro for guild mates that farms Hueco Mundo
and nothing else (no Dungeons, Trials or world boss, and it sends no logs anywhere).
    python make_hueco_zip.py
"""
import json
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
CODE = ("farm.py", "game.py", "hud.py", "hueco.py", "minimap.py", "dungeon.py", "culling.py", "trial.py",
        "worldboss.py", "reconnect.py", "logsend.py", "winio.py", "run.bat")
SETTINGS = {"hueco_only": True, "mode": "hueco", "join_trials": False, "hueco_leave_for_popups": False,
            "world_boss": False, "log_send": False, "hueco_leave_after": 10}
README = """Anime Legacy - Hueco Mundo macro
================================

Farms Hueco Mundo runs over and over, and leaves after the wave you set (10 to start with).
It does nothing else: no Dungeons, Trials or world boss.

Setup
1. Install Python 3.11 or newer from python.org. Tick "Add python.exe to PATH".
2. Unzip this folder somewhere, for example your Documents.
3. Run Roblox fullscreen at 1920x1080, standing in the lobby.
4. Get on your mount. The macro never presses M.
5. Double-click run.bat. The first time it installs what it needs (takes a minute).
6. Click into Roblox and press F6.

Keys
F5  settings (which wave to leave after)
F6  start / stop
F8  quit

It opens Hueco Mundo from Soul Society's purple key (Teleport menu, Create, Play), walks to the
skulls on the minimap, votes on cards (never Sealed Spots, which hides the skulls) and leaves after
your wave. Screenshots and a log are kept in Pictures/Screenshots/anime-legacy-log for 24 hours.
"""


def build(out=os.path.join(HERE, "dist", "anime-legacy-hueco.zip")):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in CODE:
            z.write(os.path.join(HERE, f), "anime-legacy-hueco/" + f)
        for f in sorted(os.listdir(os.path.join(HERE, "assets"))):
            z.write(os.path.join(HERE, "assets", f), "anime-legacy-hueco/assets/" + f)
        z.writestr("anime-legacy-hueco/settings.json", json.dumps(SETTINGS, indent=2))
        z.writestr("anime-legacy-hueco/README.txt", README.replace("\n", "\r\n"))
    return out


if __name__ == "__main__":
    print(build())
