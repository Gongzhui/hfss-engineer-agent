"""Real AEDT 2023 R2 end-to-end acceptance (exclusive temp project only)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from hfss_mcp.app import AppContext
from hfss_mcp.domain import JobState
from hfss_mcp.ids import file_sha256
from hfss_mcp.manifest import default_s11_metrics
from hfss_mcp.real_project import create_minimal_patch_project

pytestmark = pytest.mark.real_aedt


def _aedt_available() -> bool:
    return Path(r"C:\Program Files\AnsysEM\v232\Win64\ansysedt.exe").is_file()


@pytest.fixture(scope="module")
def real_project(tmp_path_factory: pytest.TempPathFactory) -> dict:
    if not _aedt_available():
        pytest.skip("AEDT 2023 R2 not installed")
    work = tmp_path_factory.mktemp("real_aedt_proj")
    meta = create_minimal_patch_project(work, non_graphical=True)
    path = Path(meta["project_path"])
    assert path.is_file()
    meta["original_sha256"] = file_sha256(path)
    return meta


def test_real_aedt_full_loop(real_project: dict, tmp_path: Path) -> None:
    """Full closed loop: workspace, checkpoint, mutate, solve, metrics, durable job."""
    original = Path(real_project["project_path"])
    original_hash = real_project["original_sha256"]
    data_dir = tmp_path / "hfss_mcp_data"
    params = real_project["parameters"]
    # Build parameter vector for all allowlisted vars
    param_specs = [
        {"name": "gap", "unit": "mm", "min": 0.5, "max": 3.0},
    ]
    if "patch_w" in params:
        param_specs = [
            {"name": "patch_w", "unit": "mm", "min": 5.0, "max": 20.0},
            {"name": "patch_l", "unit": "mm", "min": 5.0, "max": 20.0},
        ]

    ctx = AppContext(
        data_dir=data_dir,
        use_fake=False,
        inline_trials=False,
        start_supervisor=True,
    )
    evidence: dict = {"steps": []}
    try:
        assert ctx.config.adapter == "pyaedt"
        health = ctx.health()
        evidence["health"] = {
            "adapter": health["adapter"],
            "real_hfss_ready": health["real_hfss_ready"],
            "connection_mode": health["connection_mode"],
        }
        assert health["adapter"] == "pyaedt"
        assert health["real_hfss_ready"] is True

        values = (
            [{"name": "gap", "value": 1.2, "unit": "mm"}]
            if param_specs[0]["name"] == "gap"
            else [
                {"name": "patch_w", "value": 11.0, "unit": "mm"},
                {"name": "patch_l", "value": 12.0, "unit": "mm"},
            ]
        )
        bad_values = (
            [{"name": "gap", "value": 99.0, "unit": "mm"}]
            if param_specs[0]["name"] == "gap"
            else [
                {"name": "patch_w", "value": 99.0, "unit": "mm"},
                {"name": "patch_l", "value": 12.0, "unit": "mm"},
            ]
        )

        manifest_body = {
            "schema_version": "1.1",
            "project_path": str(original.resolve()),
            "project_name": real_project["project_name"],
            "design_name": real_project["design_name"],
            "allowed_setups": [
                {"setup": real_project["setup"], "sweep": real_project["sweep"]}
            ],
            "parameters": param_specs,
            "allowed_metrics": default_s11_metrics(
                setup=real_project["setup"],
                sweep=real_project["sweep"],
                f_min_ghz=1.0,
                f_max_ghz=3.0,
                f_target_ghz=2.4,
                port="1",
            ),
            "stop_conditions": {
                "max_trials": 1,
                "max_runtime_seconds": 1200.0,
                "metric_targets": {},
            },
            "concurrency": {"mode": "serial", "max_concurrent": 1},
            "checkpoint": {"mode": "every_trial"},
        }
        reg = ctx.register_manifest(manifest_body)
        assert reg["ok"] is True
        mid = reg["manifest_id"]
        evidence["manifest_id"] = mid
        evidence["steps"].append("manifest_validate")

        snap = ctx.design_snapshot(mid)
        assert snap["ok"] is True
        evidence["snapshot_revision"] = snap["snapshot"]["revision"]
        evidence["steps"].append("design_snapshot")

        try:
            ctx.trial_start(
                manifest_id=mid,
                run_id="run_real",
                trial_id="bad",
                idempotency_key="real-bad",
                setup=real_project["setup"],
                sweep=real_project["sweep"],
                parameters={"values": bad_values},
            )
            raise AssertionError("expected policy rejection")
        except Exception as exc:
            assert getattr(exc, "code", "") == "out_of_range"
            evidence["steps"].append("policy_reject_oob")

        start = ctx.trial_start(
            manifest_id=mid,
            run_id="run_real",
            trial_id="trial_real_1",
            idempotency_key="real-trial-1",
            setup=real_project["setup"],
            sweep=real_project["sweep"],
            parameters={"values": values},
        )
        assert start["ok"] is True
        job_id = start["job_id"]
        evidence["job_id"] = job_id
        evidence["run_id"] = start["run_id"]
        evidence["steps"].append("trial_start")
        assert start["state"] in {"queued", "running", "completed"}

        deadline = time.time() + 1200
        last_state = None
        while time.time() < deadline:
            st = ctx.trial_status(job_id)
            last_state = st["job"]["state"]
            if last_state in {
                JobState.COMPLETED.value,
                JobState.FAILED.value,
                JobState.CANCELLED.value,
                JobState.INTERRUPTED.value,
            }:
                break
            time.sleep(3.0)

        evidence["final_state"] = last_state
        # Include worker log tail for debugging
        log_path = data_dir / "workspace" / "worker_logs" / f"{job_id}.log"
        if log_path.is_file():
            evidence["worker_log_tail"] = log_path.read_text(
                encoding="utf-8", errors="replace"
            )[-4000:]

        result = ctx.trial_result(job_id)
        evidence["result"] = result.get("result")
        evidence["error"] = result.get("error")
        assert result["state"] == "completed", f"job failed: {result}"
        metrics = result["result"]["metrics"]
        assert "S11_min_dB" in metrics
        assert "S11_min_freq_GHz" in metrics
        assert "S11_at_target_dB" in metrics
        evidence["metrics"] = metrics
        evidence["steps"].append("solve_and_metrics")

        ck = ctx.checkpoint_list(run_id=start["run_id"])
        assert len(ck["checkpoints"]) >= 1
        evidence["checkpoint"] = ck["checkpoints"][0]
        evidence["steps"].append("checkpoint")

        assert file_sha256(original) == original_hash
        evidence["original_hash_ok"] = True
        evidence["steps"].append("original_hash")

        again = ctx.trial_start(
            manifest_id=mid,
            run_id="run_real",
            trial_id="trial_real_1",
            idempotency_key="real-trial-1",
            setup=real_project["setup"],
            sweep=real_project["sweep"],
            parameters={"values": values},
        )
        assert again["reused"] is True
        assert again["job_id"] == job_id
        evidence["steps"].append("idempotent_reuse")

        conflict = ctx.trial_start(
            manifest_id=mid,
            run_id="run_real",
            trial_id="trial_real_2",
            idempotency_key="real-trial-1",
            setup=real_project["setup"],
            sweep=real_project["sweep"],
            parameters={
                "values": (
                    [{"name": "gap", "value": 1.5, "unit": "mm"}]
                    if param_specs[0]["name"] == "gap"
                    else [
                        {"name": "patch_w", "value": 12.0, "unit": "mm"},
                        {"name": "patch_l", "value": 12.0, "unit": "mm"},
                    ]
                )
            },
        )
        assert conflict.get("ok") is False
        assert conflict["error"]["code"] == "idempotency_conflict"
        evidence["steps"].append("idempotent_conflict")

        ctx.close()
        ctx2 = AppContext(
            data_dir=data_dir,
            use_fake=False,
            inline_trials=False,
            start_supervisor=False,
        )
        try:
            reloaded = ctx2.trial_result(job_id)
            assert reloaded["state"] == "completed"
            assert reloaded["result"]["metrics"]["S11_min_dB"] == metrics["S11_min_dB"]
            evidence["steps"].append("restart_reload")
        finally:
            ctx2.close()
            ctx = None

        evidence_path = Path(
            r"C:\Users\Gongzhui\AppData\Local\Temp\grok-goal-d212e510eac3\implementer\real_aedt_evidence.json"
        )
        evidence_path.write_text(
            json.dumps(evidence, indent=2, default=str), encoding="utf-8"
        )
    finally:
        if ctx is not None:
            ctx.close()
