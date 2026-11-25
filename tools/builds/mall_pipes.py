"""Pipes and pipe-to-ground on the free side of the mall's plate belt A, after
the pole cell: pipe assembler (iron off A) -> pipe-to-ground assembler (iron
off A + pipes), with a pipe chest and a pipe-to-ground chest. Same frame as
mall.py (anchor (40,-38), rot 3)."""
import json, math, subprocess, sys
tools, here = sys.argv[1], sys.argv[2]
sys.path.insert(0, tools)
import cc, layouts  # noqa: E402

N, E, S, W = 0, 4, 8, 12
anchor = {"x": 40, "y": -38, "rot": 3, "mirror": False}
A = lambda x, r: {"n": "assembling-machine-1", "x": x + 1.5, "y": -2.5, "d": 0, "r": r}
I = lambda x, y, d: {"n": "inserter", "x": x + 0.5, "y": y + 0.5, "d": d}
C = lambda x, y: {"n": "wooden-chest", "x": x + 0.5, "y": y + 0.5, "d": 0}
P = lambda x, y: {"n": "small-electric-pole", "x": x + 0.5, "y": y + 0.5, "d": 0}
loc = [
    A(26, "pipe"), I(27, -1, S),                 # iron off A
    I(27, -5, S), C(27, -6),                     # pipes out to a chest (for the base)
    I(29, -3, W),                                # pipes -> pipe-to-ground assembler
    A(30, "pipe-to-ground"), I(31, -1, S),       # iron off A
    I(33, -3, W), C(34, -3),                     # pipe-to-ground out
    P(29, -1), P(29, -5), P(33, -1),
]
pole_cell = [(19.5, -0.5), (23.5, -4.5)]
print("link to pole cell:", round(min(math.dist((29.5, -0.5), p) for p in pole_cell), 2))
# every inserter inside some pole's 5x5 supply area
poles = [(s["x"], s["y"]) for s in loc if s["n"] == "small-electric-pole"]
for s in loc:
    if s["n"] == "inserter":
        ok = any(abs(px - s["x"]) <= 2.5 and abs(py - s["y"]) <= 2.5 for px, py in poles)
        if not ok:
            print("UNPOWERED inserter at local", s["x"], s["y"])
world = [layouts.transform(s, anchor) for s in loc]
for s in world:
    if s["n"] == "wooden-chest":
        print("chest at", s["x"], s["y"])
cmd = "place" if "--place" in sys.argv else "check"
cc.show(cc.call_batched(cmd, world, {"tag": "mall", "partial": True}))
