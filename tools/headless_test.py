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
        time.sleep(1)
    return cc.call("agent_status", {}, port=port)


def main():
    exe = find_factorio()
    print("factorio:", exe)
    cfg, mods = setup(exe)
    save = os.path.join(WORK, "test.zip")
    p = run(exe, cfg, mods, "--create", save)
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
