#!/usr/bin/env python3
"""Headless check of agent jobs against a throwaway map, isolated from the
player's game: its own write-data folder and mod folder under .relay/headless.

    python tools/headless_test.py [--keep]
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

TOOLS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import cc  # noqa: E402

PORT = 34598
SEED = "424242"   # fixed, so every run gets the same map
WORK = os.path.join(REPO, ".relay", "headless")


def find_factorio():
    cands = [os.environ.get("FACTORIO_EXE", "")]
    steam_roots = [r"C:\Games\Steam", r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    libs = set(steam_roots)
    for root in steam_roots:
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        if os.path.isfile(vdf):
            for m in re.finditer(r'"path"\s+"([^"]+)"', open(vdf, encoding="utf-8", errors="replace").read()):
                libs.add(m.group(1).replace("\\\\", "\\"))
    for lib in libs:
        cands.append(os.path.join(lib, "steamapps", "common", "Factorio", "bin", "x64", "factorio.exe"))
    cands += glob.glob(r"?:\SteamLibrary\steamapps\common\Factorio\bin\x64\factorio.exe")
    cands += [r"C:\Program Files\Factorio\bin\x64\factorio.exe"]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    raise SystemExit("factorio.exe not found; set FACTORIO_EXE")


def setup(exe):
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    mods = os.path.join(WORK, "mods")
    os.makedirs(mods)
    info = json.load(open(os.path.join(REPO, "info.json"), encoding="utf-8"))
    dst = os.path.join(mods, f"ClaudeCompanion_{info['version']}")
    os.makedirs(dst)
    for name in ["info.json", "control.lua", "settings.lua", "changelog.txt"]:
        shutil.copy(os.path.join(REPO, name), dst)
    shutil.copytree(os.path.join(REPO, "locale"), os.path.join(dst, "locale"))
    with open(os.path.join(mods, "mod-list.json"), "w") as f:
        json.dump({"mods": [{"name": "base", "enabled": True}, {"name": "ClaudeCompanion", "enabled": True},
                            {"name": "space-age", "enabled": False}, {"name": "quality", "enabled": False},
                            {"name": "elevated-rails", "enabled": False}]}, f)
    data = os.path.normpath(os.path.join(os.path.dirname(exe), "..", "..", "data"))
    cfg = os.path.join(WORK, "config.ini")
    with open(cfg, "w") as f:
        f.write(f"[path]\nread-data={data}\nwrite-data={WORK}\n")
    return cfg, mods


def run(exe, cfg, mods, *args, **kw):
    return subprocess.Popen([exe, "-c", cfg, "--mod-directory", mods] + list(args),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kw)


def wait_ping(proc, secs=90):
    t0 = time.time()
    while time.time() - t0 < secs:
        if proc.poll() is not None:
            raise SystemExit("server exited:\n" + proc.stdout.read()[-3000:])
        try:
            return cc.call("ping", {}, timeout=2, port=PORT)
        except Exception:
            time.sleep(1)
    raise SystemExit("server never answered")


def agent_wait(secs, port=PORT):
    t0 = time.time()
    while time.time() - t0 < secs:
        st = cc.call("agent_status", {}, port=port)
        if not st.get("queued"):
            return st
        time.sleep(0.25)
    return cc.call("agent_status", {}, port=port)


def last_report(job):
    """The agent's most recent report for a job type, from the headless chat file."""
    path = os.path.join(WORK, "script-output", "claude-companion", "chat.jsonl")
    found = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("kind") == "agent" and rec.get("job") == job:
                found = rec
    return found


def chat_records(kind):
    """Every record of one kind from the headless chat file."""
    path = os.path.join(WORK, "script-output", "claude-companion", "chat.jsonl")
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("kind") == kind:
                out.append(rec)
    return out


def main():
    exe = find_factorio()
    print("factorio:", exe)
    cfg, mods = setup(exe)
    save = os.path.join(WORK, "test.zip")
    p = run(exe, cfg, mods, "--create", save, "--map-gen-seed", SEED)
    out, _ = p.communicate(timeout=120)
    if not os.path.isfile(save):
        raise SystemExit("map create failed:\n" + out[-3000:])
    ss = os.path.join(WORK, "server-settings.json")
    with open(ss, "w") as f:
        data = os.path.normpath(os.path.join(os.path.dirname(exe), "..", "..", "data"))
        base = json.load(open(os.path.join(data, "server-settings.example.json"), encoding="utf-8"))
        base.update({"name": "cc-headless", "auto_pause": False, "visibility": {"public": False, "lan": False},
                     "require_user_verification": False})
        json.dump(base, f)
    srv = run(exe, cfg, mods, "--start-server", save, "--enable-lua-udp", str(PORT),
              "--server-settings", ss, "--port", "34297")
    results = {}
    try:
        print("ping:", wait_ping(srv))
        res = cc.call("resources", {"radius": 200}, port=PORT)["patches"]
        by = {r["name"]: r for r in res}
        print("patches:", {k: (round(v["cx"]), round(v["cy"])) for k, v in by.items()})
        ore = by.get("iron-ore") or res[0]
        spot = [ore["cx"], ore["cy"]]
        print("spawn:", cc.call("agent_spawn", {"position": spot}, port=PORT))

        # 1) mine 6 ore: at 0.5 speed and 1 s mining time that's 12 s of game time
        t0 = cc.call("ping", {}, port=PORT)["tick"]
        cc.call("agent_jobs", {"jobs": [{"type": "mine", "name": ore["name"], "at": spot, "count": 6}]}, port=PORT)
        st = agent_wait(60)
        t1 = cc.call("ping", {}, port=PORT)["tick"]
        got = st["inventory"].get(ore["name"], 0)
        results["mine_ore"] = got == 6
        print(f"mine ore: got {got} in {(t1 - t0) / 60:.1f}s game time (expect ~12s plus walking)")

        # 2) trees and rocks
        cc.call("agent_jobs", {"jobs": [{"type": "mine", "kind": "tree", "radius": 60, "count": 4},
                                        {"type": "mine", "kind": "rock", "radius": 80, "count": 1}]}, port=PORT)
        st = agent_wait(90)
        inv = st["inventory"]
        results["mine_tree"] = inv.get("wood", 0) >= 4
        results["mine_rock"] = inv.get("stone", 0) > 0 or inv.get("coal", 0) > 0
        print("after trees/rocks:", inv)

        # 3) craft with missing ingredients fails cleanly; wait for crafting
        cc.call("agent_jobs", {"jobs": [{"type": "craft", "recipe": "iron-gear-wheel", "count": 1},
                                        {"type": "craft", "recipe": "wooden-chest", "count": 1},
                                        {"type": "wait", "craft": True}]}, port=PORT)
        st = agent_wait(30)
        results["craft_wait"] = st["inventory"].get("wooden-chest", 0) == 1 and st.get("crafting", 0) == 0
        print("after craft:", st["inventory"], "crafting", st.get("crafting"))

        # 4) place a chest ghost, build it, then mine it back up
        pos = st["position"]
        gx, gy = round(pos["x"]) + 2.5, round(pos["y"]) + 0.5
        print("place:", cc.call("place", {"entities": [{"name": "wooden-chest", "position": [gx, gy]}]}, port=PORT))
        cc.call("agent_jobs", {"jobs": [{"type": "build", "area": [[gx - 1, gy - 1], [gx + 1, gy + 1]]},
                                        {"type": "mine", "kind": "entity", "name": "wooden-chest", "at": [gx, gy], "radius": 2}]},
                port=PORT)
        st = agent_wait(30)
        results["build_and_pickup_entity"] = st["inventory"].get("wooden-chest", 0) == 1
        print("after build+mine entity:", st["inventory"])

        # 4b) an unnamed entity job must refuse, leaving our buildings alone
        print("place:", cc.call("place", {"entities": [{"name": "wooden-chest", "position": [gx, gy]}]}, port=PORT))
        cc.call("agent_jobs", {"jobs": [{"type": "build", "area": [[gx - 1, gy - 1], [gx + 1, gy + 1]]},
                                        {"type": "mine", "kind": "entity", "at": [gx, gy], "radius": 2}]}, port=PORT)
        st = agent_wait(30)
        results["unnamed_entity_refused"] = st["inventory"].get("wooden-chest", 0) == 0
        cc.call("agent_jobs", {"jobs": [{"type": "mine", "kind": "entity", "name": "wooden-chest", "at": [gx, gy], "radius": 2}]},
                port=PORT)
        st = agent_wait(30)
        results["named_entity_still_works"] = st["inventory"].get("wooden-chest", 0) == 1

        # 4c) ore that needs a fluid (uranium) can't be hand-mined; skipped if the map has none nearby
        far = {r["name"]: r for r in cc.call("resources", {"radius": 600}, timeout=60, port=PORT)["patches"]}
        ur = far.get("uranium-ore")
        if ur:
            cc.call("agent_jobs", {"jobs": [{"type": "mine", "name": "uranium-ore", "at": [ur["cx"], ur["cy"]], "count": 1}]},
                    port=PORT)
            st = agent_wait(30)
            results["uranium_refused"] = st["inventory"].get("uranium-ore", 0) == 0 and not st.get("queued")
            print("uranium at", round(ur["cx"]), round(ur["cy"]), "->", results["uranium_refused"])
        else:
            print("no uranium within 600: fluid check not exercised")

        # 4d) smelt in a furnace and take the plates back out (take must see the output slot)
        cc.call("agent_jobs", {"jobs": [{"type": "mine", "name": ore["name"], "at": spot, "count": 6},
                                        {"type": "mine", "kind": "tree", "radius": 80, "count": 4},
                                        {"type": "craft", "recipe": "stone-furnace", "count": 1},
                                        {"type": "wait", "craft": True}]}, port=PORT)
        st = agent_wait(150)
        pos = st["position"]
        placed = None
        for dx, dy in [(4, 0), (-4, 0), (0, 4), (0, -4), (6, 6), (-6, -6)]:
            fx, fy = round(pos["x"]) + dx, round(pos["y"]) + dy
            placed = cc.call("place", {"entities": [{"name": "stone-furnace", "position": [fx, fy]}]}, port=PORT)
            if placed.get("placed"):
                break
        print("place furnace:", placed)
        cc.call("agent_jobs", {"jobs": [{"type": "build", "area": [[fx - 2, fy - 2], [fx + 2, fy + 2]]},
                                        {"type": "put", "to": [fx, fy], "item": "wood"},
                                        {"type": "put", "to": [fx, fy], "item": "iron-ore"},
                                        {"type": "wait", "ticks": 2500},
                                        {"type": "take", "from": [fx, fy], "item": "iron-plate"},
                                        {"type": "put", "to": [fx, fy], "item": "stone", "count": 4},
                                        {"type": "wait", "ticks": 500},
                                        {"type": "take", "from": [fx, fy], "item": "stone-brick"}]}, port=PORT)
        st = agent_wait(120)
        results["take_from_furnace"] = st["inventory"].get("iron-plate", 0) >= 9
        print("after smelt+take:", st["inventory"])

        # 4e) rotate a building, and feed a belt by hand
        cc.call("agent_jobs", {"jobs": [{"type": "craft", "recipe": "burner-inserter", "count": 1},
                                        {"type": "craft", "recipe": "transport-belt", "count": 1},
                                        {"type": "wait", "craft": True}]}, port=PORT)
        st = agent_wait(30)
        ix, iy = fx + 0.5, fy + 3.5
        bx, by_ = fx + 2.5, fy + 3.5
        print("place:", cc.call("place", {"entities": [{"name": "burner-inserter", "position": [ix, iy]},
                                                       {"name": "transport-belt", "position": [bx, by_]}],
                                          "partial": True}, port=PORT))
        cc.call("agent_jobs", {"jobs": [{"type": "build", "area": [[fx - 1, fy + 2], [fx + 4, fy + 5]]},
                                        {"type": "rotate", "at": [ix, iy], "direction": 4},
                                        {"type": "put", "to": [bx, by_], "item": "iron-plate", "count": 2}]}, port=PORT)
        agent_wait(40)
        rot, put = last_report("rotate"), last_report("put")
        results["rotate"] = bool(rot) and rot.get("event") == "done" and rot.get("direction") == 4
        results["put_on_belt"] = bool(put) and put.get("moved") == 2
        print("rotate:", rot, "put:", put)

        # 4f) tile ghosts: lay stone path from bricks
        st = cc.call("agent_status", {}, port=PORT)
        bricks = st["inventory"].get("stone-brick", 0)
        tx, ty = fx - 3, fy + 3
        laid = cc.call("tiles", {"tile": "stone-path", "positions": [[tx, ty], [tx, ty + 1]]}, port=PORT)
        print("tiles:", laid, "bricks:", bricks)
        cc.call("agent_jobs", {"jobs": [{"type": "build", "area": [[tx - 1, ty - 1], [tx + 2, ty + 3]]}]}, port=PORT)
        st = agent_wait(30)
        b = last_report("build")
        results["build_tiles"] = bool(b) and b.get("made") == 2 and st["inventory"].get("stone-brick", 0) == bricks - 2
        print("tile build:", b)

        # 4g) a ghost on a tree: build must fell the tree first
        m = cc.call("map", {"center": [st["position"]["x"], st["position"]["y"]], "radius": 40}, port=PORT)
        cells = [(m["origin"]["x"] + cx, m["origin"]["y"] + cy)
                 for cy, row in enumerate(m["rows"]) for cx, ch in enumerate(row) if ch == "T"]
        cells.sort(key=lambda c: (c[0] - st["position"]["x"]) ** 2 + (c[1] - st["position"]["y"]) ** 2)
        hit = None
        for x, y in cells[:40]:
            r = cc.call("place", {"entities": [{"name": "wooden-chest", "position": [x + 0.5, y + 0.5]}]}, port=PORT)
            if r.get("placed") and r.get("cleared"):
                hit = (x, y)
                break
            if r.get("placed"):
                cc.call("remove_ghosts", {"area": [[x, y], [x + 1, y + 1]]}, port=PORT)
        if hit:
            wood0 = st["inventory"].get("wood", 0)
            cc.call("agent_jobs", {"jobs": [{"type": "build", "area": [[hit[0] - 1, hit[1] - 1], [hit[0] + 2, hit[1] + 2]]}]},
                    port=PORT)
            st = agent_wait(60)
            b = last_report("build")
            results["build_clears_tree"] = bool(b) and b.get("made") == 1 and st["inventory"].get("wood", 0) > wood0
            print("build over tree:", b)
        else:
            print("no tree under a ghost spot: obstacle clearing not exercised")

        # 4h) deconstruct job: mine everything marked in an area
        px, py = round(st["position"]["x"]), round(st["position"]["y"])
        area = [[px - 12, py - 12], [px + 12, py + 12]]
        marked = cc.call("deconstruct", {"area": area}, port=PORT)["marked"]
        if marked:
            cc.call("agent_jobs", {"jobs": [{"type": "deconstruct", "area": area}]}, port=PORT)
            agent_wait(40 + marked * 4)
            d = last_report("deconstruct")
            results["deconstruct"] = bool(d) and d.get("got") == marked
            print("deconstruct:", marked, "marked ->", d)
        else:
            print("nothing to deconstruct nearby: job not exercised")

        # 4i) what the character crafts and mines must reach the production statistics
        prod = cc.call("production", {"items": ["wooden-chest", "transport-belt", "iron-gear-wheel", "wood", "iron-ore"]},
                       port=PORT)
        print("production:", {k: (v["made_total"], v["used_total"]) for k, v in prod.items()})
        results["craft_stats"] = (prod["wooden-chest"]["made_total"] == 1 and prod["transport-belt"]["made_total"] == 2
                                  and prod["iron-gear-wheel"]["made_total"] == 2 and prod["iron-gear-wheel"]["used_total"] == 2)
        results["mine_stats"] = prod["iron-ore"]["made_total"] == 12 and prod["wood"]["made_total"] >= 8

        # 4k) a job that does nothing must say so
        cc.call("agent_jobs", {"jobs": [{"type": "take", "from": [fx, fy], "item": "copper-plate"}]}, port=PORT)
        agent_wait(30)
        t = last_report("take")
        results["warn_on_nothing"] = bool(t) and t.get("warn") is True and t.get("moved") == 0 and bool(t.get("reason"))
        print("empty take:", t)

        # 4l) area_status names statuses; research_triggers lists the lab trigger.
        # A second furnace with stone but no fuel gives a known "no_fuel" to find.
        around = [[fx - 6, fy - 6], [fx + 6, fy + 6]]
        f2 = [fx, fy - 3]
        cc.call("agent_jobs", {"jobs": [{"type": "craft", "recipe": "stone-furnace", "count": 1, "wait": True}]}, port=PORT)
        agent_wait(30)
        print("place:", cc.call("place", {"entities": [{"name": "stone-furnace", "position": f2}]}, port=PORT))
        cc.call("agent_jobs", {"jobs": [{"type": "build", "area": [[fx - 2, fy - 5], [fx + 2, fy - 1.5]]},
                                        {"type": "put", "to": f2, "item": "stone", "count": 2},
                                        {"type": "wait", "ticks": 400}]}, port=PORT)
        agent_wait(40)
        status = cc.call("area_status", {"area": around}, port=PORT)
        print("area_status:", status["counts"], status["not_working"])
        names = [k for row in status["counts"].values() for k in row]
        results["area_status"] = ("stone-furnace" in status["counts"] and bool(names)
                                  and not any(n.isdigit() for n in names)
                                  and any(r["n"] == "stone-furnace" and r["s"] == "no_fuel" for r in status["not_working"]))
        trig = {r["tech"]: r for r in cc.call("research_triggers", {}, port=PORT)["triggers"]}
        lab = trig.get("automation-science-pack", {})
        steam = trig.get("steam-power", {})
        results["research_triggers"] = (lab.get("item") == "lab" and lab.get("ready") is False
                                        and steam.get("item") == "iron-plate" and steam.get("count") == 50
                                        and steam.get("made") == 12)
        print("triggers:", lab, steam)

        # 4m) alerts reach the chat file without being asked for
        alerts = chat_records("alert")
        whats = {r.get("what") for r in alerts}
        results["alerts"] = "no_fuel" in whats and "job_failed" in whats
        print("alerts so far:", sorted(w for w in whats if w))

        # 4n) craft that waits for its own result
        cc.call("agent_jobs", {"jobs": [{"type": "craft", "recipe": "wooden-chest", "count": 1, "wait": True}]}, port=PORT)
        st = agent_wait(30)
        cr = last_report("craft")
        results["craft_wait_flag"] = bool(cr) and cr.get("crafted") is True and st["crafting"] == 0

        # 4o) refuel shares a short supply: three burners each want 40 wood and there is less
        # than that between them, so all three must get some instead of the first taking it all
        wood = st["inventory"].get("wood", 0)
        cc.call("agent_jobs", {"jobs": [{"type": "refuel", "area": around, "fuel": "wood", "target": 40}]}, port=PORT)
        st = agent_wait(40)
        rf = last_report("refuel")
        results["refuel_shares"] = (bool(rf) and rf.get("burners") == 3 and rf.get("shared") is True and rf.get("made") == 3
                                    and 3 <= wood < 120 and rf.get("fuel_used") == wood
                                    and st["inventory"].get("wood", 0) == 0)
        print("refuel:", rf, "wood before:", wood)

        # 4p) collect from building outputs
        cc.call("agent_jobs", {"jobs": [{"type": "put", "to": [fx, fy], "item": "stone", "count": 4},
                                        {"type": "wait", "ticks": 500},
                                        {"type": "collect", "area": around, "item": "stone-brick"}]}, port=PORT)
        st = agent_wait(60)
        co = last_report("collect")
        results["collect"] = bool(co) and co.get("moved", 0) >= 2 and co.get("from", 0) >= 1
        print("collect:", co)

        # 4q) a repeat runs its jobs on a timer, quietly, and stops after `times`
        waits = len([r for r in chat_records("agent") if r.get("job") == "wait"])
        cc.call("agent_jobs", {"jobs": [{"type": "repeat", "every_ticks": 120, "times": 2,
                                         "jobs": [{"type": "wait", "ticks": 10}]}]}, port=PORT)
        time.sleep(1.5)
        mid = cc.call("agent_status", {}, port=PORT)
        time.sleep(5)
        end = cc.call("agent_status", {}, port=PORT)
        rp = last_report("repeat")
        waits2 = len([r for r in chat_records("agent") if r.get("job") == "wait"])
        results["repeat"] = (bool(rp) and rp.get("id") == 1 and bool(mid.get("repeats")) and not end.get("repeats")
                             and waits2 == waits and end.get("free_slots", 0) > 0)
        print("repeat:", rp, "mid:", mid.get("repeats"), "end:", end.get("repeats"))

        # 4r) the character's robots can be held back
        off = cc.call("agent_bots", {"enabled": False}, port=PORT)
        on = cc.call("agent_bots", {"enabled": True}, port=PORT)
        results["agent_bots"] = off.get("enabled") is False and on.get("enabled") is True

        # 4j) --research: craft a lab by hand; that must research automation-science-pack (several minutes)
        if "--research" in sys.argv:
            copper = by["copper-ore"]
            cc.call("agent_jobs", {"jobs": [
                {"type": "mine", "name": "iron-ore", "at": spot, "count": 50},
                {"type": "mine", "name": "copper-ore", "at": [copper["cx"], copper["cy"]], "count": 16},
                {"type": "mine", "kind": "tree", "radius": 120, "count": 16},
                {"type": "put", "to": [fx, fy], "item": "wood"},
                {"type": "put", "to": [fx, fy], "item": "iron-ore"},
                {"type": "wait", "ticks": 10200},
                {"type": "take", "from": [fx, fy], "item": "iron-plate"},
                {"type": "put", "to": [fx, fy], "item": "copper-ore"},
                {"type": "wait", "ticks": 3400},
                {"type": "take", "from": [fx, fy], "item": "copper-plate"}]}, port=PORT)
            st = agent_wait(900)
            print("before lab:", st["inventory"], last_report("take"))
            avail = cc.call("research", {}, port=PORT)["available"]
            ready = "automation-science-pack" in avail
            cc.call("agent_jobs", {"jobs": [{"type": "craft", "recipe": "lab", "count": 1},
                                            {"type": "wait", "craft": True}]}, port=PORT)
            st = agent_wait(120)
            avail2 = cc.call("research", {}, port=PORT)["available"]
            labs = cc.call("production", {"items": ["lab"]}, port=PORT)["lab"]["made_total"]
            results["lab_trigger"] = (ready and st["inventory"].get("lab", 0) == 1 and labs == 1
                                      and "automation-science-pack" not in avail2)
            print("lab: ready before", ready, "| labs made", labs, "| available after", avail2)

        # 5) wait ticks
        t0 = cc.call("ping", {}, port=PORT)["tick"]
        cc.call("agent_jobs", {"jobs": [{"type": "wait", "ticks": 120}]}, port=PORT)
        agent_wait(20)
        t1 = cc.call("ping", {}, port=PORT)["tick"]
        results["wait_ticks"] = t1 - t0 >= 120
    finally:
        srv.terminate()
        try:
            srv.wait(15)
        except Exception:
            srv.kill()
    log = os.path.join(WORK, "factorio-current.log")
    if os.path.isfile(log):
        errs = [l for l in open(log, encoding="utf-8", errors="replace") if "Error" in l or "error" in l]
        if errs:
            print("log errors:\n" + "".join(errs[-15:]))
    print("RESULTS", json.dumps(results))
    sys.exit(0 if results and all(results.values()) else 1)


if __name__ == "__main__":
    main()
