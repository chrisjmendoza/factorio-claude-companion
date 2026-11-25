"""Lamp ghosts beside every built small pole in the areas Chris travels:
one lamp per pole on the first free neighbouring tile."""
import sys
sys.path.insert(0, sys.argv[1])
import cc  # noqa: E402

AREAS = {
    "mall": [[33, -100], [48, -30]],
    "steam": [[50, -40], [80, -24]],
    "route": [[-20, -30], [56, 45]],
    "coal": [[-20, 42], [-6, 62]],
    "stone": [[-20, 60], [12, 105]],
}
poles = set()
for name, area in AREAS.items():
    r = cc.call("scan", {"area": area}, timeout=30)
    for e in r["entities"]:
        if e["n"] == "small-electric-pole":
            poles.add((e["x"], e["y"]))
    print(name, "poles so far", len(poles), "truncated" if r.get("truncated") else "")

OFFS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)]
chosen, pending = [], sorted(poles)
for off in OFFS:
    if not pending:
        break
    specs = [{"n": "small-lamp", "x": x + off[0], "y": y + off[1], "d": 0} for x, y in pending]
    res = cc.call_batched("check", specs, {})
    blocked = {(b["x"], b["y"]) for b in (res.get("blocked") or [])} if isinstance(res.get("blocked"), list) else set()
    still = []
    for (x, y), s in zip(pending, specs):
        if (s["x"], s["y"]) in blocked:
            still.append((x, y))
        else:
            chosen.append(s)
    pending = still
print("lamps:", len(chosen), "poles with no free neighbour:", len(pending))
if "--place" in sys.argv:
    cc.show(cc.call_batched("place", chosen, {"tag": "lights", "partial": True}))
