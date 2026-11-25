import json, math, subprocess, sys
tools, here = sys.argv[1], sys.argv[2]
sys.path.insert(0, tools)
import cc, layouts  # noqa: E402

specs = json.loads(subprocess.check_output([sys.executable, here + "/mall.py", "--json"]))
anchor = {"x": 40, "y": -38, "rot": 3, "mirror": False}
world = [layouts.transform(s, anchor) for s in specs]
poles = [(s["x"], s["y"]) for s in world if s["n"] == "small-electric-pole"]
grid_pole = (39.5, -27.5)
south = max(poles, key=lambda p: p[1])
link = (42.5, -32.5)
print("southmost mall pole", south, "link", link,
      "dists", round(math.dist(south, link), 2), round(math.dist(link, grid_pole), 2))
world.append({"n": "small-electric-pole", "x": link[0], "y": link[1], "d": 0})
xs = [s["x"] for s in world]; ys = [s["y"] for s in world]
print("footprint", min(xs), min(ys), max(xs), max(ys))
cmd = "place" if "--place" in sys.argv else "check"
cc.show(cc.call_batched(cmd, world, {"tag": "mall", "partial": True}))
