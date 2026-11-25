import sys, time, runpy
sys.argv = [sys.argv[1], sys.argv[2], "none"]
g = runpy.run_path(sys.argv[0])
sys.path.insert(0, sys.argv[1])
import cc
final = g["FINAL"]
for _ in range(360):                       # up to an hour
    res = cc.call_batched("check", final, {})
    if not res.get("blocked"):
        cc.show(cc.call_batched("place", final, {"tag": "iron", "partial": True}))
        print("FINAL LINK PLACED")
        break
    cc.call_batched("place", final, {"tag": "iron", "partial": True})
    time.sleep(10)
