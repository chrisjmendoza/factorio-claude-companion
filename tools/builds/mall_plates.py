"""Plate chest at the mall: an inserter takes iron and copper plates off belt
A into an iron chest, so Claude's character has plates to hand-craft what
the mall doesn't make (assembler 2s, splitters...). Cap it so it can't drain
the belt. Same frame as mall.py (anchor (40,-38), rot 3)."""
import math, sys
tools = sys.argv[1]
sys.path.insert(0, tools)
import cc, layouts  # noqa: E402

N, E, S, W = 0, 4, 8, 12
anchor = {"x": 40, "y": -38, "rot": 3, "mirror": False}
loc = [
    {"n": "inserter", "x": 42.5, "y": -0.5, "d": S},           # picks from belt A (south), drops north
    {"n": "iron-chest", "x": 42.5, "y": -1.5, "d": 0},
    {"n": "small-electric-pole", "x": 43.5, "y": -0.5, "d": 0},
]
print("link to the iron-chest cell's pole:", round(math.dist((43.5, -0.5), (38.5, -0.5)), 2))
world = [layouts.transform(s, anchor) for s in loc]
for s in world:
    if s["n"] == "iron-chest":
        print("plate chest at", s["x"], s["y"])
cmd = "place" if "--place" in sys.argv else "check"
cc.show(cc.call_batched(cmd, world, {"tag": "mall", "partial": True}))
