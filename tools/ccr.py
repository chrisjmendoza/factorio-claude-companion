#!/usr/bin/env python3
"""Client side of tools/relay.py, for a sandbox that can only touch files.

    python3 tools/ccr.py cc.py ping            run a tools/ script on the PC
    python3 tools/ccr.py builds/mall.py --dry
    python3 tools/ccr.py --call state '{}'     raw mod command
    python3 tools/ccr.py --chat 20             last chat lines (mirrored)
    python3 tools/ccr.py --status              is the relay running?
"""
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELAY = os.path.join(REPO, ".relay")


def relay_alive():
    try:
        with open(os.path.join(RELAY, "relay.alive")) as f:
            return time.time() - json.load(f)["t"] < 20
    except (OSError, ValueError, KeyError):
        return False


def send(req, timeout):
    if not relay_alive():
        sys.exit("relay is not running: start `python tools/relay.py` on the PC")
    name = f"{int(time.time() * 1000)}-{os.getpid()}.json"
    os.makedirs(os.path.join(RELAY, "in"), exist_ok=True)
    tmp = os.path.join(RELAY, "in", name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(req, f)
    os.replace(tmp, os.path.join(RELAY, "in", name))
    out = os.path.join(RELAY, "out", name)
    deadline = time.time() + timeout + 15
    while time.time() < deadline:
        if os.path.exists(out):
            time.sleep(0.05)
            with open(out, encoding="utf-8") as f:
                return json.load(f)
        time.sleep(0.2)
    sys.exit(f"no reply within {timeout + 15}s")


def main():
    args = sys.argv[1:]
    timeout = 120
    if args and args[0].startswith("--timeout="):
        timeout = float(args.pop(0).split("=", 1)[1])
    if not args or args[0] == "--status":
        print("relay running" if relay_alive() else "relay NOT running")
        return
    if args[0] == "--chat":
        n = int(args[1]) if len(args) > 1 else 20
        try:
            with open(os.path.join(RELAY, "chat.jsonl"), encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            lines = []
        sys.stdout.write("".join(lines[-n:]))
        return
    if args[0] == "--call":
        req = {"call": args[1], "args": json.loads(args[2]) if len(args) > 2 else {}, "timeout": min(timeout, 60)}
        rep = send(req, timeout)
        print(json.dumps(rep.get("result") if rep.get("ok") else rep, indent=1))
        sys.exit(0 if rep.get("ok") else 1)
    rep = send({"run": args, "timeout": timeout}, timeout)
    if "stdout" in rep:
        sys.stdout.write(rep["stdout"])
        sys.stderr.write(rep["stderr"])
        sys.exit(rep["returncode"])
    sys.exit(rep.get("error", "relay error"))


if __name__ == "__main__":
    main()
