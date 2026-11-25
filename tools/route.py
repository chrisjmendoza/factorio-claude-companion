"""Belt router: finds a belt path over the live map and lays it as ghosts.

    python route.py --from 30,306 --to 58,119 --end E [--poles] [--place]

A* over map tiles. A belt may go straight or turn (turns cost a little
more). Where the way is blocked it dives under with a yellow underground
pair at up to full reach (4 tiles between), never across another
underground. It never puts a tile where an existing belt would feed into
it, and the last tile faces --end so it feeds the target straight on.
Trees and rocks are allowed (the placement marks them for clearing).
With --poles it adds small poles beside the path every few tiles, linked
to the nearest existing pole. Every route is run through the same
dead-end check as fbp lint before it is placed.
"""
import argparse, heapq, json, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cc  # noqa: E402

N, E, S, W = 0, 4, 8, 12
VEC = {N: (0, -1), E: (1, 0), S: (0, 1), W: (-1, 0)}
NAMES = {"N": N, "E": E, "S": S, "W": W}
BELT_CH = {"^": N, ">": E, "v": S, "<": W}
PASSABLE = set(".icksuoTr")  # land, ore, trees and rocks (cleared on placement)
UG_MAX_GAP = 4


def left(d): return (d - 4) % 16
def right(d): return (d + 4) % 16


def load_grid(x1, y1, x2, y2, chunk=50):
    """Tile chars for the box, fetched as several modest map calls."""
    grid = {}
    cx = x1 + chunk
    while cx - chunk <= x2:
        cy = y1 + chunk
        while cy - chunk <= y2:
            res = cc.call("map", {"center": [cx, cy], "radius": chunk}, timeout=60)
            ox, oy = res["origin"]["x"], res["origin"]["y"]
            for j, row in enumerate(res["rows"]):
                for i, ch in enumerate(row):
                    grid[(ox + i, oy + j)] = ch
            cy += 2 * chunk + 1
        cx += 2 * chunk + 1
    return grid


def blocked_by_feeds(grid):
    """Tiles an existing belt outputs into: a new belt there would receive its items."""
    out = set()
    for (x, y), ch in grid.items():
        if ch in BELT_CH:
            dx, dy = VEC[BELT_CH[ch]]
            out.add((x + dx, y + dy))
    return out


def astar(grid, start, start_dirs, goal, end_dir, avoid):
    def free(t):
        return grid.get(t) in PASSABLE and t not in avoid

    def h(t):
        return abs(t[0] - goal[0]) + abs(t[1] - goal[1])

    openq, seen, came = [], {}, {}
    for d in start_dirs:
        if free(start):
            st = (start, d, None)
            heapq.heappush(openq, (h(start), 0, start, d))
            seen[(start, d)] = 0
            came[(start, d)] = None
    while openq:
        _, g, t, d = heapq.heappop(openq)
        if t == goal and d == end_dir:
            path, key = [], (t, d)
            while key:
                prev = came[key]
                path.append((key[0], key[1], prev[2] if prev else "belt"))
                key = prev[:2] if prev else None
            return list(reversed(path))
        if seen.get((t, d), 1e18) < g:
            continue
        vx, vy = VEC[d]
        nxt = (t[0] + vx, t[1] + vy)
        moves = []
        if free(nxt):
            for nd, extra in ((d, 0), (left(d), 1.5), (right(d), 1.5)):
                moves.append((nxt, nd, 1 + extra, "belt"))
        # underground: entry on nxt facing d, exit k tiles further on
        if free(nxt):
            for k in range(2, UG_MAX_GAP + 2):
                ex = (nxt[0] + vx * k, nxt[1] + vy * k)
                between = [(nxt[0] + vx * i, nxt[1] + vy * i) for i in range(1, k)]
                if any(grid.get(b) == "U" for b in between):
                    break
                if free(ex) and not all(free(b) for b in between):
                    moves.append((ex, d, k + 4, ("ug", nxt)))
        for nt, nd, cost, kind in moves:
            ng = g + cost
            key = (nt, nd)
            if ng < seen.get(key, 1e18):
                seen[key] = ng
                came[key] = (t, d, kind)
                heapq.heappush(openq, (ng + h(nt), ng, nt, nd))
    return None


def to_specs(path):
    specs = []
    for (x, y), d, kind in path:
        if isinstance(kind, tuple) and kind[0] == "ug":
            ix, iy = kind[1]
            specs.append({"n": "underground-belt", "x": ix + 0.5, "y": iy + 0.5, "d": d, "t": "input"})
            specs.append({"n": "underground-belt", "x": x + 0.5, "y": y + 0.5, "d": d, "t": "output"})
        else:
            specs.append({"n": "transport-belt", "x": x + 0.5, "y": y + 0.5, "d": d})
    return specs


def dead_ends(specs, goal, end_dir):
    """Belts whose output tile holds nothing of the route (the lint check)."""
    tiles = {(math.floor(s["x"]), math.floor(s["y"])): s for s in specs}
    bad = []
    for (x, y), s in tiles.items():
        if s["n"] == "underground-belt" and s.get("t") == "input":
            continue
        vx, vy = VEC[s["d"]]
        if (x + vx, y + vy) not in tiles and (x, y) != goal:
            bad.append((x, y))
    return bad


REACH = 7.5


def poles_along(specs, grid, taken, every=6, existing=()):
    """Poles beside the path, never more than a small pole's wire reach apart.

    Walks the path and places a pole whenever the next tile would be out of
    reach of the last one (corners included: the side offset can stretch a
    gap past the reach, which once left a coal line unpowered). Poles that
    already exist within reach of the path start are reused instead of
    laying a second line beside them.
    """
    pts, out = [(math.floor(s["x"]), math.floor(s["y"]), s["d"]) for s in specs], []
    last = None
    for x, y, _ in pts[:1]:
        near = [p for p in existing if math.dist(p, (x + 0.5, y + 0.5)) <= REACH - 1]
        if near:
            last = min(near, key=lambda p: math.dist(p, (x + 0.5, y + 0.5)))
    for i, (x, y, d) in enumerate(pts):
        here = (x + 0.5, y + 0.5)
        # an existing pole close by (e.g. a line along a parallel route) serves here too
        near = [p for p in existing if math.dist(p, here) <= every - 2]
        if near:
            last = min(near, key=lambda p: math.dist(p, here))
            continue
        if last is not None and math.dist(last, here) < every:
            continue
        placed = False
        for side in (left(d), right(d)):
            vx, vy = VEC[side]
            t = (x + vx, y + vy)
            c = (t[0] + 0.5, t[1] + 0.5)
            if grid.get(t) in PASSABLE and t not in taken and (last is None or math.dist(last, c) <= REACH):
                out.append({"n": "small-electric-pole", "x": c[0], "y": c[1], "d": 0})
                taken.add(t)
                last = c
                placed = True
                break
        if not placed and last is not None and math.dist(last, here) > REACH - 1:
            print(f"warning: no pole spot near {x},{y}; check the gap there")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True, help="x,y of the first new belt tile")
    ap.add_argument("--start", default="N,E,S,W", help="allowed directions for the first tile")
    ap.add_argument("--to", required=True, help="x,y of the last belt tile")
    ap.add_argument("--end", required=True, help="direction the last tile faces (into the target)")
    ap.add_argument("--margin", type=int, default=15)
    ap.add_argument("--poles", action="store_true")
    ap.add_argument("--place", action="store_true")
    ap.add_argument("--tag", default="route")
    ap.add_argument("--save", default=None, help="write the specs here as JSON")
    ap.add_argument("--avoid", action="append", default=[],
                    help="x1,y1,x2,y2 box the route must not enter (e.g. a planted avenue); repeatable")
    a = ap.parse_args()
    sx, sy = map(int, a.src.split(","))
    gx, gy = map(int, a.to.split(","))
    m = a.margin
    grid = load_grid(min(sx, gx) - m, min(sy, gy) - m, max(sx, gx) + m, max(sy, gy) + m)
    avoid = blocked_by_feeds(grid)
    for box in a.avoid:
        x1, y1, x2, y2 = map(int, box.split(","))
        avoid |= {(x, y) for x in range(x1, x2 + 1) for y in range(y1, y2 + 1)}
    # the start tile is meant to receive the source belt's items
    avoid.discard((sx, sy))
    path = astar(grid, (sx, sy), [NAMES[s] for s in a.start.split(",")], (gx, gy), NAMES[a.end], avoid)
    if not path:
        sys.exit("no route found")
    specs = to_specs(path)
    bad = dead_ends(specs, (gx, gy), NAMES[a.end])
    ugs = sum(1 for s in specs if s["n"] == "underground-belt") // 2
    print(f"route: {len(specs)} pieces, {ugs} underground pairs, dead ends: {bad or 'none'}")
    if bad:
        sys.exit("refusing to place a route with dead ends")
    if a.poles:
        taken = {(math.floor(s['x']), math.floor(s['y'])) for s in specs}
        # built poles show as '+' on the map; ghost poles as ':' (shared with other ghosts),
        # so also ask the game for pole ghosts in the box
        existing = [(x + 0.5, y + 0.5) for (x, y), ch in grid.items() if ch == "+"]
        box = [[min(sx, gx) - m, min(sy, gy) - m], [max(sx, gx) + m, max(sy, gy) + m]]
        for e in cc.call("scan", {"area": box}, timeout=60)["entities"]:
            if e["n"] == "small-electric-pole":
                existing.append((e["x"], e["y"]))
        specs += poles_along(specs, grid, taken, existing=existing)
    if a.save:
        json.dump(specs, open(a.save, "w"))
    res = cc.call_batched("place" if a.place else "check", specs, {"tag": a.tag, "partial": True})
    cc.show({k: res.get(k) for k in ("placed", "blocked", "bom", "to_clear", "exists")})


if __name__ == "__main__":
    main()
