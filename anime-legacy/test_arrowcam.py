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
print("arrow camera: ok")
