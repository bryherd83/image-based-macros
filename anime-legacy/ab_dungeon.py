"""A/B: dungeon.py now vs the last commit, on the simulator. Prints mean minutes per scenario.
    python ab_dungeon.py N [key=value settings for 'now' ...]
"""
import importlib.util, multiprocessing as mp, os, statistics, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sim  # noqa
import minimap as mm  # noqa

SCEN = {
    "normal": {},
    "3 far treasure enemies": {"treasure_far": 3},
    "25% drags lost": {"drag_fail": 0.25},
    "noisy map": {"noise_px": 1.0},
    "narrow doors": {"door_w": 0.09},
}


def load(which):
    if which == "now":
        path = os.path.join(HERE, "dungeon.py")
    else:
        src = subprocess.run(["git", "show", f"{which}:dungeon.py"], cwd=HERE, capture_output=True, text=True,
                             encoding="utf-8", check=True).stdout
        path = os.path.join(os.environ.get("TEMP", HERE), f"dungeon_{which}_{os.getpid()}.py")
        open(path, "w", encoding="utf-8").write(src)
    spec = importlib.util.spec_from_file_location(f"dungeon_{which}", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def one(args):
    which, name, kw, seed, extra = args
    m = load(which)
    env = sim.SimEnv(seed=seed, **kw)
    if which == "now":
        env.settings.update(extra)
    total = sum(1 for c in env.rooms.values() if c in (mm.TODO, mm.TREASURE))
    m.DungeonRun(env).run()
    done = sum(1 for c in env.rooms.values() if c == mm.CLEARED)
    t = env.cleared_order[-1][0] / 60 if done == total and env.cleared_order else None
    scans = sum(1 for _, msg in env.last_msgs if "looking at the whole map" in msg)
    return which, name, t, scans


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    extra = {}
    for a in sys.argv[2:]:
        k, v = a.split("=")
        extra[k] = float(v)
    jobs = [(w, name, kw, 300 + s, extra) for w in ("HEAD", "now") for name, kw in SCEN.items() for s in range(n)]
    with mp.Pool(max(1, mp.cpu_count() - 2)) as pool:
        res = pool.map(one, jobs)
    print(f"{'scenario':24s} {'before':>22s} {'now':>22s}   (mean min · full clears · scans)")
    for name in SCEN:
        row = []
        for w in ("HEAD", "now"):
            rs = [r for r in res if r[0] == w and r[1] == name]
            full = [r[2] for r in rs if r[2] is not None]
            row.append(f"{statistics.mean(full) if full else 0:5.2f} min {len(full):2d}/{len(rs):<2d} {statistics.mean(r[3] for r in rs):4.1f}")
        print(f"{name:24s} {row[0]:>22s} {row[1]:>22s}")
