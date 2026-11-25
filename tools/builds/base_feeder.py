"""Small-pole feeder from the powered coal-route poles to the nearest pole
ghost of the pasted base."""
import math, sys
sys.path.insert(0, sys.argv[1])
import cc  # noqa: E402

grid = [(e["x"], e["y"]) for e in cc.call("scan", {"area": [[0, 20], [25, 45]]})["entities"]
        if e["n"] == "small-electric-pole"]
base = cc.call("scan", {"area": [[55, 44], [90, 70]]}, timeout=30)["entities"]
ghost_poles = [(e["x"], e["y"]) for e in base
               if e["n"] == "entity-ghost" and e.get("ghost") == "small-electric-pole" or e["n"] == "small-electric-pole"]
print("grid poles", len(grid), "base pole ghosts", len(ghost_poles), "sample", base[:2])
if not grid or not ghost_poles:
    sys.exit("missing poles")
a, b = min(((g, h) for g in grid for h in ghost_poles), key=lambda t: math.dist(*t))
print("link", a, "->", b, round(math.dist(a, b), 1))
n = math.ceil(math.dist(a, b) / 6.8)
chain = []
for k in range(1, n):
    t = k / n
    chain.append((math.floor(a[0] + (b[0] - a[0]) * t) + 0.5, math.floor(a[1] + (b[1] - a[1]) * t) + 0.5))
pts = [a] + chain + [b]
print("gaps", [round(math.dist(p, q), 1) for p, q in zip(pts, pts[1:])])
specs = [{"n": "small-electric-pole", "x": x, "y": y, "d": 0} for x, y in chain]
cmd = "place" if "--place" in sys.argv else "check"
cc.show(cc.call_batched(cmd, specs, {"tag": "feeder", "partial": True}))
