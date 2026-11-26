#!/usr/bin/env python3
"""MCP server: gives a Claude app direct tools for the game, no relay.

The app starts this itself, on the gaming PC, and talks to it over stdin and
stdout (MCP's stdio transport: one JSON-RPC message per line). Add it to the
Claude desktop app under Settings > Developer > Edit Config:

    {"mcpServers": {"factorio": {
        "command": "python",
        "args": ["D:\\\\Dev\\\\factorio mods\\\\ClaudeCompanion\\\\tools\\\\mcp_server.py"]}}}

No packages needed. Nothing may be printed to stdout except protocol
messages; diagnostics go to stderr, which the app keeps in its MCP log.
"""
import json
import os
import subprocess
import sys
import time

TOOLS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TOOLS)
GUIDE = os.path.join(REPO, "docs", "agent-guide.md")
sys.path.insert(0, TOOLS)
import cc  # noqa: E402

PROTOCOL = "2025-06-18"
SUPPORTED = {"2024-11-05", "2025-03-26", "2025-06-18"}

INSTRUCTIONS = (
    "Tools for playing a Factorio map through the Claude Companion mod. Call `guide` first: it explains "
    "the jobs, the events and how to play. Then `ping` to check the game is reachable.")

JOB_HELP = (
    "A list of jobs, run in order. Each is an object with a `type`: walk {to}, say {text}, "
    "mine {kind,name,at,radius,count}, deconstruct {area}, pickup {at,radius}, take {from,item,count}, "
    "collect {area,item,count}, put {to,item,count}, take_belt {area,item,count}, build {area}, "
    "refuel {area,fuel,target}, craft {recipe,count,wait}, rotate {at,direction}, "
    "wait {ticks} or {craft:true}, repeat {every_ticks,jobs,times}. Positions are [x, y]; areas are "
    "[[x1, y1], [x2, y2]]. Always give mine a count.")

TOOL_DEFS = [
    {"name": "guide",
     "description": "How to play: the jobs, the events, the commands and the habits that work. Read this first.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "ping",
     "description": "Checks the game is reachable. Returns the mod version, the game tick and the player count.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "agent_status",
     "description": "Your character: position, inventory, free slots, the current job with its target and "
                    "progress, the crafting queue and any repeats.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "agent_jobs",
     "description": "Queues work for your character. Returns at once; each job's result arrives later as an "
                    "event, so follow with `events`. " + JOB_HELP,
     "inputSchema": {"type": "object", "required": ["jobs"], "properties": {
         "jobs": {"type": "array", "items": {"type": "object"}, "description": JOB_HELP},
         "replace": {"type": "boolean", "description": "Drop the current queue first. Default false."}}}},
    {"name": "events",
     "description": "What has happened since you last asked: job results, alerts, chat from Chris and finished "
                    "research. With wait_seconds it holds until something arrives, which is how to wait for a "
                    "job without polling. The first call returns the most recent lines.",
     "inputSchema": {"type": "object", "properties": {
         "wait_seconds": {"type": "number", "description": "Wait up to this long for a new event (0 to 50). Default 0."},
         "kinds": {"type": "array", "items": {"type": "string"},
                   "description": "Only these kinds: agent, alert, chat, research, task, session, error."},
         "limit": {"type": "integer", "description": "Most events to return, newest kept. Default 50."}}}},
    {"name": "say",
     "description": "Speaks in game chat as Claude. Use [gps=x,y] to pin a place on the map.",
     "inputSchema": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}},
    {"name": "call",
     "description": "Runs any mod command. Looking: state, map, scan, resources, area_status, power, production, "
                    "inventory, ghosts, offshore_spots. Planning: place, tiles, check, fit, remove_ghosts, "
                    "deconstruct, clear_under_ghosts, cancel_deconstruct, set_recipe, upgrade, chest_limit, mark, "
                    "clear_marks. Research: research, research_triggers. Alerts: watch. Task board: tasks_set, "
                    "tasks_done, tasks_get. Character: agent_spawn, agent_stop, agent_bots, agent_credit, "
                    "agent_unstick. `guide` says what each is for.",
     "inputSchema": {"type": "object", "required": ["command"], "properties": {
         "command": {"type": "string"},
         "args": {"type": "object", "description": "The command's arguments. Default {}."},
         "timeout": {"type": "number", "description": "Seconds to wait for the reply. Default 15."}}}},
    {"name": "run_script",
     "description": "Runs a Python script from the repo's tools/ folder on the gaming PC and returns its output. "
                    "For build templates and blueprints: script 'cc.py' with args like "
                    "['build', 'smelter_column', '--at', '10,-20', '--dry'], or a script under builds/.",
     "inputSchema": {"type": "object", "required": ["script"], "properties": {
         "script": {"type": "string", "description": "Path under tools/, e.g. cc.py or builds/mall.py"},
         "args": {"type": "array", "items": {"type": "string"}},
         "timeout": {"type": "number", "description": "Seconds. Default 120."}}}},
]


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, file=sys.stderr, flush=True)


class Events:
    """Reads new lines from the game's chat file, remembering where it got to."""

    def __init__(self):
        self.pos = None

    def _start(self, size):
        # first read: begin about 6 KB back, so the caller sees recent history
        back = max(0, size - 6000)
        if back == 0:
            return 0
        with open(cc.CHAT_FILE, "rb") as f:
            f.seek(back)
            return back + f.read(6000).find(b"\n") + 1

    def read(self):
        if not os.path.isfile(cc.CHAT_FILE):
            return []
        size = os.path.getsize(cc.CHAT_FILE)
        if self.pos is None:
            self.pos = self._start(size)
        if size < self.pos:  # the file was replaced (a new game): start over
            self.pos = 0
        if size == self.pos:
            return []
        with open(cc.CHAT_FILE, "rb") as f:
            f.seek(self.pos)
            data = f.read()
        cut = data.rfind(b"\n") + 1  # whole lines only
        self.pos += cut
        out = []
        for line in data[:cut].decode("utf-8", errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

    def take(self, wait_seconds=0, kinds=None, limit=50):
        deadline = time.time() + max(0.0, min(float(wait_seconds or 0), 50.0))
        found = []
        while True:
            found += [r for r in self.read() if not kinds or r.get("kind") in kinds]
            if found or time.time() >= deadline:
                return found[-int(limit or 50):]
            time.sleep(0.25)


EVENTS = Events()


def resolve_script(name):
    path = os.path.realpath(os.path.join(TOOLS, name))
    if not path.startswith(os.path.realpath(TOOLS) + os.sep) or not path.endswith(".py"):
        raise ValueError(f"script must be a .py file under tools/: {name}")
    if not os.path.isfile(path):
        raise ValueError(f"no such script: {name}")
    return path


def run_tool(name, a):
    if name == "guide":
        with open(GUIDE, encoding="utf-8") as f:
            return f.read()
    if name == "ping":
        return cc.call("ping", {}, timeout=5)
    if name == "agent_status":
        return cc.call("agent_status", {})
    if name == "agent_jobs":
        return cc.call("agent_jobs", {"jobs": a["jobs"], "replace": bool(a.get("replace"))})
    if name == "events":
        events = EVENTS.take(a.get("wait_seconds"), a.get("kinds"), a.get("limit"))
        return {"events": events, "count": len(events)}
    if name == "say":
        return cc.call("say", {"text": a["text"]})
    if name == "call":
        return cc.call(a["command"], a.get("args") or {}, timeout=float(a.get("timeout") or 15))
    if name == "run_script":
        script = resolve_script(a["script"])
        proc = subprocess.run([sys.executable, script] + [str(x) for x in a.get("args") or []],
                              cwd=REPO, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=float(a.get("timeout") or 120),
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        text = proc.stdout + (("\n[stderr]\n" + proc.stderr) if proc.stderr.strip() else "")
        if proc.returncode != 0:
            raise RuntimeError(f"exit code {proc.returncode}\n{text}")
        return text or "(no output)"
    raise ValueError(f"unknown tool: {name}")


def handle(msg):
    """Returns the result for a request, or None for a notification."""
    method, params = msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        asked = params.get("protocolVersion")
        return {"protocolVersion": asked if asked in SUPPORTED else PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "factorio-claude-companion", "version": "1.0.0"},
                "instructions": INSTRUCTIONS}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOL_DEFS}
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        try:
            result = run_tool(name, args)
            text = result if isinstance(result, str) else json.dumps(result, indent=1)
            return {"content": [{"type": "text", "text": text}], "isError": False}
        except Exception as err:  # the model should see the failure and adjust
            log(f"{name} failed: {err}")
            return {"content": [{"type": "text", "text": f"{type(err).__name__}: {err}"}], "isError": True}
    if method in ("resources/list", "prompts/list"):
        return {method.split("/")[0]: []}
    raise LookupError(method)


def main():
    log(f"factorio MCP server up; game port {cc.GAME_PORT}; chat file {cc.CHAT_FILE}")
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except ValueError:
            continue
        if "id" not in msg:  # a notification: nothing to answer
            continue
        reply = {"jsonrpc": "2.0", "id": msg["id"]}
        try:
            reply["result"] = handle(msg)
        except LookupError as err:
            reply["error"] = {"code": -32601, "message": f"method not found: {err}"}
        except Exception as err:
            reply["error"] = {"code": -32603, "message": f"{type(err).__name__}: {err}"}
        stdout.write(json.dumps(reply, separators=(",", ":")).encode("utf-8") + b"\n")
        stdout.flush()


if __name__ == "__main__":
    main()
