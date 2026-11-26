#!/usr/bin/env python3
"""File relay so Claude can drive the game from a sandbox that can't reach localhost.

Run this on the gaming PC (same machine as Factorio) and leave it open:

    python tools/relay.py

Claude writes request files into .relay/in/, this relay runs each one against
the game, and writes the reply to .relay/out/. It also mirrors the game's chat
file into .relay/chat.jsonl so Claude can read chat without APPDATA access.

Request formats (one JSON object per file):
    {"call": "ping", "args": {}, "timeout": 10}          raw mod command via cc.call
    {"run": ["cc.py", "map", "--at", "0,0"], "timeout": 120}
        runs a Python script under tools/ (subfolders allowed) with those args
"""
import json
import os
import subprocess
import sys
import time
import traceback

TOOLS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TOOLS)
RELAY = os.path.join(REPO, ".relay")
IN_DIR = os.path.join(RELAY, "in")
OUT_DIR = os.path.join(RELAY, "out")
CHAT_MIRROR = os.path.join(RELAY, "chat.jsonl")
HEARTBEAT = os.path.join(RELAY, "relay.alive")

sys.path.insert(0, TOOLS)
import cc  # noqa: E402


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def resolve_script(name):
    path = os.path.realpath(os.path.join(TOOLS, name))
    if not path.startswith(os.path.realpath(TOOLS) + os.sep) or not path.endswith(".py"):
        raise ValueError(f"script must be a .py file under tools/: {name}")
    if not os.path.isfile(path):
        raise ValueError(f"no such script: {name}")
    return path


def handle(req):
    if "call" in req:
        result = cc.call(req["call"], req.get("args") or {}, timeout=float(req.get("timeout", 10)))
        return {"ok": True, "result": result}
    if "run" in req:
        argv = list(req["run"])
        script = resolve_script(argv[0])
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.run([sys.executable, script] + [str(a) for a in argv[1:]],
                              cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=float(req.get("timeout", 120)), env=env)
        return {"ok": proc.returncode == 0, "returncode": proc.returncode,
                "stdout": proc.stdout, "stderr": proc.stderr}
    raise ValueError("request needs 'call' or 'run'")


class ChatMirror:
    def __init__(self):
        self.pos = 0
        self.size_seen = -1

    def pump(self):
        src = cc.CHAT_FILE
        if not os.path.isfile(src):
            return
        size = os.path.getsize(src)
        if size < self.pos:  # truncated or replaced: start over
            self.pos = 0
        if size == self.pos:
            return
        with open(src, "rb") as f:
            f.seek(self.pos)
            data = f.read()
        cut = data.rfind(b"\n") + 1  # only whole lines
        if cut == 0:
            return
        with open(CHAT_MIRROR, "ab") as out:
            out.write(data[:cut])
        self.pos += cut


def main():
    os.makedirs(IN_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    chat = ChatMirror()
    # Mirror only chat from now on unless asked for history.
    if "--history" not in sys.argv and os.path.isfile(cc.CHAT_FILE):
        chat.pos = os.path.getsize(cc.CHAT_FILE)
    log(f"relay up. watching {IN_DIR}")
    log(f"chat file: {cc.CHAT_FILE}")
    last_beat = 0
    while True:
        try:
            chat.pump()
        except Exception as err:
            log(f"chat mirror error: {err}")
        now = time.time()
        if now - last_beat > 5:
            write_json(HEARTBEAT, {"t": now})
            last_beat = now
        names = sorted(n for n in os.listdir(IN_DIR) if n.endswith(".json"))
        for name in names:
            path = os.path.join(IN_DIR, name)
            try:
                with open(path, encoding="utf-8") as f:
                    req = json.load(f)
            except (OSError, ValueError):
                continue  # still being written; try next pass
            try:
                os.remove(path)
            except OSError:
                pass
            label = req.get("call") or " ".join(map(str, req.get("run", [])))[:120]
            log(f"> {label}")
            try:
                reply = handle(req)
            except Exception as err:
                reply = {"ok": False, "error": f"{type(err).__name__}: {err}",
                         "trace": traceback.format_exc()[-2000:]}
            log(f"< {'ok' if reply.get('ok') else 'FAIL ' + str(reply.get('error') or reply.get('returncode'))}")
            write_json(os.path.join(OUT_DIR, name), reply)
        time.sleep(0.2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("relay stopped")
