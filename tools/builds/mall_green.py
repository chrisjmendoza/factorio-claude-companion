"""Green science past the mall's labs: two assemblers in a row, fed from one
input chest (inserters + belts) at the far end, packs passed assembler to
assembler and into lab 2. Same frame as mall.py (anchor (40,-38), rot 3);
lab 2 sits on local x 58..60, rows 2..4."""
import json, math, subprocess, sys
tools, here = sys.argv[1], sys.argv[2]
sys.path.insert(0, tools)
import cc, layouts  # noqa: E402

N, E, S, W = 0, 4, 8, 12
anchor = {"x": 40, "y": -38, "rot": 3, "mirror": False}
I = lambda x, y, d: {"n": "inserter", "x": x + 0.5, "y": y + 0.5, "d": d}
# One assembler: assemblers don't accept science packs, so a second one
# chained behind it could never pass its packs on to the lab.
loc = [
    I(61, 3, E),                                                   # green -> lab 2
    {"n": "assembling-machine-1", "x": 63.5, "y": 3.5, "d": 0, "r": "logistic-science-pack"},
    I(65, 3, E),                                                   # input chest -> green
    {"n": "wooden-chest", "x": 66.5, "y": 3.5, "d": 0},
    {"n": "small-electric-pole", "x": 61.5, "y": 1.5, "d": 0},
    {"n": "small-electric-pole", "x": 65.5, "y": 1.5, "d": 0},
]
old_poles = [(57.5, 1.5), (53.5, 1.5), (53.5, 5.5)]  # from mall_red.py
print("link:", round(min(math.dist((61.5, 1.5), p) for p in old_poles), 2))
world = [layouts.transform(s, anchor) for s in loc]
for s in world:
    if s["n"] == "wooden-chest":
        print("input chest at", s["x"], s["y"])
cmd = "place" if "--place" in sys.argv else "check"
cc.show(cc.call_batched(cmd, world, {"tag": "mall", "partial": True}))
