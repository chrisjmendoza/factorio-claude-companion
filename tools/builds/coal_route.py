"""Coal belt from the electric drill strip on the coal patch to the steam
plant's west feed stub, with a small-pole line alongside it.

Path (world tiles): strip belt runs north up x=-13 to y=41, then
east along y=40 to x=19, north up x=20 to y=-26, east along y=-27 to x=51,
ending at the stub's west end (52,-27), which flows east.
Usage: coal_route.py TOOLS_DIR [--dry]
"""
import math, sys

sys.path.insert(0, sys.argv[1])
import cc, layouts  # noqa: E402

DRY = "--dry" in sys.argv
N, E = layouts.N, layouts.E

path = []  # (tx, ty, dir)
for x in range(-13, 20):
    path.append((x, 40, E))
for y in range(40, -27, -1):
    path.append((20, y, N))
for x in range(20, 52):
    path.append((x, -27, E))
# corner tiles take the direction of the leg they start
path = [(x, y, d) for (x, y, d) in path]
seen, belts = set(), []
for x, y, d in path:
    if (x, y) in seen:
        continue
    seen.add((x, y))
    belts.append((x, y, d))
# the corner (20,40) appears as the end of the east leg and the start of the
# north leg; keep the north-facing one so it turns
belts = [b for b in belts if (b[0], b[1]) != (20, 40)] + [(20, 40, N)]
belts = [b for b in belts if (b[0], b[1]) != (20, -27)] + [(20, -27, E)]
belt_tiles = {(x, y) for x, y, _ in belts}

LEFT = {E: (0, -1), N: (-1, 0)}
poles = []
for i, (x, y, d) in enumerate(path):
    if i % 7:
        continue
    dx, dy = LEFT[d]
    t = (x + dx, y + dy)
    if t in belt_tiles:
        t = (x - dx, y - dy)
    poles.append(t)
poles.append((52, -28))  # bridges to the steam plant's west pole at (57.5,-32.5)

# wire-reach sanity check (small pole: 7.5), including the strip's north pole
chain = [(-14, 45)] + poles + [(57, -33)]
for a, b in zip(chain, chain[1:]):
    dist = math.dist(a, b)
    if dist > 7.5:
        print(f"WARNING poles {a} -> {b} are {dist:.1f} apart")

specs = [{"n": "transport-belt", "x": x + 0.5, "y": y + 0.5, "d": d} for x, y, d in belts]
specs += [{"n": "small-electric-pole", "x": x + 0.5, "y": y + 0.5, "d": 0} for x, y in poles]
print(f"{len(belts)} belts, {len(poles)} poles")
res = cc.call_batched("check" if DRY else "place", specs, {"tag": "coal-line", "partial": True})
cc.show(res)
