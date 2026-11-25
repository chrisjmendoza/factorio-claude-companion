"""Small-pole cell on the free side of the mall's plate belt A, past the lamp
chain: cable (copper off A) -> pole assembler <- wood from a chest; poles out
to a chest. Same frame as mall.py (anchor (40,-38), rot 3)."""
import json, math, subprocess, sys
tools, here = sys.argv[1], sys.argv[2]
sys.path.insert(0, tools)
import cc, layouts  # noqa: E402

N, E, S, W = 0, 4, 8, 12
anchor = {"x": 40, "y": -38, "rot": 3, "mirror": False}
A = lambda x, r: {"n": "assembling-machine-1", "x": x + 1.5, "y": -2.5, "d": 0, "r": r}  # rows -4..-2
I = lambda x, y, d: {"n": "inserter", "x": x + 0.5, "y": y + 0.5, "d": d}
loc = [
    A(16, "copper-cable"), I(17, -1, S),          # copper off A
    I(19, -3, W),                                 # cable -> pole assembler
    A(20, "small-electric-pole"),
    I(21, -5, N), {"n": "wooden-chest", "x": 21.5, "y": -5.5, "d": 0},   # wood chest -> assembler
    I(23, -3, W), {"n": "wooden-chest", "x": 24.5, "y": -2.5, "d": 0},   # poles out
    {"n": "small-electric-pole", "x": 19.5, "y": -0.5, "d": 0},
    {"n": "small-electric-pole", "x": 23.5, "y": -4.5, "d": 0},
]
# the wood chest sits above the inserter: inserter (21,-5) picks north from (21,-6)
loc[5] = {"n": "wooden-chest", "x": 21.5, "y": -6 + 0.5, "d": 0}
old = json.loads(subprocess.check_output([sys.executable, here + "/mall.py", "--json"]))
poles = [(s["x"], s["y"]) for s in old if s["n"] == "small-electric-pole"] + [(15.5, -0.5), (11.5, -0.5)]
print("link to mall network:", round(min(math.dist((19.5, -0.5), p) for p in poles), 2))
world = [layouts.transform(s, anchor) for s in loc]
for s in world:
    if s["n"] == "wooden-chest":
        print("chest at", s["x"], s["y"])
cmd = "place" if "--place" in sys.argv else "check"
cc.show(cc.call_batched(cmd, world, {"tag": "mall", "partial": True}))
