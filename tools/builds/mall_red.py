"""Extends the bootstrap mall north: belts A and B carry on, a red science
assembler takes copper (A) and gears (B) and inserts straight into a lab,
which passes packs on to a second lab."""
import json, math, subprocess, sys
tools, here = sys.argv[1], sys.argv[2]
sys.path.insert(0, tools)
import cc, layouts  # noqa: E402

N, E, S, W = 0, 4, 8, 12
loc = []
for tx in range(49, 53):
    loc.append({"n": "transport-belt", "x": tx + 0.5, "y": 0.5, "d": E})
    loc.append({"n": "transport-belt", "x": tx + 0.5, "y": 6.5, "d": E})
loc += [
    {"n": "assembling-machine-1", "x": 51.5, "y": 3.5, "d": 0, "r": "automation-science-pack"},
    {"n": "inserter", "x": 51.5, "y": 1.5, "d": N},   # copper from A
    {"n": "inserter", "x": 51.5, "y": 5.5, "d": S},   # gears from B
    {"n": "inserter", "x": 53.5, "y": 3.5, "d": W},   # packs -> lab 1
    {"n": "lab", "x": 55.5, "y": 3.5, "d": 0},
    {"n": "inserter", "x": 57.5, "y": 3.5, "d": W},   # lab 1 -> lab 2
    {"n": "lab", "x": 59.5, "y": 3.5, "d": 0},
    {"n": "small-electric-pole", "x": 53.5, "y": 1.5, "d": 0},
    {"n": "small-electric-pole", "x": 53.5, "y": 5.5, "d": 0},
    {"n": "small-electric-pole", "x": 57.5, "y": 1.5, "d": 0},
]
old = json.loads(subprocess.check_output([sys.executable, here + "/mall.py", "--json"]))
old_poles = [(s["x"], s["y"]) for s in old if s["n"] == "small-electric-pole"]
new_poles = [(s["x"], s["y"]) for s in loc if s["n"] == "small-electric-pole"]
print("nearest old pole to (53.5,1.5):", round(min(math.dist((53.5, 1.5), p) for p in old_poles), 2))
anchor = {"x": 40, "y": -38, "rot": 3, "mirror": False}
world = [layouts.transform(s, anchor) for s in loc]
cmd = "place" if "--place" in sys.argv else "check"
cc.show(cc.call_batched(cmd, world, {"tag": "mall", "partial": True}))
