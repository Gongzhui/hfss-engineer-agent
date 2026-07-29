"""Run a benchmark case through the real MCP toolchain and score it.

    uv run python benchmark/run_case.py --case siw_feed_l1 --policy probe
    uv run python benchmark/run_case.py --case siw_feed_l1 --policy probe --max-trials 1

The runner spawns ``hfss_mcp.server`` as an MCP stdio subprocess and only
touches the *sandbox* project through manifest/trial tools. The answer book
is used afterwards, for scoring only.

Policy ``probe`` (deterministic scripted baseline):
  t1       — baseline at the sandbox's current (perturbed) values;
  t2..tN   — coordinate descent: per whitelisted variable, in case order,
             try the range midpoint on top of the best-so-far vector;
             keep the move iff the primary metric improves.

PASS = final best primary metric beats the broken baseline AND all
case.json thresholds hold. Exit 0 on PASS, 1 on FAIL, 2 on preflight.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from case_io import Case, load_case, read_design_variables  # noqa: E402
from procs import ansysedt_pids, kill_spawned  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TERMINAL_STATES = {"completed", "failed", "cancelled", "interrupted"}
TRIAL_TIMEOUT_S = 1800.0
CROSS_CHECK_TOL_DB = 0.01


def log(msg: str) -> None:
    print(msg, flush=True)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class RunFailure(RuntimeError):
    pass


async def call_tool(session: Any, name: str, args: dict[str, Any]) -> dict[str, Any]:
    result = await session.call_tool(name, args)
    if result.isError:
        text = "".join(getattr(block, "text", "") for block in (result.content or []))
        raise RunFailure(f"MCP tool {name} transport error: {text}")
    payload = result.structuredContent
    if payload is None:
        text = "".join(getattr(block, "text", "") for block in (result.content or []))
        payload = json.loads(text) if text.strip() else {}
    if isinstance(payload, dict) and payload.get("ok") is False:
        err = json.dumps(payload.get("error"), ensure_ascii=False)
        raise RunFailure(f"MCP tool {name} rejected: {err}")
    if not isinstance(payload, dict):
        raise RunFailure(f"MCP tool {name} returned unexpected payload: {payload!r}")
    return payload


class TrialDriver:
    """MCP-stdio driver for the manifest/trial toolchain."""

    def __init__(self, case: Case, run_dir: Path) -> None:
        self.case = case
        self.run_dir = run_dir
        self.ts_dir = run_dir / "touchstone"
        self.ts_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "tmp").mkdir(parents=True, exist_ok=True)
        self.trials_used = 0

    async def __aenter__(self) -> TrialDriver:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        env = os.environ.copy()
        env.update(
            {
                "HFSS_MCP_ADAPTER": "pyaedt",
                "HFSS_MCP_DATA_DIR": str(self.run_dir / "app_data"),
                "HFSS_MCP_TOUCHSTONE_KEEP_DIR": str(self.ts_dir),
                "FASTMCP_LOG_LEVEL": "WARNING",
                "TMP": str(self.run_dir / "tmp"),
                "TEMP": str(self.run_dir / "tmp"),
                "TMPDIR": str(self.run_dir / "tmp"),
            }
        )
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "hfss_mcp.server"],
            env=env,
            cwd=str(REPO),
        )
        self._stack = __import__("contextlib").AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        health = await call_tool(self.session, "health", {})
        log(
            f"server health: adapter={health.get('adapter')} "
            f"connection_mode={health.get('connection_mode')} "
            f"real_hfss_ready={health.get('real_hfss_ready')}"
        )
        if health.get("adapter") != "pyaedt" or not health.get("real_hfss_ready"):
            raise RunFailure("real HFSS backend not ready")
        manifest = json.loads(self.case.manifest_path.read_text(encoding="utf-8"))
        reg = await call_tool(self.session, "manifest_validate", {"manifest": manifest})
        self.mid = reg["manifest_id"]
        log(f"manifest registered via MCP: id={self.mid[:16]}...")
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._stack.aclose()

    async def run_trial(self, label: str, params: dict[str, float]) -> dict[str, Any]:
        self.trials_used += 1
        mark = time.time()
        t0 = time.time()
        start = await call_tool(
            self.session,
            "trial_start",
            {
                "manifest_id": self.mid,
                "run_id": self.run_dir.name,
                "trial_id": label,
                "idempotency_key": f"{self.run_dir.name}-{label}",
                "setup": self.case.source.setup,
                "sweep": self.case.source.sweep,
                "parameters": [
                    {"name": v.name, "value": params[v.name], "unit": v.unit}
                    for v in self.case.variables
                ],
            },
        )
        job_id = start["job_id"]
        deadline = time.time() + TRIAL_TIMEOUT_S
        while True:
            status = await call_tool(self.session, "trial_status", {"job_id": job_id})
            state = status["job"]["state"]
            if state in TERMINAL_STATES:
                break
            if time.time() > deadline:
                raise RunFailure(f"trial {label} exceeded {TRIAL_TIMEOUT_S}s")
            await asyncio.sleep(5.0)
        result = await call_tool(self.session, "trial_result", {"job_id": job_id})
        if result["state"] != "completed":
            err = json.dumps(result.get("error"), ensure_ascii=False)
            raise RunFailure(f"trial {label} ended state={result['state']}: {err}")
        ts = self._harvest(mark, label)
        row = {
            "label": label,
            "job_id": job_id,
            "params": dict(params),
            "metrics": result["result"]["metrics"],
            "solve_seconds": round(time.time() - t0, 1),
            "touchstone": {
                "file": ts.name,
                "mtime": datetime.fromtimestamp(ts.stat().st_mtime, UTC).isoformat(),
            },
        }
        self._check_touchstone(row)
        log(
            f"  {label}: {self.case.metrics.primary}="
            f"{row['metrics'][self.case.metrics.primary]:.4f} dB "
            f"({row['solve_seconds']}s) params={ {k: round(v, 4) for k, v in params.items()} }"
        )
        return row

    def _harvest(self, since: float, label: str) -> Path:
        candidates = [
            p
            for p in self.ts_dir.glob("*.s*p")
            if p.is_file() and p.stat().st_mtime >= since - 2.0
        ]
        if not candidates:
            raise RunFailure(f"trial {label}: no Touchstone appeared in {self.ts_dir}")
        return max(candidates, key=lambda p: p.stat().st_mtime)

    def _check_touchstone(self, row: dict[str, Any]) -> None:
        """Tool metric must equal an independent re-parse of the Touchstone file."""
        from hfss_mcp.metrics import parse_touchstone_s11_db

        ts = self.ts_dir / row["touchstone"]["file"]
        freqs, s11_db = parse_touchstone_s11_db(ts)
        target = self.case.metrics.target_ghz
        _f, v = min(zip(freqs, s11_db, strict=False), key=lambda t: abs(t[0] - target))
        tool_v = float(row["metrics"]["S11_at_target_dB"])
        if abs(v - tool_v) > 1e-6:
            raise RunFailure(
                f"{row['label']}: touchstone re-parse {v} != tool metric {tool_v}"
            )
        row["touchstone"]["reparsed_s11_at_target_db"] = v


def probe_moves(case: Case) -> list[tuple[str, float]]:
    """Deterministic coordinate moves: per variable, in case order, try the range midpoint."""
    return [(var.name, round((var.min + var.max) / 2.0, 4)) for var in case.variables]


async def run_case(case: Case, run_dir: Path, max_trials: int) -> dict[str, Any]:
    from hfss_mcp.ids import file_sha256

    report: dict[str, Any] = {
        "case_id": case.case_id,
        "policy": "probe",
        "run_id": run_dir.name,
        "started_at": _utc_now(),
        "budget": {"max_trials": max_trials},
        "thresholds": dict(case.metrics.thresholds),
        "primary_metric": case.metrics.primary,
    }
    sandbox = case.sandbox_project
    sha_before = file_sha256(sandbox)
    report["sandbox_sha256_before"] = sha_before

    current = {
        v.name: float(read_design_variables(sandbox, case.source.design_name)[v.name][0])
        for v in case.variables
    }
    report["initial_params"] = current
    primary = case.metrics.primary

    trials: list[dict[str, Any]] = []
    async with TrialDriver(case, run_dir) as driver:
        row = await driver.run_trial("t1_baseline", current)
        trials.append(row)
        best_row: dict[str, Any] = row
        best_params = dict(current)
        log(f"  -> baseline {primary}={row['metrics'][primary]:.4f} dB")
        for name, mid_value in probe_moves(case):
            if driver.trials_used >= max_trials:
                log(f"budget exhausted ({max_trials} trials) — stopping schedule")
                break
            candidate = dict(best_params)
            candidate[name] = mid_value
            label = f"t{driver.trials_used + 1}_{name}"
            row = await driver.run_trial(label, candidate)
            trials.append(row)
            if row["metrics"][primary] < best_row["metrics"][primary]:
                best_row = row
                best_params = dict(candidate)
                log(f"  -> new best {best_row['metrics'][primary]:.4f} dB @ {label}")
            else:
                log("  -> not better; coordinate move reverted")
        report["trials_used"] = driver.trials_used

    baseline = trials[0]
    improvement = baseline["metrics"][primary] - best_row["metrics"][primary]

    # cross-check runner baseline against the answer book's broken baseline
    answer = json.loads((case.answer_dir / "metrics.json").read_text(encoding="utf-8"))
    broken = answer["results"]["broken"]["metrics"]
    cross = {
        name: abs(float(baseline["metrics"][name]) - float(broken[name]))
        for name in ("S11_min_dB", "S11_min_freq_GHz", "S11_at_target_dB")
    }
    cross_ok = all(v <= CROSS_CHECK_TOL_DB for v in cross.values())

    thresholds = {
        name: {
            "threshold": thr,
            "value": best_row["metrics"][name],
            "met": best_row["metrics"][name] <= thr,
        }
        for name, thr in case.metrics.thresholds.items()
    }
    thresholds_met = all(t["met"] for t in thresholds.values())

    sha_after = file_sha256(sandbox)
    report.update(
        {
            "finished_at": _utc_now(),
            "trials": trials,
            "baseline": baseline,
            "best": best_row,
            "best_params": best_params,
            "improvement_db": round(improvement, 4),
            "answer_broken_metrics": broken,
            "cross_check_abs_diff_db": cross,
            "cross_check_ok": cross_ok,
            "thresholds": thresholds,
            "thresholds_met": thresholds_met,
            "sandbox_sha256_after": sha_after,
            "sandbox_unchanged": sha_before == sha_after,
            "answer_nominal_metrics": answer["results"]["nominal"]["metrics"],
        }
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a benchmark case via MCP stdio.")
    parser.add_argument("--case", required=True, help="case id under benchmark/cases/")
    parser.add_argument("--policy", choices=["probe"], default="probe")
    parser.add_argument(
        "--max-trials",
        type=int,
        default=None,
        help="override case budget (used by negative-verification runs)",
    )
    parser.add_argument("--run-id", default=None, help="run directory name (default: timestamp)")
    args = parser.parse_args()

    try:
        case = load_case(args.case)
    except (FileNotFoundError, ValueError) as exc:
        log(f"PREFLIGHT FAIL: {exc}")
        return 2
    if not case.sandbox_project.is_file() or not case.manifest_path.is_file():
        log("PREFLIGHT FAIL: sandbox/manifest missing — run build_case.py + verify_case.py first")
        return 2
    if not (case.answer_dir / "metrics.json").is_file():
        log("PREFLIGHT FAIL: answer book missing — run build_case.py --stage answer first")
        return 2

    max_trials = args.max_trials or case.budget.max_trials
    run_id = args.run_id or datetime.now(UTC).strftime("run_%Y%m%dT%H%M%SZ")
    run_dir = case.runs_dir / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    log(f"run: case={case.case_id} policy={args.policy} budget={max_trials} dir={run_dir}")
    pre_pids = ansysedt_pids()
    t0 = time.time()
    report: dict[str, Any] | None = None
    code = 1
    try:
        report = asyncio.run(run_case(case, run_dir, max_trials))
        improvement = report["improvement_db"]
        passed = (
            report["thresholds_met"]
            and improvement > 0
            and report["sandbox_unchanged"]
            and report["cross_check_ok"]
        )
        report["status"] = "PASS" if passed else "FAIL"
        report["wall_seconds"] = round(time.time() - t0, 1)
        log(
            f"RESULT: primary {report['primary_metric']} broken="
            f"{report['baseline']['metrics'][report['primary_metric']]:.4f} -> best="
            f"{report['best']['metrics'][report['primary_metric']]:.4f} dB "
            f"(improvement {improvement:+.4f} dB, answer-nominal "
            f"{report['answer_nominal_metrics'][report['primary_metric']]:.4f} dB)"
        )
        log(f"thresholds_met={report['thresholds_met']} sandbox_unchanged="
            f"{report['sandbox_unchanged']} cross_check_ok={report['cross_check_ok']}")
        log(f"STATUS: {report['status']}")
        code = 0 if passed else 1
    except Exception as exc:
        leaf: BaseException = exc
        while isinstance(leaf, BaseExceptionGroup) and leaf.exceptions:
            leaf = leaf.exceptions[0]
        log(f"RUN FAILED: {type(leaf).__name__}: {leaf}")
        report = report or {"case_id": case.case_id, "run_id": run_id}
        report["status"] = "ERROR"
        report["error"] = f"{type(leaf).__name__}: {leaf}"
        code = 1
    finally:
        leftover = kill_spawned(pre_pids)
        no_residue = not leftover
        log(f"NO_AEDT_RESIDUE: {no_residue}")
        if report is not None:
            report["no_aedt_residue"] = no_residue
            (run_dir / "report.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
            log(f"report: {run_dir / 'report.json'}")
        if not no_residue:
            code = 1
        shutil.rmtree(run_dir / "tmp", ignore_errors=True)  # pywin32 gen_py cache
    return code


if __name__ == "__main__":
    raise SystemExit(main())
