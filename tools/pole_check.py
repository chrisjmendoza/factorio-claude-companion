"""Groups electric poles into wire-connected networks by reach and shows the
closest gap between networks, so a pole line that falls short is easy to find.

    python tools/pole_check.py [--at x,y] [--r 120]
"""
import argparse, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cc  # noqa: E402

REACH = {"small-electric-pole": 7.5, "medium-electric-pole": 9, "big-electric-pole": 32, "substation": 18}
ap = argparse.ArgumentParser()
ap.add_argument("--at", default="0,0")
ap.add_argument("--r", type=float, default=120)
a = ap.parse_args()
x, y = map(float, a.at.split(","))
res = cc.call("scan", {"center": [x, y], "radius": a.r, "names": list(REACH), "limit": 5000}, timeout=60)
P = [(e["x"], e["y"], REACH[e["n"]]) for e in res["entities"] if not e.get("ghost")]
par = list(range(len(P)))
def f(i):
    while par[i] != i:
        par[i] = par[par[i]]; i = par[i]
    return i
for i in range(len(P)):
    for j in range(i + 1, len(P)):
        if math.dist(P[i][:2], P[j][:2]) <= min(P[i][2], P[j][2]):
            par[f(i)] = f(j)
groups = {}
for i in range(len(P)):
    groups.setdefault(f(i), []).append(P[i][:2])
gs = sorted(groups.values(), key=len, reverse=True)
print(f"{len(P)} poles in {len(gs)} network(s)")
for g in gs:
    xs, ys = [p[0] for p in g], [p[1] for p in g]
    print(f"  {len(g):>4} poles, x {min(xs)}..{max(xs)}, y {min(ys)}..{max(ys)}")
for i in range(len(gs)):
    for j in range(i + 1, len(gs)):
        d, p, q = min((math.dist(p, q), p, q) for p in gs[i] for q in gs[j])
        if d < 40:
            print(f"  gap {d:.1f} between {p} and {q}")
