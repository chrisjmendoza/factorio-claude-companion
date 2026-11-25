"""Copper outpost on the south side of the copper patch, same unit as iron:
electric drill -> stone furnace, coal inserter from a coal belt, long-handed
inserter onto a plate belt. Rows: drills 36..38 (S), furnaces 39..40,
inserters 41, coal belt 42 (W), plates 43 (E).
Coal: splitter on the coal strip's tail at (-14..-13, 42), tap west along y 40.
Plates: east along y 43 (under the strip tail), north up x 38, under the
coal row, then into the mall's plate belt A at (40,-36) from the east."""
import math, sys
sys.path.insert(0, sys.argv[1])
import cc  # noqa: E402

N, E, S, W = 0, 4, 8, 12
T = lambda n, x, y, d=0, **kw: dict({"n": n, "x": x + 0.5, "y": y + 0.5, "d": d}, **kw)
specs = []
for k in range(8):
    x0 = -74 + 3 * k
    specs.append({"n": "electric-mining-drill", "x": x0 + 1.5, "y": 37.5, "d": S})
    specs.append({"n": "stone-furnace", "x": x0 + 2.0, "y": 40.0, "d": 0})
    specs.append(T("inserter", x0 + 1, 41, S))
    specs.append(T("long-handed-inserter", x0 + 2, 41, N))
    if k % 2 == 1:
        specs.append(T("small-electric-pole", x0, 40))
# coal tap: strip tail -> (-14,41) N -> west along y 40 -> down x -50 -> row 42 W
specs.append(T("transport-belt", -14, 41, N))
for x in range(-49, -13):
    specs.append(T("transport-belt", x, 40, W))
specs.append(T("transport-belt", -50, 40, S))
specs.append(T("transport-belt", -50, 41, S))
for x in range(-74, -49):
    specs.append(T("transport-belt", x, 42, W))
# plates: row 43 east, under the strip tail at x -13
for x in range(-73, -14):
    specs.append(T("transport-belt", x, 43, E))
specs.append(T("underground-belt", -14, 43, E, t="input"))
specs.append(T("underground-belt", -12, 43, E, t="output"))
for x in range(-11, 37):
    specs.append(T("transport-belt", x, 43, E))
# north up x 38 to the coal row, under it, on to the mall
for y in range(43, -26, -1):  # up to and including -25, the tile before the underground
    specs.append(T("transport-belt", 37, y, N))
specs.append(T("underground-belt", 37, -26, N, t="input"))
specs.append(T("underground-belt", 37, -28, N, t="output"))
for y in range(-29, -34, -1):
    specs.append(T("transport-belt", 37, y, N))
specs += [T("transport-belt", 37, -34, E), T("transport-belt", 38, -34, E), T("transport-belt", 39, -34, E), T("transport-belt", 40, -34, E),
          T("transport-belt", 41, -34, N), T("transport-belt", 41, -35, N), T("transport-belt", 41, -36, W)]
# poles: units chain east along y 41 to the coal strip's pole at (-14,45)
for x in range(-47, -15, 6):
    specs.append(T("small-electric-pole", x, 41))
specs.append(T("small-electric-pole", -17, 41))
SPLITTER_AT = (-13.0, 42.5)   # N-facing splitter over the strip tail, pasted as a replacement ghost

mode = sys.argv[2] if len(sys.argv) > 2 else "check"
if mode == "check":
    res = cc.call_batched("check", specs, {})
    cc.show({k: res.get(k) for k in ("blocked", "bom", "to_clear", "total")})
elif mode == "place":
    cc.show(cc.call_batched("place", specs, {"tag": "copper", "partial": True}))

