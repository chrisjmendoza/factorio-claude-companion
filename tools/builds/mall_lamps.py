"""Lamp chain on the free side (local north) of the mall's plate belt A:
cable1 -> circuit -> LAMP <- cable2, iron/copper straight off belt A,
lamps out to a chest."""
import json, math, subprocess, sys
tools, here = sys.argv[1], sys.argv[2]
sys.path.insert(0, tools)
import cc, layouts  # noqa: E402

N, E, S, W = 0, 4, 8, 12
anchor = {"x": 40, "y": -38, "rot": 3, "mirror": False}
A = lambda x, r: {"n": "assembling-machine-1", "x": x + 1.5, "y": -2.5, "d": 0, "r": r}  # rows -4..-2
I = lambda x, y, d: {"n": "inserter", "x": x + 0.5, "y": y + 0.5, "d": d}
loc = [
    A(0, "copper-cable"), I(1, -1, S),            # copper off A
    I(3, -3, W),                                  # cable -> circuit
    A(4, "electronic-circuit"), I(5, -1, S),      # iron off A
    I(7, -3, W),                                  # circuit -> lamp
    A(8, "small-lamp"), I(9, -1, S),              # iron off A
    I(11, -3, E),                                 # cable2 -> lamp
    A(12, "copper-cable"), I(13, -1, S),          # copper off A
    I(9, -5, S), {"n": "wooden-chest", "x": 9.5, "y": -5.5, "d": 0},   # lamps out
]
# fix the chest: inserter at row -5 picks the lamp assembler (south), drops north
loc[-1] = {"n": "wooden-chest", "x": 9.5, "y": -6 + 0.5, "d": 0}
for px, py in ((3, -1), (7, -1), (11, -1), (7, -5)):
    loc.append({"n": "small-electric-pole", "x": px + 0.5, "y": py + 0.5, "d": 0})

old = json.loads(subprocess.check_output([sys.executable, here + "/mall.py", "--json"]))
old_poles = [(s["x"], s["y"]) for s in old if s["n"] == "small-electric-pole"]
print("link to mall network:", round(min(math.dist((3.5, -0.5), p) for p in old_poles), 2))
world = [layouts.transform(s, anchor) for s in loc]
cmd = "place" if "--place" in sys.argv else "check"
cc.show(cc.call_batched(cmd, world, {"tag": "mall", "partial": True}))
