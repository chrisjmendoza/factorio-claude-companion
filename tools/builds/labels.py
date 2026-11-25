"""Label combinators for my builds: check the tiles, then paste them as one
blueprint (build_blueprint keeps the combinator signals on the ghosts)."""
import math, sys
sys.path.insert(0, sys.argv[1])
import cc, layouts  # noqa: E402

mall = {"x": 40, "y": -38, "rot": 3, "mirror": False}
local = [((-2, -2), "iron-plate"), ((-2, 2), "copper-plate"),
         ((18, 2), "transport-belt"), ((24, 2), "underground-belt"), ((30, 2), "inserter"),
         ((36, 2), "long-handed-inserter"), ((42, 2), "electric-mining-drill"), ((48, 2), "assembling-machine-1")]
labels = []
for (tx, ty), sig in local:
    w = layouts.transform({"n": "constant-combinator", "x": tx + 0.5, "y": ty + 0.5, "d": 0}, mall)
    labels.append(((w["x"], w["y"]), sig))
labels.append(((51.5, -25.5), "coal"))  # west end of the steam plant's coal stub

specs = [{"n": "constant-combinator", "x": p[0], "y": p[1], "d": 0} for p, _ in labels]
chk = cc.call_batched("check", specs, {})
cc.show({k: chk.get(k) for k in ("blocked", "exists", "total")})
if chk.get("blocked") or "--paste" not in sys.argv:
    sys.exit(0)

ents = []
for i, ((x, y), sig) in enumerate(labels, 1):
    ents.append({"entity_number": i, "name": "constant-combinator", "position": {"x": x, "y": y},
                 "control_behavior": {"sections": {"sections": [{"index": 1, "filters": [
                     {"index": 1, "name": sig, "quality": "normal", "comparator": "=", "count": 1}]}]}}})
xs = [x for (x, _), _ in labels]; ys = [y for (_, y), _ in labels]
centre = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
text = cc.bp_encode({"blueprint": {"item": "blueprint", "label": "Claude labels", "entities": ents,
                                   "version": 562954249961472}})
uid = "lbl%d" % (sum(map(ord, text)) % 100000)
cc.call("bp_part", {"id": uid, "i": 1, "n": 1, "data": text})
cc.show(cc.call("bp_build", {"id": uid, "position": list(centre)}))
# verify: every label should now exist exactly where intended
again = cc.call_batched("check", specs, {})
print("after paste: exists", again.get("exists"), "of", len(specs), "blocked", again.get("blocked"))
