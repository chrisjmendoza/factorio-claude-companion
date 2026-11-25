"""Belt sources (belts nothing feeds) in the pasted starter base, in world
coordinates, with the nearest constant-combinator label."""
import sys, math
sys.path.insert(0, sys.argv[1])
import cc  # noqa: E402

root = cc.bp_decode(open(sys.argv[2], encoding="utf-8").read())
bp = next(b for label, b in cc.bp_walk(root) if "yellow" in label and "FULL PASTE" in label)
at = (float(sys.argv[3]), float(sys.argv[4]))
ents = bp["entities"]
xs = [e["position"]["x"] for e in ents]; ys = [e["position"]["y"] for e in ents]
# offset guess: build_blueprint centres the bounding box on the position
cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
off = (at[0] - round(cx) + 1, at[1] - round(cy))  # +1 x: checked against the live map (base iron input is at x 60)
print("entity bbox", min(xs), min(ys), max(xs), max(ys), "offset guess", off)

V = {0: (0, -1), 4: (1, 0), 8: (0, 1), 12: (-1, 0)}
tiles = {}
for e in ents:
    if e["name"] in ("transport-belt", "underground-belt"):
        tiles[(math.floor(e["position"]["x"]), math.floor(e["position"]["y"]))] = e
    if e["name"] == "splitter":
        d = e.get("direction", 0); px, py = e["position"]["x"], e["position"]["y"]
        for s in (-0.5, 0.5):
            dx, dy = (s, 0) if d in (0, 8) else (0, s)
            tiles[(math.floor(px + dx), math.floor(py + dy))] = e


def outputs_into(src, dst_tile):
    d = src.get("direction", 0); vx, vy = V[d]
    sx, sy = math.floor(src["position"]["x"]), math.floor(src["position"]["y"])
    if src["name"] == "splitter":
        return False  # handled loosely
    if src["name"] == "underground-belt" and src.get("type") == "input":
        return False
    return (sx + vx, sy + vy) == dst_tile


labels = [e for e in ents if e["name"] == "constant-combinator"]


def label_near(x, y):
    best = min(labels, key=lambda c: (c["position"]["x"] - x) ** 2 + (c["position"]["y"] - y) ** 2, default=None)
    if not best:
        return ""
    sigs = []
    for sec in (best.get("control_behavior", {}).get("sections", {}).get("sections", [])):
        for f in sec.get("filters", []):
            sigs.append(f.get("name"))
    return f"{sigs} @{math.dist((x, y), (best['position']['x'], best['position']['y'])):.0f}"


sources = []
for t, e in tiles.items():
    if e["name"] != "transport-belt":
        continue
    d = e.get("direction", 0); vx, vy = V[d]
    behind = (t[0] - vx, t[1] - vy)
    fed = False
    for nb in ((t[0] + 1, t[1]), (t[0] - 1, t[1]), (t[0], t[1] + 1), (t[0], t[1] - 1)):
        s = tiles.get(nb)
        if s and (outputs_into(s, t) or (s["name"] == "splitter" and nb == behind)
                  or (s["name"] == "underground-belt" and s.get("type") == "output" and nb == behind)):
            fed = True
    if not fed:
        sources.append((t, d))

for (x, y), d in sorted(sources):
    wx, wy = x + off[0], y + off[1]
    print(f"source world ({wx:.0f},{wy:.0f}) dir {d:2d}  label {label_near(x + 0.5, y + 0.5)}")

