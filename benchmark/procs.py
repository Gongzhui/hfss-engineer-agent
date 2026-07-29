"""ansysedt.exe process snapshot / cleanup helpers shared by benchmark scripts.

Only PIDs that appeared *after* the snapshot are ever killed — pre-existing
AEDT sessions belonging to the user are left untouched.
"""

from __future__ import annotations

import subprocess


def ansysedt_pids() -> set[int]:
    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq ansysedt.exe", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout
    pids: set[int] = set()
    for line in out.splitlines():
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) >= 2 and parts[0].lower().startswith("ansysedt"):
            try:
                pids.add(int(parts[1]))
            except ValueError:
                continue
    return pids


def kill_spawned(pre: set[int], settle_s: float = 5.0, retries: int = 3) -> set[int]:
    """Kill ansysedt PIDs that appeared after snapshot ``pre``; return leftovers.

    Workers may still be shutting down when the job reports completion, so we
    wait briefly and retry before declaring a residue.
    """
    import time

    for attempt in range(retries + 1):
        spawned = ansysedt_pids() - pre
        if not spawned:
            return set()
        if attempt < retries:
            time.sleep(settle_s)
            spawned = ansysedt_pids() - pre
            for pid in sorted(spawned):
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    timeout=30,
                )
    return ansysedt_pids() - pre
