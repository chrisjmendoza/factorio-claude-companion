"""Bootstrap mall generator. Local frame: plate belt A on row 0 flowing east
(iron on its south lane, copper on its north lane), product assemblers on rows
2-4, intermediates belt B on row 6 flowing east (gears south lane, circuits
north lane). Prints the spec list as JSON, or writes a blueprint string for fbp.
"""
import json, math, sys

N, E, S, W = 0, 4, 8, 12
specs = []


def ent(n, x, y, d=0, r=None):
    s = {"n": n, "x": x, "y": y, "d": d}
    if r:
        s["r"] = r
    specs.append(s)


def asm(x0, recipe):
    ent("assembling-machine-1", x0 + 1.5, 3.5, 0, recipe)


def ins(tx, ty, d, name="inserter"):
    ent(name, tx + 0.5, ty + 0.5, d)


def chest(tx, ty):
    ent("wooden-chest", tx + 0.5, ty + 0.5)


END = 48
for tx in range(-1, END + 1):
    ent("transport-belt", tx + 0.5, 0.5, E)
for tx in range(0, END + 1):
    ent("transport-belt", tx + 0.5, 6.5, E)
# plate feed at the west end
chest(-1, -2); ins(-1, -1, N)   # iron  -> south lane
chest(-1, 2);  ins(-1, 1, S)    # copper -> north lane

# gears -> B south lane
asm(0, "iron-gear-wheel"); ins(1, 1, N); ins(1, 5, N)
# cable -> circuits -> stub -> B north lane
asm(4, "copper-cable"); ins(5, 1, N); ins(7, 3, W)
asm(8, "electronic-circuit"); ins(9, 1, N); ins(11, 3, W)
for ty in (3, 4, 5):
    ent("transport-belt", 12.5, ty + 0.5, S)


def product(x0, recipe, out_chest=True, from_b=True):
    asm(x0, recipe)
    ins(x0 + 1, 1, N)
    if from_b:
        ins(x0 + 1, 5, S)
    ins(x0 + 3, 3, W)
    chest(x0 + 4, 3)


product(14, "transport-belt")
ins(19, 3, W); product(20, "underground-belt", from_b=False)
product(26, "inserter")
ins(31, 3, W); product(32, "long-handed-inserter")
product(38, "electric-mining-drill")
product(44, "assembling-machine-1")

# ---- poles: greedy cover of every powered entity from free tiles in rows 1 and 5
SIZE = {"assembling-machine-1": 3}
occupied = set()
for s in specs:
    k = SIZE.get(s["n"], 1)
    for dx in range(k):
        for dy in range(k):
            occupied.add((math.floor(s["x"] - k / 2) + dx, math.floor(s["y"] - k / 2) + dy))
powered = [s for s in specs if s["n"] in ("assembling-machine-1", "inserter", "long-handed-inserter")]


def covers(p, s):
    k = SIZE.get(s["n"], 1)
    px, py = p[0] + 0.5, p[1] + 0.5
    return (abs(px - s["x"]) < 2.5 + k / 2) and (abs(py - s["y"]) < 2.5 + k / 2)


cands = [(x, y) for y in (1, 5) for x in range(-1, END + 1) if (x, y) not in occupied]
poles, todo = [], list(range(len(powered)))
while todo:
    best = max(cands, key=lambda p: sum(covers(p, powered[i]) for i in todo))
    poles.append(best)
    cands.remove(best)
    todo = [i for i in todo if not covers(best, powered[i])]
# connect: add row-1 poles until consecutive gaps <= 7
poles.sort()
fixed = True
while fixed:
    fixed = False
    pts = sorted(poles)
    # union-find by wire reach
    groups = []
    for p in pts:
        g = [gr for gr in groups if any(math.dist(p, q) <= 7.5 for q in gr)]
        merged = [p] + [q for gr in g for q in gr]
        groups = [gr for gr in groups if gr not in g] + [merged]
    if len(groups) > 1:
        a, b = groups[0], groups[1]
        pa, pb = min(((x, y) for x in a for y in b), key=lambda t: math.dist(*t))
        mid = ((pa[0] + pb[0]) // 2, 1)
        options = sorted((c for c in cands), key=lambda c: math.dist(c, mid))
        poles.append(options[0]); cands.remove(options[0]); fixed = True
for p in poles:
    ent("small-electric-pole", p[0] + 0.5, p[1] + 0.5)

if "--json" in sys.argv:
    print(json.dumps(specs))
elif "--bp" in sys.argv:
    sys.path.insert(0, sys.argv[-1])
    import cc
    ents = []
    for i, s in enumerate(specs, 1):
        e = {"entity_number": i, "name": s["n"], "position": {"x": s["x"], "y": s["y"]}}
        if s["d"]:
            e["direction"] = s["d"]
        if s.get("r"):
            e["recipe"] = s["r"]
        ents.append(e)
    print(cc.bp_encode({"blueprint": {"item": "blueprint", "label": "Claude bootstrap mall", "entities": ents,
                                      "version": 562949958139904}}))
else:
    from collections import Counter
    print(Counter(s["n"] for s in specs), len(poles), "poles")
