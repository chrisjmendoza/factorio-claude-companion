#!/usr/bin/env python3
"""Builds every layout for real on a scratch area and checks it works.

Run against a throwaway map (a headless server is ideal) started with
--enable-lua-udp and the cheats setting on: it flattens ground, spawns ore
and water, places entities instantly and feeds them from infinity chests.
Never point it at a save you care about.

    python selftest.py --port 34598
"""
import argparse
import json
import sys
import time

import cc
import layouts
from layouts import ent, transform

ORIGIN_X, ORIGIN_Y = -400, -400   # far from spawn
CELL = 48                          # each test gets its own CELL x CELL square


def lua(code):
    return cc.call("lua", {"code": code}, timeout=30)["value"]


def prepare(cx, cy, ore=None, water=None):
    """Flattens a cell, optionally lays ore on an area and water on another.

    Areas are world tile rectangles (x1, y1, x2, y2), exclusive of x2/y2.
    """
    x1, y1 = cx - CELL // 2, cy - CELL // 2
    code = f"""
local s = game.surfaces.nauvis
s.request_to_generate_chunks({{{cx}, {cy}}}, 2)
s.force_generate_chunk_requests()
local area = {{{{{x1}, {y1}}}, {{{x1 + CELL}, {y1 + CELL}}}}}
for _, e in pairs(s.find_entities_filtered{{area = area}}) do
  if e.valid and e.type ~= "character" then e.destroy() end
end
local tiles = {{}}
for x = {x1}, {x1 + CELL - 1} do for y = {y1}, {y1 + CELL - 1} do
  tiles[#tiles + 1] = {{name = "grass-1", position = {{x, y}}}}
end end
s.set_tiles(tiles)
"""
    if water:
        wx1, wy1, wx2, wy2 = water
        code += f"""
local w = {{}}
for x = {wx1}, {wx2 - 1} do for y = {wy1}, {wy2 - 1} do w[#w + 1] = {{name = "water", position = {{x, y}}}} end end
s.set_tiles(w)
"""
    if ore:
        name, (ox1, oy1, ox2, oy2) = ore
        code += f"""
for x = {ox1}, {ox2 - 1} do for y = {oy1}, {oy2 - 1} do
  s.create_entity{{name = "{name}", position = {{x + 0.5, y + 0.5}}, amount = 100000}}
end end
"""
    code += "return true"
    lua(code)


def place(template, anchor):
    specs = [transform(s, anchor) for s in template]
    result = cc.call_batched("place", specs, {"instant": True})
    if result.get("blocked") or result.get("failed"):
        raise AssertionError(f"placement failed: {json.dumps(result)[:600]}")
    return specs


def world_box(local_box, anchor):
    """A local tile rectangle (x1, y1, x2, y2) moved into the world."""
    x1, y1, x2, y2 = local_box
    a = transform({"x": x1, "y": y1}, anchor)
    b = transform({"x": x2, "y": y2}, anchor)
    return (int(min(a["x"], b["x"])), int(min(a["y"], b["y"])), int(max(a["x"], b["x"])), int(max(a["y"], b["y"])))


def power_source(spec):
    """A free 5 MW source next to the given world spec position."""
    lua(f"""
local s = game.surfaces.nauvis
local e = s.create_entity{{name = "electric-energy-interface", position = {{{spec['x']}, {spec['y']}}}, force = "player"}}
e.power_production = 5000000 / 60
e.power_usage = 0
e.electric_buffer_size = 5000000
return true""")


def feed(chest_spec, item):
    """An infinity chest that keeps itself stocked with `item`."""
    lua(f"""
local s = game.surfaces.nauvis
local c = s.create_entity{{name = "infinity-chest", position = {{{chest_spec['x']}, {chest_spec['y']}}}, force = "player"}}
c.set_infinity_container_filter(1, {{name = "{item}", count = 50, mode = "at-least", index = 1}})
c.remove_unfiltered_items = true
return true""")


def count_in(area, names, item, belts=False):
    """How many `item` are inside matching entities (or on belts) in an area."""
    x1, y1, x2, y2 = area
    if belts:
        body = f"""
for _, b in pairs(s.find_entities_filtered{{area = a, type = "transport-belt"}}) do
  for i = 1, 2 do n = n + b.get_transport_line(i).get_item_count("{item}") end
end"""
    else:
        body = f"""
for _, e in pairs(s.find_entities_filtered{{area = a, name = {json.dumps(names).replace('[', '{').replace(']', '}')}}}) do
  n = n + e.get_item_count("{item}")
end"""
    return int(lua(f"""
local s = game.surfaces.nauvis
local a = {{{{{x1}, {y1}}}, {{{x2}, {y2}}}}}
local n = 0
{body}
return n"""))


def fuel(area, names, count=20):
    x1, y1, x2, y2 = area
    lua(f"""
local s = game.surfaces.nauvis
for _, e in pairs(s.find_entities_filtered{{area = {{{{{x1}, {y1}}}, {{{x2}, {y2}}}}}, name = {json.dumps(names).replace('[', '{').replace(']', '}')}}}) do
  e.insert{{name = "coal", count = {count}}}
end
return true""")


def cell_center(i):
    return ORIGIN_X + (i % 8) * CELL, ORIGIN_Y + (i // 8) * CELL


# ---------------------------------------------------------------------------
# tests: each sets up a cell, builds, and returns a check to run later

def test_steam(i, rot, mirror):
    cx, cy = cell_center(i)
    anchor = {"x": cx, "y": cy, "rot": rot, "mirror": mirror}
    # pump faces local south, so water is local rows 2 and beyond
    prepare(cx, cy, water=world_box((-6, 2, 7, 10), anchor))
    template = layouts.steam_power(boilers=2, engines=2)
    specs = place(template, anchor)
    fuel(cell_area(cx, cy), ["boiler"])
    pole = next(s for s in specs if s["n"] == "small-electric-pole")
    # a load to draw the power: an interface that only consumes
    lua(f"""
local s = game.surfaces.nauvis
local p = s.find_non_colliding_position("electric-energy-interface", {{{pole['x']}, {pole['y']}}}, 3, 0.5, true)
local e = s.create_entity{{name = "electric-energy-interface", position = p, force = "player"}}
e.power_production = 0
e.power_usage = 1000000 / 60
e.electric_buffer_size = 1000000
return true""")

    def check():
        steam = float(lua(f"""
local s = game.surfaces.nauvis
local n = 0
for _, e in pairs(s.find_entities_filtered{{area = {{{{{cx - 24}, {cy - 24}}}, {{{cx + 24}, {cy + 24}}}}}, name = "steam-engine"}}) do
  if e.get_fluid_count("steam") > 0 then n = n + 1 end
end
return n"""))
        return steam == 4, f"{int(steam)}/4 engines have steam"
    return check


def cell_area(cx, cy):
    return (cx - CELL // 2, cy - CELL // 2, cx + CELL // 2, cy + CELL // 2)


def test_drills(i, rot, mirror):
    cx, cy = cell_center(i)
    anchor = {"x": cx, "y": cy, "rot": rot, "mirror": mirror}
    prepare(cx, cy, ore=("iron-ore", world_box((0, 0, 7, 15), anchor)))
    template = layouts.drill_strip(segments=2, tail=4)
    place(template, anchor)
    power_source(transform({"x": 1.0, "y": -1.0}, anchor))

    def check():
        on_belt = count_in(cell_area(cx, cy), None, "iron-ore", belts=True)
        tail = count_in(world_box((3, -4, 4, -1), anchor), None, "iron-ore", belts=True)
        return on_belt > 0 and tail > 0, f"{on_belt} ore on the belt, {tail} past the north end"
    return check


def test_smelter(i, rot, mirror, sides=2):
    cx, cy = cell_center(i)
    anchor = {"x": cx, "y": cy, "rot": rot, "mirror": mirror}
    prepare(cx, cy)
    template = layouts.smelter_column(rows=4, sides=sides)
    # feed: one extra belt tile on top of each input belt, ore from one side, coal from the other
    extra = [ent("transport-belt", 0.5, -0.5, layouts.S), ent("inserter", -0.5, -0.5, layouts.W),
             ent("inserter", 1.5, -0.5, layouts.E)]
    if sides > 1:
        extra += [ent("transport-belt", 10.5, -0.5, layouts.S), ent("inserter", 9.5, -0.5, layouts.W),
                  ent("inserter", 11.5, -0.5, layouts.E)]
    place(template + extra, anchor)
    feed(transform({"x": -1.5, "y": -0.5}, anchor), "iron-ore")
    feed(transform({"x": 2.5, "y": -0.5}, anchor), "coal")
    if sides > 1:
        feed(transform({"x": 8.5, "y": -0.5}, anchor), "iron-ore")
        feed(transform({"x": 12.5, "y": -0.5}, anchor), "coal")
    power_source(transform({"x": -1.0, "y": 3.0}, anchor))

    def check():
        plates = count_in(world_box((5, 0, 6, 8), anchor), None, "iron-plate", belts=True)
        furnaces = count_in(cell_area(cx, cy), ["stone-furnace"], "iron-plate")
        return plates > 0, f"{plates} plates on the output belt, {furnaces} in furnaces"
    return check


def test_burner_smelt(i, rot, mirror):
    cx, cy = cell_center(i)
    anchor = {"x": cx, "y": cy, "rot": rot, "mirror": mirror}
    prepare(cx, cy, ore=("iron-ore", world_box((0, 0, 4, 8), anchor)))
    place(layouts.burner_smelt(count=2, rows=2), anchor)
    fuel(cell_area(cx, cy), ["burner-mining-drill", "stone-furnace"], 10)

    def check():
        plates = count_in(cell_area(cx, cy), ["stone-furnace"], "iron-plate")
        lit = int(lua(f"""
local s = game.surfaces.nauvis
local n = 0
for _, e in pairs(s.find_entities_filtered{{area = {{{{{cx - 24}, {cy - 24}}}, {{{cx + 24}, {cy + 24}}}}}, name = "stone-furnace"}}) do
  if e.get_item_count("iron-plate") > 0 or e.get_item_count("iron-ore") > 0 then n = n + 1 end
end
return n"""))
        return lit == 4, f"{lit}/4 furnaces receiving ore, {plates} plates made"
    return check


def test_burner_coal(i, rot, mirror):
    cx, cy = cell_center(i)
    anchor = {"x": cx, "y": cy, "rot": rot, "mirror": mirror}
    prepare(cx, cy, ore=("coal", world_box((0, 0, 4, 2), anchor)))
    place(layouts.burner_coal(count=2), anchor)
    fuel(cell_area(cx, cy), ["burner-mining-drill"], 5)

    def check():
        coal = count_in(cell_area(cx, cy), ["wooden-chest"], "coal")
        return coal > 0, f"{coal} coal in chests"
    return check


TESTS = [
    ("steam_power", test_steam),
    ("drill_strip", test_drills),
    ("smelter_column", test_smelter),
    ("smelter_column(1 side)", lambda i, r, m: test_smelter(i, r, m, sides=1)),
    ("burner_smelt", test_burner_smelt),
    ("burner_coal", test_burner_coal),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=34598)
    ap.add_argument("--wait", type=float, default=40.0, help="real seconds to let things run")
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    cc.GAME_PORT = a.port

    if not cc.call("ping")["cheats"]:
        sys.exit("the cheats setting is off on that game; selftest needs it")

    checks, index = [], 0
    for name, fn in TESTS:
        if a.only and a.only not in name:
            continue
        for rot, mirror in ((0, False), (1, False), (2, False), (3, False), (1, True)):
            if mirror and name in layouts.LAYOUTS and not getattr(layouts.LAYOUTS[name], "mirrorable", True):
                continue
            label = f"{name} rot={rot}{' mirror' if mirror else ''}"
            try:
                checks.append((label, fn(index, rot, mirror)))
            except Exception as err:  # noqa: BLE001 - report and carry on
                checks.append((label, err))
            index += 1

    print(f"built {len(checks)} cases; letting them run {a.wait:.0f}s")
    time.sleep(a.wait)

    failures = 0
    for label, check in checks:
        if isinstance(check, Exception):
            print(f"FAIL {label}: {check}")
            failures += 1
            continue
        ok, detail = check()
        print(f"{'ok  ' if ok else 'FAIL'} {label}: {detail}")
        failures += 0 if ok else 1
    print(f"{len(checks) - failures}/{len(checks)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
