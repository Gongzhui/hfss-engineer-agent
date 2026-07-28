"""One-command real-HFSS closed-loop demo, driven over the MCP protocol (stdio).

    uv run python examples/run_demo.py

What the audience sees:
  1. SHA-256 of the golden project BEFORE the run.
  2. An MCP server spawned as a stdio subprocess; every action goes through
     MCP tools (manifest_validate / trial_start / trial_status / trial_result).
  3. >=6 trials tuning the whitelisted ``gap`` variable; each trial runs in an
     exclusive worker AEDT desktop on a *workspace copy* of the golden project.
  4. A trial/gap/S11 table built from real Touchstone exports (re-parsed here
     from the persisted .s1p files; file mtimes prove they were made now).
  5. SHA-256 of the golden project AFTER the run — must be identical.
  6. examples/demo_output/results.json + zero leftover ansysedt.exe.

Exit codes: 0 = success (best S11 beats baseline and hash unchanged);
1 = demo failure; 2 = preflight failure.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hfss_mcp.ids import file_sha256
from hfss_mcp.metrics import parse_touchstone_s11_db

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
GOLDEN = HERE / "golden_patch.aedt"
MANIFEST_PATH = HERE / "golden_manifest.json"
OUT = HERE / "demo_output"
DATA_DIR = OUT / "data"
TS_DIR = OUT / "touchstone"
TMP_DIR = OUT / "tmp"
RESULTS = OUT / "results.json"
AEDT_EXE = Path(r"C:\Program Files\AnsysEM\v232\Win64\ansysedt.exe")

# First entry reproduces the golden project's initial gap=1mm (baseline).
TRIAL_GAPS_MM = [1.0, 0.6, 0.8, 1.5, 2.0, 2.5]
TARGET_GHZ = 2.4
TRIAL_TIMEOUT_S = 900.0
TERMINAL_STATES = {"completed", "failed", "cancelled", "interrupted"}


def log(msg: str) -> None:
    print(msg, flush=True)


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


def kill_pids(pids: set[int]) -> None:
    for pid in sorted(pids):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=30,
        )


class DemoFailure(RuntimeError):
    pass


async def call_tool(session: Any, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call one MCP tool; unwrap structured payload; raise on tool-level error."""
    result = await session.call_tool(name, args)
    if result.isError:
        text = "".join(getattr(block, "text", "") for block in (result.content or []))
        raise DemoFailure(f"MCP tool {name} transport error: {text}")
    payload = result.structuredContent
    if payload is None:
        text = "".join(getattr(block, "text", "") for block in (result.content or []))
        payload = json.loads(text) if text.strip() else {}
    if isinstance(payload, dict) and payload.get("ok") is False:
        err = json.dumps(payload.get("error"), ensure_ascii=False)
        raise DemoFailure(f"MCP tool {name} rejected: {err}")
    if not isinstance(payload, dict):
        raise DemoFailure(f"MCP tool {name} returned unexpected payload: {payload!r}")
    return payload


def newest_touchstone(since_epoch: float) -> Path:
    candidates = [
        p
        for p in TS_DIR.glob("*.s*p")
        if p.is_file() and p.stat().st_mtime >= since_epoch - 2.0
    ]
    if not candidates:
        raise DemoFailure(
            f"no Touchstone file appeared in {TS_DIR} during the trial "
            "(HFSS_MCP_TOUCHSTONE_KEEP_DIR hook did not fire)"
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)


async def run_trials(session: Any, mid: str) -> list[dict[str, Any]]:
    """Drive >=6 whitelist trials through MCP tools; return table rows."""
    rows: list[dict[str, Any]] = []
    log("-" * 78)
    log(
        f"{'trial':<6}{'gap(mm)':>8} {'S11@2.4GHz(dB)':>15} {'S11_min(dB)':>12}"
        f" {'min@GHz':>8}  touchstone"
    )
    for i, gap in enumerate(TRIAL_GAPS_MM, start=1):
        mark = time.time()
        start = await call_tool(
            session,
            "trial_start",
            {
                "manifest_id": mid,
                "run_id": "demo_run",
                "trial_id": f"t{i}",
                "idempotency_key": f"demo-gap-{i}",
                "setup": "Setup1",
                "sweep": "Sweep1",
                "parameters": [{"name": "gap", "value": gap, "unit": "mm"}],
            },
        )
        job_id = start["job_id"]
        deadline = time.time() + TRIAL_TIMEOUT_S
        while True:
            status = await call_tool(session, "trial_status", {"job_id": job_id})
            state = status["job"]["state"]
            if state in TERMINAL_STATES:
                break
            if time.time() > deadline:
                raise DemoFailure(f"trial t{i} timed out after {TRIAL_TIMEOUT_S}s")
            await asyncio.sleep(2.0)

        result = await call_tool(session, "trial_result", {"job_id": job_id})
        if result["state"] != "completed":
            err = json.dumps(result.get("error"), ensure_ascii=False)
            raise DemoFailure(f"trial t{i} ended in state={result['state']}: {err}")
        metrics = result["result"]["metrics"]

        s1p = newest_touchstone(mark)
        freqs, s11_db = parse_touchstone_s11_db(s1p)
        f_best, v_best = min(
            zip(freqs, s11_db, strict=False), key=lambda t: abs(t[0] - TARGET_GHZ)
        )
        tool_v = float(metrics["S11_at_target_dB"])
        if abs(v_best - tool_v) > 1e-6:
            raise DemoFailure(
                f"trial t{i}: touchstone re-parse {v_best} != tool metric {tool_v}"
            )
        row = {
            "trial": f"t{i}",
            "gap_mm": gap,
            "s11_at_target_db": tool_v,
            "s11_min_db": float(metrics["S11_min_dB"]),
            "s11_min_freq_ghz": float(metrics["S11_min_freq_GHz"]),
            "touchstone": s1p.name,
            "touchstone_mtime": datetime.fromtimestamp(
                s1p.stat().st_mtime, UTC
            ).isoformat(),
            "touchstone_points": len(freqs),
            "reparsed_freq_ghz": f_best,
            "job_id": job_id,
        }
        rows.append(row)
        log(
            f"t{i:<5}{gap:>8.1f} {tool_v:>15.4f} {row['s11_min_db']:>12.4f}"
            f" {row['s11_min_freq_ghz']:>8.2f}  {s1p.name}"
        )
    log("-" * 78)
    return rows


async def run_demo() -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    started = datetime.now(UTC)
    log("=" * 78)
    log("hfss-mcp real-HFSS closed-loop demo (MCP stdio)")
    log("=" * 78)

    # --- Preflight ---------------------------------------------------------
    if not AEDT_EXE.is_file():
        log(f"PREFLIGHT FAIL: AEDT 2023 R2 not found at {AEDT_EXE}")
        return 2
    if not GOLDEN.is_file() or not MANIFEST_PATH.is_file():
        log("PREFLIGHT FAIL: golden project/manifest missing.")
        log("Run:  uv run python examples/build_golden.py")
        return 2

    pre_pids = ansysedt_pids()
    if pre_pids:
        log(
            f"note: {len(pre_pids)} pre-existing ansysedt.exe PID(s) "
            f"{sorted(pre_pids)} — left untouched; demo cleans up only its own."
        )

    if OUT.exists():
        shutil.rmtree(OUT, ignore_errors=True)
    TS_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    sha_before = file_sha256(GOLDEN)
    log(f"GOLDEN_SHA256_BEFORE={sha_before}")

    env = os.environ.copy()
    env.update(
        {
            "HFSS_MCP_ADAPTER": "pyaedt",
            "HFSS_MCP_DATA_DIR": str(DATA_DIR),
            "HFSS_MCP_TOUCHSTONE_KEEP_DIR": str(TS_DIR),
            "FASTMCP_LOG_LEVEL": "WARNING",
            "TMP": str(TMP_DIR),
            "TEMP": str(TMP_DIR),
            "TMPDIR": str(TMP_DIR),
        }
    )
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "hfss_mcp.server"],
        env=env,
        cwd=str(REPO),
    )

    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        health = await call_tool(session, "health", {})
        log(
            f"server health: adapter={health.get('adapter')} "
            f"connection_mode={health.get('connection_mode')} "
            f"real_hfss_ready={health.get('real_hfss_ready')}"
        )
        if health.get("adapter") != "pyaedt" or not health.get("real_hfss_ready"):
            raise DemoFailure("real HFSS backend not ready")

        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        reg = await call_tool(session, "manifest_validate", {"manifest": manifest})
        mid = reg["manifest_id"]
        whitelist = [(p["name"], p["min"], p["max"], p["unit"]) for p in reg["parameters"]]
        log(f"manifest registered: id={mid[:16]}... whitelist={whitelist}")

        rows = await run_trials(session, mid)

    baseline = rows[0]
    best = min(rows, key=lambda r: r["s11_at_target_db"])
    improvement = baseline["s11_at_target_db"] - best["s11_at_target_db"]
    log(
        f"BEST: {best['trial']} gap={best['gap_mm']}mm "
        f"S11@2.4GHz={best['s11_at_target_db']:.4f} dB "
        f"(baseline {baseline['s11_at_target_db']:.4f} dB @ gap={baseline['gap_mm']}mm)"
    )
    log(f"IMPROVEMENT: {improvement:.4f} dB")

    sha_after = file_sha256(GOLDEN)
    unchanged = sha_after == sha_before
    log(f"GOLDEN_SHA256_AFTER={sha_after}")
    log(f"GOLDEN_UNCHANGED: {unchanged}")

    finished = datetime.now(UTC)
    RESULTS.write_text(
        json.dumps(
            {
                "demo": "hfss-mcp real-HFSS closed loop over MCP stdio",
                "golden_project": str(GOLDEN),
                "golden_sha256_before": sha_before,
                "golden_sha256_after": sha_after,
                "golden_unchanged": unchanged,
                "target_ghz": TARGET_GHZ,
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "trials": rows,
                "baseline": baseline,
                "best": best,
                "improvement_db": improvement,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    log(f"results: {RESULTS}")

    if not unchanged:
        log("FAIL: golden project bytes changed during the run")
        return 1
    if improvement <= 0:
        log("FAIL: best trial did not improve S11 over baseline")
        return 1
    log("DEMO RESULT: PASS (closed loop improved S11; golden project untouched)")
    return 0


def _leaf_error(exc: BaseException) -> BaseException:
    """Unwrap nested anyio ExceptionGroups down to the first real error."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def main() -> int:
    pre = ansysedt_pids()
    code = 1
    try:
        code = asyncio.run(run_demo())
    except KeyboardInterrupt:
        code = 130
    except Exception as exc:
        leaf = _leaf_error(exc)
        if isinstance(leaf, DemoFailure):
            log(f"DEMO FAILED: {leaf}")
        else:
            log(f"DEMO CRASHED: {type(leaf).__name__}: {leaf}")
        code = 1
    finally:
        spawned = ansysedt_pids() - pre
        if spawned:
            log(
                f"cleanup: killing {len(spawned)} demo-spawned ansysedt.exe "
                f"PID(s) {sorted(spawned)}"
            )
            kill_pids(spawned)
            time.sleep(2.0)
        leftover = ansysedt_pids() - pre
        log(f"NO_AEDT_RESIDUE: {not leftover}")
        if leftover:
            log(f"WARNING: ansysedt.exe still running: {sorted(leftover)}")
            code = 1
        # Keep the repo tree lint-clean: the redirected TMP accumulates a
        # pywin32 gen_py cache that ruff would otherwise scan.
        shutil.rmtree(TMP_DIR, ignore_errors=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
