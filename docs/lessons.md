# Lessons learned

Things learned while building with Claude Companion, from mistakes and from studying Chris's blueprints. Add an entry whenever something breaks or a blueprint teaches something new. Say what happened, why, and what to do instead.

## Belts and lanes

- **Inserters drop on the far lane; drills drop on the near lane.** A drill's output point sits just past its edge, inside the near half of the next tile.
- **Sideloading** (a belt running into the side of another) puts everything on the target's near lane. If the target tile has nothing feeding it from behind, it turns into a **curve** instead, which keeps both lanes. A sideload tile needs either a belt behind it (less preferred) or a belt on the opposite side feeding into the other lane of the center belt. 
- **Sideloading into an underground** passes only the lane on the open side; the hood blocks the other half. Chris's blueprints use this on purpose to merge one lane into a tunnel while the other lane carries on (it's also in blueprint-tools/CLAUDE.md). Don't "fix" it.
- **Merge two belts of the same item with a splitter, not a sideload** (Chris fixed this at the base's iron input). A sideload crams the second belt onto one lane, which caps it at half a belt and leaves the source drills backed up. A splitter with both belts as inputs balances the two across its outputs, using both lanes. For the north and south iron belts into the base's iron line, feed both into a splitter's two inputs.
- **Splitters** keep lanes and split each lane separately. A splitter facing a belt's side sideloads.
- **Lane plans are part of the design.** On 2026-11-24 the outpost links swapped the mall belt's lanes (iron west, copper east) while old plates still sat on it, and Chris had to clear it by hand. Before changing which side feeds a belt, warn first and plan the cleanup.
- **Undergrounds (Chris's style):** one pair per crossing at full reach (yellow 4, red 6, blue 8, turbo 10 tiles between). Go under at belt intersections for breathing room. Don't chain short pairs when they can cover a gap. 

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
- **`--avoid x1,y1,x2,y2` keeps a route out of an area.** First used to route around a tree avenue, which turned out to be only a planting trial, so Chris didn't mind either way. Use it when an area genuinely matters.
- **Pole lines must check reach at corners.** "A pole every 6 tiles, beside the belt" let a corner's side offset stretch one gap to 8.6 tiles, over the 7.5 reach, which would have left the coal strip unpowered. `route.py` now measures every gap.
- **Assemblers don't accept science packs,** so science assemblers can't be chained. Each needs its own inserter into a lab.
- **Non-rotatable entities report facing north.** A rotated plan gives an assembler or pole another facing, so "same entity here?" must ignore facing for poles, chests, lamps, labs, furnaces and assemblers without fluid boxes, or a built machine looks like it blocks its own spot. (Assemblers count as rotatable because of fluid recipes, so `supports_direction` alone isn't enough.)
- **Every mall output chest needs a limit.** An uncapped chest keeps its assembler running and drains shared inputs. The lamp line made 707 lamps (707 circuits plus iron and copper) and the pole line 764 poles, while red science starved of gears. After capping belts (2 slots), red arms, drills, assemblers and lamps (1 each) and poles (2), the inserter chest went from near-empty to 178 in one cycle. Set limits as part of building the cell.
- **Burner smelters fed by long-handed inserters keep their output empty.** There's nothing to collect there; plates are on the belt.
- **Ratios:** electric drill 0.5 ore/s; stone furnace 0.3125 plates/s; assembler 1 runs at 0.5 speed. One gear assembler 1 makes 1 gear/s, which starved the mall. A yellow inserter moves about 0.86 items/s chest to chest (about 0.83 from a belt), so a single chest-feed inserter capped the whole mall. More numbers are under "Reference numbers" below.

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

- **Use iron chests, not wooden** (Chris): assemblers can make them from iron plates; wooden chests need wood carried in by hand. The mall has an iron-chest cell.
- **Electric mining (Chris's tip):** put drills side by side with no gaps, facing the belt, and leave one free column behind each drill row for a line of poles. More drills per tile of ore than gap rows. Layout: `drill_row` (9 wide; a pole behind every pair of drills, 6 apart). The two pole columns are 8 apart, over wire reach, so link each side to the grid separately.
- **Coal snake:** 16 burner drills in one serpentine loop on coal, each fuelling the next; it stores up to 800 coal. Better output than a 4-drill pinwheel. Layout: `coal_snake`.
- **Dual-sided steam:** a coal belt up the middle, boilers both sides, 2 engines per boiler; it grows a unit at a time. Layout: `steam_dual`. The pump isn't the limit in 2.x (one pump feeds 200 boilers, see "Reference numbers"). What limits it is the coal belt: a yellow belt (15 coal/s) feeds 33 boilers at 0.45 coal/s each.
- **The starter book's full paste leaves furnace gaps in the smelting lines' top rows** (iron at x 73, 76, 121, 124; brick at 121, 124), where only poles and lamps stand. Chris counts them as missing. Each gap takes the neighbouring unit: furnace, long-handed inserter 2.5 above (input), inserter 1.5 below (output). Check pasted lines against both the standalone line blueprint and the full paste; they differ.
- **Starter base book (v17/18):** ore and coal enter on each smelting line's west end, each input labelled with a constant combinator; plates run east into a spine of one belt per item, with splitter taps under the columns into the wings. Stages paste over each other (stone, then steel, then electric furnaces; assembler 1, 2, 3).

## Reference numbers (Factorio 2.1, researched 2026-11-24)

Checked against the game's own data files (2.1.25, base and space-age prototypes) and the wiki. Items marked *(unverified)* rest on community practice or on a figure worked out from cooldowns.

### Throughput

- **Belts:** yellow 15/s (7.5 per lane), red 30/s, blue 45/s, turbo 60/s (Space Age), at 4 items per lane per tile. An inserter won't drop onto a lane that's already packed solid.
- **Inserters, chest to chest at hand size 1:** burner 0.79/s, yellow 0.86/s, long-handed 1.25/s, fast 2.5/s, bulk 2.5/s × hand size. A long-handed inserter beats a yellow one.
- **Hand size in 2.0:** normal inserters start at 1, reach 2 at Inserter capacity bonus 2 (red+green science) and 3 at level 7. Bulk inserters start at 2 and reach 12 at level 7. Level 1 only helps bulk inserters.
- **Names changed in 2.0:** the old stack inserter is now the **bulk** inserter. The new **stack** inserter (Space Age) is the only thing that stacks items on belts. Belt stacking (up to 4 per stack, any belt tier) needs the stack-inserter research plus Transport belt capacity 1–2.

### Ratios

- **Steam (2.x):** boilers conserve energy using each fluid's heat capacity (in-game changelog). Water's heat capacity is 2 kJ and steam's 0.2 kJ, so **1 water makes 10 steam**. The offshore pump gives 1,200 water/s with no power, a boiler uses 6 water/s for 60 steam/s, and an engine takes 30 steam/s for 900 kW. That's **1 pump : 200 boilers : 400 engines**; in 1.1 it was 1:20:40.
- **Boiler:** burns 1.8 MW, which is 0.45 coal/s (coal holds 4 MJ), and makes 30 pollution/min.
- **Smelting:** iron and copper plates take 3.2 s: a stone furnace makes 0.3125/s and a steel furnace 0.625/s, both burning 90 kW (0.0225 coal/s).
  - A yellow belt of ore (15/s) fills 48 stone furnaces or 24 steel furnaces. A red belt fills 48 steel furnaces.
  - Steel takes 16 s for 5 iron plates, so one iron furnace feeds exactly one steel furnace of the same type.
  - Swapping stone furnaces for steel doubles the ore a column needs; check the input belt can carry it.
- **Electric drill:** mines a 5×5 area, makes 0.5 ore/s (uranium 0.25/s) and uses 90 kW. It takes 15 drills per yellow lane, 30 per belt.
- **Burner drill:** mines a 2×2 area, makes 0.25 ore/s and uses 150 kW (0.0375 coal/s). It pollutes 12/min, more than an electric drill's 10.
- **Assemblers:** assembler 1 runs at 0.5 speed (75 kW), assembler 2 at 0.75 (150 kW), assembler 3 at 1.25 (375 kW). A lab uses 60 kW.
- **Gears:** 0.5 s for 2 plates, so 1/s from an assembler 1, 1.5/s from an assembler 2 and 2.5/s from an assembler 3.
- **Green circuits:** cable is 0.5 s for 2; a circuit is 1 iron plus 3 cable in 0.5 s. That gives **3 cable : 2 circuit assemblers** at any tier; an assembler 1 pair makes 1 circuit/s.
- **Red science** (5 s): 0.1/s per assembler 1, so 1/s takes 10 of them plus 1 gear assembler.
- **Green science** (6 s): 0.083/s per assembler 1. For equal output, use 5 red assemblers to every 6 green.

### Power

- **Poles (wire reach / supply area):** small 7.5 / 5×5, medium 9 / 7×7, big 32 / 4×4, substation 18 / 18×18. Medium and big poles come with Electric energy distribution 1 (needs steel); the substation with distribution 2.
- **Solar:** a panel peaks at 60 kW and averages about 42 kW. An accumulator holds 5 MJ at up to 300 kW. Use about 0.84 accumulators per panel; about 24 panels and 20 accumulators give 1 MW around the clock.

### Biters and defence

- **Evolution** (default factors): time 0.000004/s, pollution 0.0000009 per unit produced, 0.002 per spawner killed. Each increase is scaled by (1 − evolution)², and since 2.0 evolution is tracked per planet. It counts pollution *produced*: absorption slows attacks but not evolution.
- **Absorption per chunk per minute:**
  - water 1.54, grass 1.11, sand 0.92
  - concrete and landfill 0
  - a healthy tree 0.06; trees start losing leaves above 60 pollution in their chunk
  - one boiler's 30/min is about 27 grass chunks, or about 500 trees
- **Attacks:** units only attack once pollution reaches a spawner. The pollution a spawner absorbs pays for attackers:
  - biters: small 4, medium 20, big 80
  - spitters: small 4, medium 12, big 30
  - groups go out every 1–10 minutes, and expansion parties every 10–60 minutes, more often as evolution rises
- **Gun turret:** range 18. A yellow magazine (4 iron, 1 s to craft) does 5 damage per round, 10 rounds; a red (piercing) one does 8. A firing turret uses about 1 magazine/s *(unverified, worked out)*, and inserters fill it to only 10 magazines.
- **Ranges:** gun turrets (18) and laser turrets (24) outrange spitters (13–16). Worms (25–48) outrange gun turrets, so never build turrets in a worm's reach.
- **Defence research:**
  - Gun turret, Stone wall and Military each cost 10 red.
  - Military 2 (piercing ammo) needs red+green and steel; Gate needs Stone wall and Military 2.
  - Flamethrowers need oil; laser turrets need blue science.
- **Walls** *(unverified, community practice)*: 1–2 thick, a few tiles in front of the turrets, so every wall tile sits inside turret range and biters stop to chew it while being shot.

### Logistics gotchas

- **Which lane an inserter takes from:** from a belt running across in front of it, the **near** lane first, and the far lane only when the near one is empty. From a belt pointing at it, or a curve, the belt's left lane.
- **Long-handed inserters** pick up and drop exactly 2 tiles away; they can't reach the tile next to them.
- **Filters in 2.0:** every inserter (burner included) has 5 filter slots, whitelist or blacklist. The filter inserter is gone.
- **How much inserters load into a machine:** 1 craft plus the crafts it finishes in 1.166 s, rounded up, so at least 2 crafts. Fuel goes in up to 5 items.
- **Chests:** wooden 16 slots, iron 32, steel 48. The red-X limit applies to the slots inserters fill.
- **Splitter filters:** the filtered item leaves on one side and everything else on the other. If one output is blocked, everything leaves by the other.

Sources: wiki.factorio.com (Transport belts/Physics, Inserters, Inserter capacity bonus, Bulk inserter, Power production, Steam engine, Boiler, Offshore pump, Big electric pole, Electric mining drill, Enemies, Pollution) and the Factorio 2.1.25 data files and changelog.
