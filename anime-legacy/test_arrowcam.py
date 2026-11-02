"""The new minimap's arrow = the camera (10-19 laptop traces): the camera direction is read off
it and every turn is checked and corrected, so lost or short mouse drags no longer send the farm
into walls. Simulator, half the drags lost, with and without the mount.
    python test_arrowcam.py
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sim  # noqa: E402
import dungeon  # noqa: E402

for kw in ({"drag_fail": 0.5}, {"drag_fail": 0.5, "mount": 2.4}, {"k_true": 750.0}, {"drag_fail": 0.25}):
    # (drag_fail 0.25 seed 3: re-aiming at a door below face()'s own minimum turn looped for ever)
    for seed in ((1, 2, 3) if kw == {"drag_fail": 0.25} else (1, 2)):
        env = sim.SimEnv(seed=seed, arrow_follows="camera", **kw)
        lines = []
        env.log = lambda m, *a, **k: lines.append(m)
        run = dungeon.DungeonRun(env)
        run.run()
        # the "dungeon camera" log line counts the turns, and the drags that didn't turn the camera
        s = run.turn_stats
        assert s["n"] > 0 and s["drags"] >= s["n"] and s["sec"] > 0, s
        assert s["lost"] > 0 and s["careful"] > 0 if "drag_fail" in kw else s["lost"] == 0, (kw, s)
        stuck = sum(m.startswith("stuck") for m in lines)
        print(kw, seed, f"{env.t / 60:.1f} min, stuck {stuck}")
        assert env.t / 60 < 9.5 and stuck <= 3, (kw, seed, env.t, stuck)

# drags don't start on your name label in the middle of the screen (no drag turned the camera,
# 11-02 03:33, 06:02, 06:07), and one after a lost drag starts somewhere else
import types  # noqa: E402
import game  # noqa: E402
spots = []
real = game.winio.move_to, game.winio.right_drag
game.winio.move_to, game.winio.right_drag = lambda x, y: spots.append((x, y)), lambda px, slow=False: None
try:
    g = types.SimpleNamespace(active=lambda: True, rect=(0, 0), size=lambda: (1920, 1080), to_screen=lambda x, y: (x, y))
    for slow in (False, True, True, True, False):
        game.Game.cam_drag(g, 300, slow=slow)
finally:
    game.winio.move_to, game.winio.right_drag = real
assert spots[0] == spots[4] == spots[3] and len(set(spots[:3])) == 3, spots
assert all(abs(x - 960) > 300 and 500 < y < 880 for x, y in spots), spots
print("arrow camera: ok")
