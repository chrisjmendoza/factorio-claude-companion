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
  `remove_ghosts`, `deconstruct`, `ghosts`, `inventory`, `production`,
  `research`, `mark`, `clear_marks`, and `lua` (cheats only).
- **Layouts:** `tools/layouts.py` holds the build templates (steam power,
  electric drill strips, smelting columns, burner drill/furnace pairs).
  `tools/selftest.py` builds each one for real at every rotation on a
  throwaway map and checks that it produces. Run it after changing a layout.

`tools/` is development tooling and is not shipped in the mod zip.

## Testing against a headless server

```
factorio.exe --start-server test.zip --enable-lua-udp 34598 --server-settings ss.json
python tools/cc.py --port 34598 ping
python tools/selftest.py --port 34598     # needs the cheats setting on
```
