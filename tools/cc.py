#!/usr/bin/env python3
"""Claude Companion bridge: talk to a running Factorio over Lua UDP.

The game must be started with --enable-lua-udp <port> (default 34198) and
have the ClaudeCompanion mod enabled. Chat from the game lands in
%APPDATA%/Factorio/script-output/claude-companion/chat.jsonl.

    python cc.py ping
    python cc.py say "On it."
    python cc.py map --at 0,0 --r 30
    python cc.py call resources '{"radius": 200}'
    python cc.py build smelter_column --at 10,-20 --param rows=6 --dry
    python cc.py steam --near 0,0 --boilers 2
    python cc.py chat --tail 20
"""
import argparse
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layouts  # noqa: E402

GAME_PORT = int(os.environ.get("CC_PORT", "34198"))
WRITE_DIR = os.environ.get("CC_WRITE_DIR", os.path.join(os.environ.get("APPDATA", ""), "Factorio"))
CHAT_FILE = os.path.join(WRITE_DIR, "script-output", "claude-companion", "chat.jsonl")
MAX_REQUEST = 60000


class CompanionError(Exception):
    pass


def call(cmd, args=None, timeout=10.0, port=None):
    """Sends one command and waits for its reply."""
    port = port or GAME_PORT
    rid = int(time.time() * 1000) % 1_000_000_000
    payload = json.dumps({"id": rid, "cmd": cmd, "args": args or {}}, separators=(",", ":"))
    if len(payload) > MAX_REQUEST:
        raise CompanionError(f"request is {len(payload)} bytes; split it (limit {MAX_REQUEST})")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.5)
    try:
        sock.sendto(payload.encode("utf-8"), ("127.0.0.1", port))
        chunks, deadline = {}, time.time() + timeout
        while time.time() < deadline:
            try:
                data, _ = sock.recvfrom(70000)
            except socket.timeout:
                continue
            except ConnectionResetError:
                # Windows reports an ICMP "port unreachable" this way.
                raise CompanionError(f"nothing is listening on UDP {port}: is Factorio running with "
                                     f"--enable-lua-udp {port} and the mod enabled?")
            text = data.decode("utf-8")
            if text.startswith("CHUNK "):
                header, piece = text.split("\n", 1)
                _, cid, i, n = header.split()
                if int(cid) != rid:
                    continue
                chunks[int(i)] = piece
                if len(chunks) < int(n):
                    continue
                text = "".join(chunks[k] for k in range(1, int(n) + 1))
            msg = json.loads(text)
            if msg.get("id") != rid:
                continue
            if not msg.get("ok"):
                raise CompanionError(msg.get("error", "unknown error"))
            return msg.get("result")
        raise CompanionError(f"no reply to '{cmd}' within {timeout}s: is the game paused or still loading?")
    finally:
        sock.close()


# Factorio's Lua UDP socket starts with a small receive buffer and only grows
# it (the log says "Increasing size of socket buffer to 8192") after a bigger
# datagram arrives, and that datagram is dropped. Batches are capped well under
# the 4 KB starting size so the first big request of a session isn't lost.
BATCH_BYTES = 3000


def call_batched(cmd, entities, extra=None, batch_bytes=BATCH_BYTES, **kw):
    """Runs a command over a long entity list in several packets, merging replies."""
    batches, current, size = [], [], 0
    for spec in entities:
        n = len(json.dumps(spec, separators=(",", ":"))) + 1
        if current and size + n > batch_bytes:
            batches.append(current)
            current, size = [], 0
        current.append(spec)
        size += n
    if current:
        batches.append(current)
    merged = {}
    for chunk in batches:
        args = dict(extra or {})
        args["entities"] = chunk
        part = call(cmd, args, **kw)
        for key, value in part.items():
            # Lua's JSON writes an empty table as {}, so an empty list can
            # arrive as a dict: treat empties as "nothing to merge".
            if isinstance(value, (dict, list)) and not value:
                merged.setdefault(key, value)
                continue
            if isinstance(value, list) and isinstance(merged.get(key), dict) and not merged[key]:
                merged[key] = []
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                merged[key] = merged.get(key, 0) + value
            elif isinstance(value, list):
                merged.setdefault(key, []).extend(value)
            elif isinstance(value, dict):
                bucket = merged.setdefault(key, {})
                for k, v in value.items():
                    bucket[k] = bucket.get(k, 0) + v
            else:
                merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# output helpers

def xy(text):
    x, y = text.split(",")
    return float(x), float(y)


def parse_params(pairs):
    out = {}
    for pair in pairs or []:
        key, value = pair.split("=", 1)
        for cast in (int, float):
            try:
                value = cast(value)
                break
            except ValueError:
                pass
        if value in ("true", "false"):
            value = value == "true"
        out[key] = value
    return out


def print_map(result):
    x0, y0, rows = result["origin"]["x"], result["origin"]["y"], result["rows"]
    width = result["width"]
    # Column ruler: a tick every 10 tiles, labelled with the world x.
    marks = [" "] * width
    for col in range(width):
        if (x0 + col) % 10 == 0:
            label = str(x0 + col)
            for k, ch in enumerate(label):
                if col + k < width:
                    marks[col + k] = ch
    print(f"{'':>6} " + "".join(marks))
    for i, row in enumerate(rows):
        y = y0 + i
        print(f"{y:>6} {row}")
    print(result["legend"])


def show(value):
    print(json.dumps(value, indent=1, sort_keys=True))


# ---------------------------------------------------------------------------
# planners

def steam(near, radius, boilers, engines, pipes, place, tag, fuel_belt, dual=0):
    """Finds a shore where a whole steam plant fits, nearest first.

    With dual=N it fits the dual-sided plant (layouts.steam_dual) at N units.
    """
    spots = call("offshore_spots", {"center": list(near), "radius": radius, "limit": 12})["spots"]
    if not spots:
        raise CompanionError("no shoreline for an offshore pump within range")
    if dual:
        template = layouts.steam_dual(units=dual)
    else:
        template = layouts.steam_power(boilers=boilers, engines=engines, pipes=pipes, fuel_belt=fuel_belt)
    anchors = []
    for spot in spots:
        rot = layouts.rot_for((spot["outward"]["x"], spot["outward"]["y"]))
        for mirror in (False, True):
            base = layouts.transform({"x": 0.5, "y": 0.5}, {"rot": rot, "mirror": mirror})
            anchors.append({"x": spot["output"]["x"] - base["x"], "y": spot["output"]["y"] - base["y"],
                            "rot": rot, "mirror": mirror})
    fit = call("fit", {"template": template, "anchors": anchors})
    if not fit["fits"]:
        raise CompanionError(f"no shore spot fits {boilers} boiler(s); closest: {fit['best']}")
    anchor = fit["anchor"]
    print(f"fits at anchor {anchor} (trees/rocks to clear: {fit['to_clear']})")
    if place:
        show(call("place", {"template": template, "anchor": anchor, "tag": tag}))
    return anchor


def bp_decode(text):
    import base64, zlib
    text = text.strip()
    return json.loads(zlib.decompress(base64.b64decode(text[1:])))


def bp_encode(obj):
    import base64, zlib
    raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    return "0" + base64.b64encode(zlib.compress(raw, 9)).decode("ascii")


def bp_walk(obj, path=()):
    """Yields (label path, blueprint dict) for every blueprint in a string's JSON."""
    if "blueprint" in obj:
        bp = obj["blueprint"]
        yield " / ".join(path + (bp.get("label", "?"),)), bp
    elif "blueprint_book" in obj:
        book = obj["blueprint_book"]
        here = path + (book.get("label", "?"),)
        for child in book.get("blueprints", []):
            yield from bp_walk(child, here)


def bp_bbox(bp):
    xs = [e["position"]["x"] for e in bp.get("entities", [])] or [0]
    ys = [e["position"]["y"] for e in bp.get("entities", [])] or [0]
    return min(xs), min(ys), max(xs), max(ys)


def blueprint(path, select, at, direction, mode):
    """--list prints the blueprints in a file; --outline draws the footprint a
    paste at `at` would cover; otherwise uploads and pastes the one blueprint
    whose label path contains every word of `select`."""
    with open(path, encoding="utf-8") as handle:
        root = bp_decode(handle.read())
    found = list(bp_walk(root))
    if mode == "list":
        for label, bp in found:
            x1, y1, x2, y2 = bp_bbox(bp)
            print(f"{len(bp.get('entities', [])):5d} ents  {x2 - x1 + 1:4.0f}x{y2 - y1 + 1:<4.0f} {label}")
        return
    words = [w.lower() for w in (select or "").split()]
    hits = [(label, bp) for label, bp in found if all(w in label.lower() for w in words)]
    if len(hits) != 1:
        names = "\n  ".join(label for label, _ in hits[:20]) or "(none)"
        raise CompanionError(f"--select must match exactly one blueprint; it matched {len(hits)}:\n  {names}")
    label, bp = hits[0]
    x1, y1, x2, y2 = bp_bbox(bp)
    w, h = x2 - x1 + 1, y2 - y1 + 1
    print(f"{label}: {len(bp.get('entities', []))} entities, about {w:.0f}x{h:.0f}")
    if mode == "outline":
        # build_blueprint centres the print on the position; this is approximate
        area = [[at[0] - w / 2, at[1] - h / 2], [at[0] + w / 2, at[1] + h / 2]]
        show(call("mark", {"area": area, "text": bp.get("label", "blueprint"), "seconds": 600}))
        return
    text = bp_encode({"blueprint": bp})
    piece = 2400
    parts = [text[i:i + piece] for i in range(0, len(text), piece)]
    uid = f"bp{int(time.time())}"
    for i, part in enumerate(parts, 1):
        call("bp_part", {"id": uid, "i": i, "n": len(parts), "data": part})
    print(f"uploaded {len(text)} chars in {len(parts)} parts")
    show(call("bp_build", {"id": uid, "position": list(at), "direction": direction}, timeout=30))


def build(layout, at, rot, mirror, params, dry, tag, partial, instant):
    fn = layouts.LAYOUTS[layout]
    if mirror and not getattr(fn, "mirrorable", True):
        raise CompanionError(f"{layout} does not work mirrored; rotate it instead")
    template = fn(**params)
    anchor = {"x": at[0], "y": at[1], "rot": rot, "mirror": mirror}
    specs = [layouts.transform(s, anchor) for s in template]
    extra = {"tag": tag, "partial": partial}
    if instant:
        extra["instant"] = True
    return call_batched("check" if dry else "place", specs, extra)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=10.0)
    sub = ap.add_subparsers(dest="what", required=True)

    p = sub.add_parser("call", help="run any mod command with JSON args")
    p.add_argument("cmd")
    p.add_argument("args", nargs="?", default="{}", help="JSON object, or @file.json")

    sub.add_parser("ping")
    sub.add_parser("state")
    sub.add_parser("inv")
    sub.add_parser("ghosts")

    p = sub.add_parser("lua", help="run a Lua file in the game (needs the cheats setting)")
    p.add_argument("file")

    p = sub.add_parser("say")
    p.add_argument("text", nargs="+")

    p = sub.add_parser("map")
    p.add_argument("--at", type=xy, default=None, help="centre x,y (default: the player)")
    p.add_argument("--r", type=int, default=30)

    p = sub.add_parser("chat", help="print recent lines from the game's chat file")
    p.add_argument("--tail", type=int, default=20)

    p = sub.add_parser("build", help="place a template from layouts.py")
    p.add_argument("layout", choices=sorted(layouts.LAYOUTS))
    p.add_argument("--at", type=xy, required=True, help="world x,y of local (0, 0)")
    p.add_argument("--rot", type=int, default=0)
    p.add_argument("--mirror", action="store_true")
    p.add_argument("--param", action="append", help="layout argument as key=value")
    p.add_argument("--dry", action="store_true", help="only check; place nothing")
    p.add_argument("--partial", action="store_true", help="place what fits even if some is blocked")
    p.add_argument("--instant", action="store_true", help="real entities (needs the cheats setting)")
    p.add_argument("--tag", default=None)

    p = sub.add_parser("blueprint", help="list, outline or paste a blueprint from a string file")
    p.add_argument("file", help="text file holding a blueprint or book string")
    p.add_argument("--select", default=None, help="words that pick one blueprint out of a book")
    p.add_argument("--at", type=xy, default=(0, 0), help="centre of the paste")
    p.add_argument("--dir", type=int, default=0, help="0 north, 4 east, 8 south, 12 west")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--list", action="store_true")
    g.add_argument("--outline", action="store_true")

    p = sub.add_parser("steam", help="find a shore and place a steam plant")
    p.add_argument("--near", type=xy, default=(0, 0))
    p.add_argument("--radius", type=int, default=120)
    p.add_argument("--boilers", type=int, default=1)
    p.add_argument("--engines", type=int, default=2)
    p.add_argument("--pipes", type=int, default=1)
    p.add_argument("--fuel-belt", action="store_true")
    p.add_argument("--dual", type=int, default=0, metavar="UNITS",
                   help="dual-sided plant with this many units (2 boilers + 4 engines each)")
    p.add_argument("--dry", action="store_true")
    p.add_argument("--tag", default="power")

    a = ap.parse_args()
    if a.port:
        global GAME_PORT
        GAME_PORT = a.port
    kw = {"timeout": a.timeout}

    try:
        if a.what == "call":
            raw = a.args
            if raw.startswith("@"):
                raw = open(raw[1:], encoding="utf-8").read()
            result = call(a.cmd, json.loads(raw), **kw)
            if a.cmd == "map":
                print_map(result)
            else:
                show(result)
        elif a.what in ("ping", "state", "ghosts"):
            show(call(a.what, {}, **kw))
        elif a.what == "inv":
            show(call("inventory", {}, **kw))
        elif a.what == "lua":
            with open(a.file, encoding="utf-8") as handle:
                print(call("lua", {"code": handle.read()}, **kw)["value"])
        elif a.what == "say":
            call("say", {"text": " ".join(a.text)}, **kw)
        elif a.what == "map":
            args = {"radius": a.r}
            if a.at:
                args["center"] = list(a.at)
            print_map(call("map", args, **kw))
        elif a.what == "chat":
            if not os.path.exists(CHAT_FILE):
                print(f"(no chat yet: {CHAT_FILE})")
                return
            with open(CHAT_FILE, encoding="utf-8") as handle:
                for line in handle.readlines()[-a.tail:]:
                    print(line.rstrip())
        elif a.what == "build":
            show(build(a.layout, a.at, a.rot, a.mirror, parse_params(a.param), a.dry, a.tag, a.partial, a.instant))
        elif a.what == "blueprint":
            mode = "list" if a.list else "outline" if a.outline else "paste"
            blueprint(a.file, a.select, a.at, a.dir, mode)
        elif a.what == "steam":
            steam(a.near, a.radius, a.boilers, a.engines, a.pipes, not a.dry, a.tag, a.fuel_belt, a.dual)
    except CompanionError as err:
        print(f"error: {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
