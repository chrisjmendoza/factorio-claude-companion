# Claude Companion

Play a map together with Claude. Chat in game and Claude reads it; Claude
answers in game chat, reads the map, and lays down builds as **ghosts** that
your construction robots then build from your inventory. Claude never spawns
items: if you don't have what a build needs, the ghosts wait.

## Setup

1. **Launch option.** In Steam: Factorio → Properties → Launch options:

   ```
   --enable-lua-udp 34198
   ```

   This lets the mod exchange messages with programs on your own PC over
   UDP port 34198 (localhost only). Without the option the mod still loads,
   but Claude can't reach it.

2. **Mods.** Enable *Claude Companion*. *Simple Bot Start* (BotStart) is a
   good partner: power armour and construction bots from the first second.

3. **New game, then tell Claude.** Claude works from the bridge in
   `tools/cc.py` on the same PC. Typing in chat (or `/claude <message>`)
   reaches Claude.

## Map settings

| Setting | Default | |
| --- | --- | --- |
| Chat passed to Claude | Everything | or only lines mentioning Claude, or only `/claude` |
| Allow Claude to use cheats | off | lets Claude run Lua and place real entities instantly. Leave off for a fair game |

Achievements: any third-party mod already turns them off, so this one costs
nothing extra there.

## How it works

- **Chat → Claude:** chat lines are appended to
  `%APPDATA%\Factorio\script-output\claude-companion\chat.jsonl`, along with
  finished research and a line when a save loads.
- **Claude → game:** `tools/cc.py` sends one JSON command per UDP packet;
  the mod answers to the sender's port. Commands: `ping`, `say`, `state`,
  `map`, `scan`, `resources`, `offshore_spots`, `check`, `fit`, `place`,
  `tiles`, `remove_ghosts`, `deconstruct`, `ghosts`, `inventory`, `production`,
  `research`, `research_triggers`, `area_status`, `watch`, `mark`, `clear_marks`, and `lua` (cheats only).
- **Layouts:** `tools/layouts.py` holds the build templates (steam power,
  electric drill strips, smelting columns, burner drill/furnace pairs).
  `tools/selftest.py` builds each one for real at every rotation on a
  throwaway map and checks that it produces. Run it after changing a layout.

## Claude's character

Claude can also play as a character of its own, which walks, carries items
and works at a player's real speed and reach. `agent_spawn` puts it on the
map; `agent_jobs {"jobs": [...]}` queues work, done in order; `agent_status`
reports its position, inventory and current job; `agent_stop` clears the
queue. Each finished or failed job is written to the chat file.

| Job | Arguments | |
| --- | --- | --- |
| `walk` | `to`, `within` | walk to a position |
| `say` | `text` | speak in game chat |
| `take` / `put` | `from` / `to`, `item`, `count` | move items out of or into a building; `put` also feeds a belt |
| `take_belt` | `area`, `item`, `count` | pick items off belts in an area |
| `build` | `area` | build the ghosts in an area from its own inventory, tiles included |
| `refuel` | `area`, `fuel`, `target` | top up burner buildings (default 5 coal each); a short supply is shared evenly |
| `craft` | `recipe`, `count`, `wait` | hand-craft; queues only what it has ingredients for; `wait: true` stays until it's made |
| `collect` | `area`, `item`, `count` | take an item (or everything) from every building output in an area |
| `mine` | `kind`, `name`, `at`, `radius`, `count` | mine by hand, nearest first |
| `deconstruct` | `area` | mine everything marked for deconstruction in an area |
| `pickup` | `at`, `radius` | collect items lying on the ground |
| `rotate` | `at`, `direction` | turn a building (0 north, 4 east, 8 south, 12 west) |
| `wait` | `ticks`, or `craft: true` | wait a while, or until crafting finishes |
| `repeat` | `every_ticks`, `jobs`, `times` | run a list of jobs now and again on a timer |

`mine` takes `kind` = `resource` (the default; `name` is the ore), `tree`,
`rock`, or `entity` (pick up one of its own buildings; `name` is required).
`count` is items of the main product, not things mined: a tree gives 4 wood.
Without a `count` it mines everything within `radius` (default 24) of `at`.
It can't mine what a player can't: oil, or ore that needs a fluid.

`build` fells trees and rocks marked for deconstruction under a ghost before
building it, and reports how many ghosts it `made`, what items were `missing`,
and how many were `blocked` by something it couldn't clear. If the character
dies, Claude gets a `died` report naming the cause, and the queue is dropped.

The game keeps no books for a character with no player behind it, so the mod
does: what it crafts and mines is added to the production statistics, and a
technology unlocked by crafting, mining or building something is researched
when the character does it. `agent_credit {"item": "lab", "count": 1}` counts
items it made before 0.2.9; they must still exist, carried or built.

A job that finishes without doing anything (a `take` that moved nothing, a
`build` that found no ghosts) is reported with `warn: true` and a `reason`.

A `repeat` registers its jobs and steps aside, so other jobs run in between;
its rounds are only reported when one fails or warns. `agent_stop` clears the
queue and every repeat; `{"keep_repeats": true}` keeps them, and
`{"repeat_id": n}` stops one.

Other commands for the character: `agent_status` (position, inventory, the
current job's target and progress, the crafting queue, repeats),
`agent_bots {"enabled": false}` (hold back its own construction robots so
ghosts are built by hand in the order given), `research_triggers` (what each
trigger technology still needs).

### Alerts

The mod writes `{"kind": "alert", "what": ...}` lines to the chat file when
something goes wrong within 48 tiles of the character or in an area added
with `watch {"area": [[x1, y1], [x2, y2]]}` (up to 10; `{"clear": true}`
forgets them):

| `what` | Meaning |
| --- | --- |
| `no_fuel` | a burner building has run out |
| `output_blocked` | a drill has nowhere to put its ore |
| `dropping_on_ground` | a drill is facing nothing |
| `no_minable_resources` | a drill has run out of ore |
| `output_full` | a furnace or assembler's output is full |
| `job_failed` | one of the character's jobs failed |
| `inventory_nearly_full` | the character has 5 or fewer free slots |
| `research_queue_empty` | research finished and nothing is queued |

A building is reported when it goes bad and again every five minutes while
it stays that way. `area_status` gives the whole picture on request: counts
by status name for each kind of building, and the positions of the ones that
aren't working.

Not yet possible for the character: driving, fighting and repairing,
changing armour or equipment, and swapping a building for its upgrade in
place (mine it and build the new one instead).

To watch it work:

- `/claude-follow`: your view follows Claude's character. Run it again, or
  press Esc, to come back.
- `/claude-watch`: a small camera window that follows it while you keep
  playing. Drag it by its title; `/claude-watch 0.3` sets the zoom; run it
  again to close.

## Development tools

- `tools/mcp_server.py`: an MCP server that gives the Claude desktop app
  direct tools for the game (`ping`, `agent_jobs`, `events`, `call`,
  `run_script`, and `guide`, which serves `docs/agent-guide.md`). Add it under
  Settings > Developer > Edit Config; the snippet is at the top of the file.
  It needs no packages and replaces the relay.
- `tools/relay.py` and `tools/ccr.py`: a file relay for a Claude that can't
  reach localhost. Run `python tools/relay.py` on the gaming PC; Claude then
  sends commands with `python3 tools/ccr.py cc.py ping`.
- `tools/headless_test.py`: runs the character's jobs on a throwaway map
  with its own folder and port, so it is safe while a game is open.

`tools/` is development tooling and is not shipped in the mod zip.

## Testing against a headless server

```
factorio.exe --start-server test.zip --enable-lua-udp 34598 --server-settings ss.json
python tools/cc.py --port 34598 ping
python tools/selftest.py --port 34598     # needs the cheats setting on
```
