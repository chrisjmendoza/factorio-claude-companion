"""Read-only lookup in the Factorio install's data files (Windows).

    python tools/factorio_data.py <relative path under data/> [grep text] [context lines]
"""
import os, subprocess, sys
out = subprocess.run(["powershell", "-NoProfile", "-Command",
                      "Get-Process factorio -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Path"],
                     capture_output=True, text=True).stdout.strip()
exe = out or r"C:\Games\Steam\steamapps\common\Factorio\bin\x64\factorio.exe"
data = os.path.normpath(os.path.join(os.path.dirname(exe), "..", "..", "data"))
path = os.path.join(data, sys.argv[1])
lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
if len(sys.argv) < 3:
    print("\n".join(lines[:200])); sys.exit()
ctx = int(sys.argv[3]) if len(sys.argv) > 3 else 15
for i, l in enumerate(lines):
    if sys.argv[2] in l:
        print(f"--- {i+1}"); print("\n".join(lines[max(0, i - 2):i + ctx]))
