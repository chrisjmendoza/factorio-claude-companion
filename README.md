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
  `research`, `mark`, `clear_marks`, and `lua` (cheats only).
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
| `refuel` | `area`, `fuel`, `per` | top up burner buildings (default 5 coal each) |
| `craft` | `recipe`, `count` | hand-craft; queues only what it has ingredients for |
| `mine` | `kind`, `name`, `at`, `radius`, `count` | mine by hand, nearest first |
| `deconstruct` | `area` | mine everything marked for deconstruction in an area |
| `pickup` | `at`, `radius` | collect items lying on the ground |
| `rotate` | `at`, `direction` | turn a building (0 north, 4 east, 8 south, 12 west) |
| `wait` | `ticks`, or `craft: true` | wait a while, or until crafting finishes |

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
