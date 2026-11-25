# Lessons learned

Things learned while building with Claude Companion, from mistakes and from studying Chris's blueprints. Add an entry whenever something breaks or a blueprint teaches something new. Say what happened, why, and what to do instead.

## Belts and lanes

- **Inserters drop on the far lane; drills drop on the near lane.** A drill's output point sits just past its edge, inside the near half of the next tile.
- **Sideloading** (a belt running into the side of another) puts everything on the target's near lane. If the target tile has nothing feeding it from behind, it turns into a **curve** instead, which keeps both lanes. A sideload tile needs a belt behind it.
- **Sideloading into an underground** passes only the lane on the open side; the hood blocks the other half. Chris's blueprints use this on purpose to merge one lane into a tunnel while the other lane carries on (it's also in blueprint-tools/CLAUDE.md). Don't "fix" it.
- **Splitters** keep lanes and split each lane separately. A splitter facing a belt's side sideloads.
- **Lane plans are part of the design.** On 2026-11-24 the outpost links swapped the mall belt's lanes (iron west, copper east) while old plates still sat on it, and Chris had to clear it by hand. Before changing which side feeds a belt, warn first and plan the cleanup.
- **Undergrounds (Chris's style):** one pair per crossing at full reach (yellow 4, red 6, blue 8, turbo 10 tiles between). Go under at belt intersections for breathing room. Don't chain short pairs.

## Placement and ghosts

- **Trees can't be ghosts.** The game rejects `entity-ghost` for the tree type whatever its flags. A ghostable stand-in, such as a planted-sapling `simple-entity-with-owner` that the mod swaps for a tree once built, does work (tested headless).
- **Ghosts don't block tree growth.** TreeRegrow seeds landed under base ghosts and stopped the robots. Fixed in 0.1.5; any spawning script must check for ghosts itself.
- **A splitter ghost can only replace a belt once that belt is marked for deconstruction.** Marking a live belt is risky: bots may lift it before a splitter exists and starve whatever it feeds (the steam plant's coal, at one point). Have the splitter in hand first.
- **Trees under a pasted base:** clear only what overlaps ghosts (`clear_under_ghosts`). A blanket sweep felled about 500 trees Chris didn't want and flooded his inventory with wood. Ask before clearing forest.
- **Pole coverage:** a small pole powers 2.5 tiles each way from its centre. When adding one inserter or machine by hand, check it's inside a supply area (missed once and Chris caught it).
- **Keep growth paths clear.** Lamps placed "beside every pole" landed on the steam plant's next-unit row (the water pipe and coal belt continue there) and blocked its growth, breaking the "tileable without change" promise. When decorating, skip any build's reserved growth tiles; a dry run of the next size catches it.
- **Drill strips need a powered path back to the grid.** The south ore lines' poles ended at the base's edge, but the base's own poles weren't built yet, so the strips sat at status 60 (no power). Check drill status after building an outpost; 1 is working, 38 is output full.
- **Blueprint world offsets:** `build_blueprint` centres the print. Working out world coordinates from blueprint coordinates came out one tile off in x, and the iron route stopped one tile short. Check computed positions against the live map before routing to them.

## Generated layouts

- **Always run a dead-end lint before placing a route.** A dry-run `check` only compares the world against the plan, so a tile missing from the plan passes. The copper route shipped with a one-tile gap (an off-by-one `range`). `route.py` now refuses routes with dead ends.
- **Belts need no power; pole lines along a route only carry power to its far end.** Two parallel routes share one pole line, split where they diverge. Laying a line per route doubled the poles down the shared corridor (Chris caught it). `route.py` now reuses existing poles near the path.
- **The router's "never take a belt's output" rule must exempt the route's own start.** The start tile is meant to receive the source belt's items. It only worked while the source was still a ghost (ghosts don't count as feeding); once built, every route from it came back "no route found". Found by flood-filling and splitting the route into halves.
- **Respect what Chris planted.** The fastest path ran straight down his tree avenue. Pass `--avoid x1,y1,x2,y2` for planted or decorative areas before routing.
- **Pole lines must check reach at corners.** "A pole every 6 tiles, beside the belt" let a corner's side offset stretch one gap to 8.6 tiles, over the 7.5 reach, which would have left the coal strip unpowered. `route.py` now measures every gap.
- **Assemblers don't accept science packs,** so science assemblers can't be chained. Each needs its own inserter into a lab.
- **Every mall output chest needs a limit.** An uncapped chest keeps its assembler running and drains shared inputs. The lamp line made 707 lamps (707 circuits plus iron and copper) and the pole line 764 poles, while red science starved of gears. After capping belts (2 slots), red arms, drills, assemblers and lamps (1 each) and poles (2), the inserter chest went from near-empty to 178 in one cycle. Set limits as part of building the cell.
- **Burner smelters fed by long-handed inserters keep their output empty.** There's nothing to collect there; plates are on the belt.
- **Ratios:** electric drill 0.5 ore/s; stone furnace 0.3125 plates/s; assembler 1 runs at 0.5 speed. One gear assembler 1 makes 1 gear/s, which starved the mall. A yellow inserter moves about 0.83 items/s, so a single chest-feed inserter capped the whole mall.

## Factorio 2.x API

- Electric network statistics count consumption as **input** and production as **output**, the reverse of item statistics. They're only available on **electric poles** (`pole.electric_network_statistics`).
- Reading a key a LuaObject doesn't have **raises**, it doesn't return nil. Many prototype stats became quality methods (`get_max_power_output()`), so wrap version-dependent lookups in `pcall`.
- `set_recipe` returns items as name-to-count in 1.1 and as a list of records in 2.x; handle both.
- Fuel is `fuel_categories = {"chemical"}` (plural) in 2.1.
- **Player-less characters** need room to start: the pathfinder refuses a start wedged between machines, even when `find_non_colliding_position` accepted it. Spawn with 2x2 clearance, and step clear after a failed path. They don't show on the map, so draw a `render_mode = "chart"` marker. A personal roboport on one works: its bots build ghosts from its inventory.

- **Plan character paths with a padded hitbox.** Characters walk in only 8 directions, so a path threaded between tree trunks with the true ±0.2 box can't be followed. The character walked into a trunk and re-planned the same path for 9 minutes. Plan with ±0.45, and step clear if it's still stuck after two re-plans. Tested through 160 random trees.
- **A Lua local can't see a local declared after it.** A function calling a helper defined further down gets nil unless the helper is forward-declared (`local unstick` up top, `unstick = function ...` below).
- **Headless `--benchmark` never processes `force.chart`** (`is_chunk_charted` stays false even when called directly), so map-reveal code can only be checked in a real game.
- **Player-less characters don't reveal the map** the way player characters do. Chart around them from script (`force.chart` once a second).

## Tooling (Windows)

- Factorio's Lua UDP socket starts with a small buffer and **drops the first datagram over about 4 KB** each session while it grows. Batch requests under 3 KB.
- Lua's JSON writes an empty table as `{}`, so an empty list arrives as a dict.
- PowerShell `>` writes UTF-16, which `fbp` can't read, and `Set-Content -Encoding utf8` adds a BOM that breaks Factorio's `info.json` and changelog. Write files from Python, or as ASCII.
- Inline `python -c` with quotes inside PowerShell breaks easily. Put anything non-trivial in a script file.
- A zip Factorio has open can't be deleted. Deploy new versions under new names and remove the old zip after the game closes (a background wait loop).

## From Chris's designs

- **Electric mining (Chris's tip):** put drills side by side with no gaps, facing the belt, and leave one free column behind each drill row for a line of poles. More drills per tile of ore than gap rows. Layout: `drill_row` (9 wide; a pole behind every pair of drills, 6 apart). The two pole columns are 8 apart, over wire reach, so link each side to the grid separately.
- **Coal snake:** 16 burner drills in one serpentine loop on coal, each fuelling the next; it stores up to 800 coal. Better output than a 4-drill pinwheel. Layout: `coal_snake`.
- **Dual-sided steam:** a coal belt up the middle, boilers both sides, 2 engines per boiler; it grows a unit at a time to 20 boilers per pump. Layout: `steam_dual`.
- **Starter base book (v17/18):** ore and coal enter on each smelting line's west end, each input labelled with a constant combinator; plates run east into a spine of one belt per item, with splitter taps under the columns into the wings. Stages paste over each other (stone, then steel, then electric furnaces; assembler 1, 2, 3).
