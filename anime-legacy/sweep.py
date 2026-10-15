"""Bigger simulator sweep: many dungeons per scenario, in parallel. Prints mean / worst."""
import multiprocessing as mp
import statistics
import sys

import sim

SCENARIOS = {
    "normal": {},
    "camera turns less (k=900)": {"k_true": 900.0},
    "camera turns more (k=420)": {"k_true": 420.0},
    "25% drags lost": {"drag_fail": 0.25},
    "arrow follows camera": {"arrow_follows": "camera"},
    "narrow doors (0.09)": {"door_w": 0.09},
    "noisy map (1px)": {"noise_px": 1.0},
    "everything bad": {"k_true": 900.0, "drag_fail": 0.2, "door_w": 0.1, "noise_px": 0.8},
}


def one(args):
    name, kw, seed = args
    env, total, done = sim.run_one(seed=seed, **kw)
    t_all = env.cleared_order[-1][0] / 60 if done == total and env.cleared_order else None
    return name, seed, done, total, t_all, env.stats["spawns"], env.stats["jumps"]


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    jobs = [(name, kw, 100 + s) for name, kw in SCENARIOS.items() for s in range(n)]
    with mp.Pool(max(1, mp.cpu_count() - 2)) as pool:
        res = pool.map(one, jobs)
    print(f"{'scenario':28s} runs  full-clears  mean min  worst min  worst rooms  spawns/run")
    for name in SCENARIOS:
        rs = [r for r in res if r[0] == name]
        full = [r[4] for r in rs if r[4] is not None]
        worst_rooms = min(r[2] / r[3] for r in rs)
        print(f"{name:28s} {len(rs):4d}  {len(full):5d}/{len(rs):<5d} {statistics.mean(full) if full else 0:8.1f} "
              f"{max(full) if full else 0:9.1f}  {100 * worst_rooms:9.0f}%   {statistics.mean(r[5] for r in rs):8.2f}")
    bad = [r for r in res if r[4] is None]
    for r in bad[:10]:
        print("  not fully cleared:", r[0], "seed", r[1], f"{r[2]}/{r[3]}")
