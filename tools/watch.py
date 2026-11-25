"""Polls the game once a minute and prints a line only when something worth
acting on changes: a build finishes (its ghosts all built), the shortfall list
empties, or a key production rate crosses the next threshold. Plus a heartbeat
every 10 minutes with the key rates."""
import sys, time

sys.path.insert(0, sys.argv[1])  # ClaudeCompanion/tools
import cc  # noqa: E402

KEY = ["iron-plate", "copper-plate", "coal", "electronic-circuit", "automation-science-pack"]
STEPS = [50, 100, 200, 400, 800, 1600, 3200]  # items per 10 min

prev_ghosts = None
last_reported = 0
prev_short = None
power_warned = fuel_warned = False
tier = {}
last_beat = 0.0


def out(msg):
    print(msg, flush=True)


while True:
    try:
        g = cc.call("ghosts", {})
        p = cc.call("production", {})
    except Exception as err:  # game closed or busy: say so once a minute at most
        out(f"WATCH ERROR {type(err).__name__}: {err}")
        time.sleep(60)
        continue

    n = g.get("ghosts", 0)
    short = sorted((g.get("short") or {}).items())
    if prev_ghosts is not None and n == 0 and prev_ghosts > 0:
        out("MILESTONE all ghosts built")
    elif prev_ghosts is not None and last_reported - n >= max(8, last_reported // 10):
        out(f"PROGRESS ghosts {last_reported} -> {n}")
        last_reported = n
    if prev_ghosts is None or n > last_reported:
        last_reported = n  # new ghosts placed: report progress from here
    if prev_short is not None and short != prev_short and not short and n:
        out(f"MILESTONE nothing short: the {n} ghosts left only need building")
    prev_ghosts, prev_short = n, short

    for item in KEY:
        rate = (p.get(item) or {}).get("made_last_10m", 0)
        t = sum(1 for s in STEPS if rate >= s)
        if item in tier and t > tier[item]:
            out(f"MILESTONE {item} now {rate:.0f}/10min")
        tier[item] = max(t, tier.get(item, 0))

    # power (needs the mod's `power` command; silently skipped on older builds)
    try:
        pw = cc.call("power", {})
        for net in pw.get("networks", []):
            load = net.get("load") or 0
            if load >= 0.85 and not power_warned:
                out(f"POWER high load {load:.0%}: {net['produced_w']/1e6:.2f} of {net['capacity_w']/1e6:.2f} MW")
                power_warned = True
            elif load < 0.7:
                power_warned = False
        if pw.get("boilers_out_of_fuel", 0) and not fuel_warned:
            out(f"POWER {pw['boilers_out_of_fuel']} boiler(s) out of fuel")
            fuel_warned = True
        elif not pw.get("boilers_out_of_fuel", 0):
            fuel_warned = False
    except Exception:
        pass

    if time.time() - last_beat >= 600:
        rates = ", ".join(f"{i} {(p.get(i) or {}).get('made_last_10m', 0):.0f}" for i in KEY[:3])
        out(f"HEARTBEAT ghosts {n}, short {dict(short)}; per 10min: {rates}")
        last_beat = time.time()
    time.sleep(60)
