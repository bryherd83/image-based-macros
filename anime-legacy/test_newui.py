"""The game's 10-19 UI update: lobby Worlds button, trial top panel (ENEMIES / WAVE counters,
castle icon, Leave, Spawn) and the DPS line in the player box, on the PC screenshots.
    python test_newui.py
"""
import os, sys
import cv2
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hud  # noqa: E402

T = hud.Templates()
S = os.path.join(HERE, "testdata", "screens", "pc-1019-new-ui-%s.png")
want = {
    # name: (enemies, wave, dps number wider than one digit, in a trial/dungeon)
    "lobby": (None, None, True, False),
    "dungeon-24": (None, None, True, False),     # lobby with the Trial popup
    "dungeon-25": ("1/4", "1/50", True, True),
    "dungeon-26": ("1/4", "2/50", True, True),
    "defense": ("7/7", "7/50", False, True),     # wider panel (HEALTH box), "0 DPS"
}
for name, (en, wv, hit, inrun) in want.items():
    f = cv2.imread(S % name)
    e, w = hud.read_counter(f, "enemies"), hud.read_counter(f, "wave")
    got = (e.text if e else None, w.text if w else None, hud.dps_hitting(f),
           all(T.find(f, k) for k in ("roomhud", "leave", "spawn")))
    print(name, got)
    assert got == (en, wv, hit, inrun), (name, got)
    assert T.find(f, "worlds"), name
f = cv2.imread(S % "dungeon-25")
assert T.find(f, "spawn") == hud.SPAWN_XY and not hud.spawn_hidden(f)
assert hud.find_popup(cv2.imread(S % "dungeon-24")).kind == "trial"
d = cv2.imread(S % "defense")
assert T.find(d, "defheart") and not T.find(cv2.imread(S % "dungeon-25"), "defheart")
print("new UI: ok")
