"""Stone furnace outpost on the stone patch: drill strip (belt north up x=0,
y 103..86), an assembler making stone furnaces from the belt's end, a chest,
and a pole chain back to the coal strip's south pole at (-14.5, 59.5)."""
import math, sys
sys.path.insert(0, sys.argv[1])
import cc, layouts  # noqa: E402

N, E, S, W = 0, 4, 8, 12
anchor = {"x": 1, "y": 89, "rot": 0, "mirror": False}
specs = [layouts.transform(s, anchor) for s in layouts.drill_strip(segments=2, tail=3)]
specs += [
    {"n": "inserter", "x": 5.5, "y": 86.5, "d": W},          # belt end (4,86) -> assembler
    {"n": "assembling-machine-1", "x": 7.5, "y": 86.5, "d": 0, "r": "stone-furnace"},
    {"n": "inserter", "x": 9.5, "y": 86.5, "d": W},          # assembler -> chest
    {"n": "wooden-chest", "x": 10.5, "y": 86.5, "d": 0},
    {"n": "small-electric-pole", "x": 7.5, "y": 88.5, "d": 0},
]
# pole chain from the coal strip's south pole to the stone strip's north pole
a, b = (-14.5, 59.5), (3.5, 89.5)
n = math.ceil(math.dist(a, b) / 7.0)
for k in range(1, n):
    t = k / n
    specs.append({"n": "small-electric-pole", "x": math.floor(a[0] + (b[0] - a[0]) * t) + 0.5,
                  "y": math.floor(a[1] + (b[1] - a[1]) * t) + 0.5, "d": 0})
chain = [a] + [(s["x"], s["y"]) for s in specs[-(n - 1):]] + [b]
print("pole gaps", [round(math.dist(p, q), 1) for p, q in zip(chain, chain[1:])])
cmd = "place" if "--place" in sys.argv else "check"
cc.show(cc.call_batched(cmd, specs, {"tag": "stone", "partial": True}))

