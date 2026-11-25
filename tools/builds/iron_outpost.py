"""Iron outpost on the north patch: 10 units of electric drill -> stone
furnace (direct insertion), coal from a belt via inserters, plates out by
long-handed inserters onto a plate belt; coal riser from a splitter on the
coal line; plates to the mall. World tile coordinates throughout.

Rows: drills -86..-84 (facing S), furnaces -83..-82, inserters -81,
coal belt -80 (flows W), plate belt -79 (flows E)."""
import math, sys
sys.path.insert(0, sys.argv[1])
import cc  # noqa: E402

N, E, S, W = 0, 4, 8, 12
T = lambda n, x, y, d=0, **kw: dict({"n": n, "x": x + 0.5, "y": y + 0.5, "d": d}, **kw)
specs = []
UNITS = range(10)
for k in UNITS:
    x0 = -9 + 3 * k
    specs.append({"n": "electric-mining-drill", "x": x0 + 1.5, "y": -84.5, "d": S})
    specs.append({"n": "stone-furnace", "x": x0 + 2.0, "y": -82.0, "d": 0})
    specs.append(T("inserter", x0 + 1, -81, S))               # coal belt -> furnace
    specs.append(T("long-handed-inserter", x0 + 2, -81, N))   # furnace -> plate belt
    if k % 2 == 1:
        specs.append(T("small-electric-pole", x0, -82))
# coal: belt row -80 flowing W, fed by the riser on x 24
for x in range(-9, 24):
    specs.append(T("transport-belt", x, -80, W))
specs.append(T("transport-belt", 24, -80, W))
for y in range(-79, -27):
    specs.append(T("transport-belt", 24, y, N))
specs.append(T("transport-belt", 24, -28, N))
specs.append(T("transport-belt", 23, -28, E))                 # splitter tap output
# plates: row -79 flowing E, under the riser, then down x 27
for x in range(-8, 23):
    specs.append(T("transport-belt", x, -79, E))
specs.append(T("underground-belt", 23, -79, E, t="input"))
specs.append(T("underground-belt", 25, -79, E, t="output"))
specs.append(T("transport-belt", 26, -79, E))
for y in range(-79, -36):
    specs.append(T("transport-belt", 27, y, S))
FINAL = [T("transport-belt", 27, -36, E)] + [T("transport-belt", x, -36, E) for x in range(28, 40)] \
    + [T("transport-belt", 40, -35, N)]
# poles: up the riser from the coal-line pole at (25,-28), then over to the units
for y in (-35, -42, -49, -56, -63, -70, -77):
    specs.append(T("small-electric-pole", 25, y))
specs.append(T("small-electric-pole", 21, -82))

mode = sys.argv[2] if len(sys.argv) > 2 else "check"
if mode == "check":
    res = cc.call_batched("check", specs, {})
    cc.show({k: res.get(k) for k in ("blocked", "bom", "to_clear", "total")})
elif mode == "place":
    cc.show(cc.call_batched("place", specs, {"tag": "iron", "partial": True}))
elif mode == "final":
    cc.show(cc.call_batched("check", FINAL, {}))
