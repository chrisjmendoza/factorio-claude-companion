# Builds in the 2026-11-24 game

One-off scripts that laid out the first Claude Companion base. They record the exact world geometry, so later edits can be made against the same coordinates. Each one takes the `tools` directory as its first argument and dry-runs (`check`) unless told to place.

| Script | What it built | Where |
| --- | --- | --- |
| `coal_route.py` | Coal belt from the electric drill strip to the steam plant's feed stub, with a pole line | coal patch (-13,52) to steam (51,-27) |
| `mall.py`, `place_mall.py` | Bootstrap mall: plate belt A (iron/copper), intermediates belt B (gears/circuits), product cells into chests | strip x 34..47, y -38..-87, rotated with anchor (40,-38) rot 3 |
| `mall_red.py` | Red science cell feeding two labs at the mall's north end | (43,-90) |
| `mall_feed.py` | Extra plate-feed chests (since removed for the outpost links) | (40,-37) |
| `mall_lamps.py` | Lamp chain on the west side of belt A | (36,-45) |
| `stone_outpost.py` | Electric drills on stone into a stone-furnace assembler, with a pole chain | (8,87) |
| `iron_outpost.py` | 10 drill-to-furnace units, coal riser from a splitter at (22,-27), plates down x 27 into belt A's west lane | (5,-82) |
| `final_link.py` | Waits for the old feed chests to clear, then places the iron link into belt A | (40,-36) |
| `copper_outpost.py` | 8 units on the copper patch, coal tap from the strip tail, plates up x 37 into belt A's east lane | (-62,37) |
| `base_feeder.py` | Pole line from the coal route to the pasted starter base | (20,38) to (77,53) |
| `lights.py` | One lamp beside every pole in a set of areas | various |
| `labels.py` | Constant-combinator labels, pasted as a blueprint so the signals survive | mall, steam coal entry |
| `inputs.py` | Lists the starter base's belt inputs in world coordinates | base at (150,142) |

Mall plate belt lanes since the outpost links: iron on the west lane, copper on the east.

`../watch.py` is the milestone watcher: it polls `ghosts`, `production` and `power` once a minute and prints only on finished builds, rate thresholds, power load or empty boilers, plus a 10-minute heartbeat.
