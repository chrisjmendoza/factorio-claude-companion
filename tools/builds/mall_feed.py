"""Triples the mall's iron feed and doubles its copper feed: belt A grows two
tiles west (local), with extra chest+inserter pairs on each side."""
import json, math, subprocess, sys
tools, here = sys.argv[1], sys.argv[2]
sys.path.insert(0, tools)
import cc, layouts  # noqa: E402

N, E, S, W = 0, 4, 8, 12
anchor = {"x": 40, "y": -38, "rot": 3, "mirror": False}
T = lambda s: layouts.transform(s, anchor)

loc = [
    {"n": "transport-belt", "x": -2.5, "y": 0.5, "d": E},
    {"n": "transport-belt", "x": -1.5, "y": 0.5, "d": E},
    {"n": "inserter", "x": -2.5, "y": -0.5, "d": N}, {"n": "wooden-chest", "x": -2.5, "y": -1.5, "d": 0},
    {"n": "inserter", "x": -1.5, "y": -0.5, "d": N}, {"n": "wooden-chest", "x": -1.5, "y": -1.5, "d": 0},
    {"n": "inserter", "x": -1.5, "y": 1.5, "d": S},  {"n": "wooden-chest", "x": -1.5, "y": 2.5, "d": 0},
    {"n": "small-electric-pole", "x": -3.5, "y": 0.5, "d": 0},
]
old = json.loads(subprocess.check_output([sys.executable, here + "/mall.py", "--json"]))
old_poles = [(s["x"], s["y"]) for s in old if s["n"] == "small-electric-pole"]
print("new pole to nearest old pole:", round(min(math.dist((-3.5, 0.5), p) for p in old_poles), 2))

# the old input labels sit where the new chests go: remove those two ghosts first
old_labels = [T({"n": "constant-combinator", "x": -1.5, "y": -1.5, "d": 0}),
              T({"n": "constant-combinator", "x": -1.5, "y": 2.5, "d": 0})]
world = [T(s) for s in loc]
if "--place" not in sys.argv:
    cc.show(cc.call_batched("check", world, {}))
    print("labels to move:", [(l["x"], l["y"]) for l in old_labels])
    sys.exit(0)
for l in old_labels:
    print(cc.call("remove_ghosts", {"area": [[l["x"] - 0.4, l["y"] - 0.4], [l["x"] + 0.4, l["y"] + 0.4]]}))
cc.show(cc.call_batched("place", world, {"tag": "mall", "partial": True}))
# new labels just past the feed, on each side
labels = [(T({"n": "c", "x": -3.5, "y": -1.5, "d": 0}), "iron-plate"),
          (T({"n": "c", "x": -3.5, "y": 2.5, "d": 0}), "copper-plate")]
ents = [{"entity_number": i, "name": "constant-combinator", "position": {"x": p["x"], "y": p["y"]},
         "control_behavior": {"sections": {"sections": [{"index": 1, "filters": [
             {"index": 1, "name": sig, "quality": "normal", "comparator": "=", "count": 1}]}]}}}
        for i, (p, sig) in enumerate(labels, 1)]
xs = [p["x"] for p, _ in labels]; ys = [p["y"] for p, _ in labels]
text = cc.bp_encode({"blueprint": {"item": "blueprint", "label": "labels", "entities": ents, "version": 562954249961472}})
cc.call("bp_part", {"id": "feedlbl", "i": 1, "n": 1, "data": text})
cc.show(cc.call("bp_build", {"id": "feedlbl", "position": [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2]}))
chk = cc.call_batched("check", [{"n": "constant-combinator", "x": p["x"], "y": p["y"], "d": 0} for p, _ in labels], {})
print("labels in place:", chk.get("exists"), "of 2")
