"""Fresh hosted job guard; candidate UID cannot change this process or file."""

import os
import subprocess
import sys
import time

from enforcement import enabled, skipped

if not enabled():
    skipped("deadline")
    raise SystemExit(0)

deadline = int(sys.argv[1])
remaining = deadline - time.time()
if not 0 < remaining <= 1200:
    raise SystemExit(1)
time.sleep(remaining)
subprocess.run(["sudo", "pkill", "-KILL", "-u", "oncall"], check=False)
# Gateway independently enforces the same deadline; no candidate process can
# extend either clock. Publisher rechecks deadline before every allowed write.
os._exit(0)
