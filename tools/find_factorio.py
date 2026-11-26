"""Prints the path of the running factorio.exe (Windows), for headless tests."""
import subprocess
out = subprocess.run(["powershell", "-NoProfile", "-Command",
                      "Get-Process factorio -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Path"],
                     capture_output=True, text=True)
print(out.stdout.strip() or "not running", out.stderr.strip())
