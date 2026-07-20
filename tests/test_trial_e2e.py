"""FakeAdapter end-to-end trial via AppContext / runner."""

from __future__ import annotations

from pathlib import Path

from hfss_mcp.adapter.fake import FakeAdapter
from hfss_mcp.app import AppContext, build_manifest_for_tests
from hfss_mcp.checkpoint import CheckpointService
from hfss_mcp.domain import JobState, ParameterValue, ParameterVector
from hfss_mcp.jobs.runner import TrialRunner, submit_trial
from hfss_mcp.jobs.store import JobStore


def test_fake_adapter_e2e_trial(tmp_path: Path, project_file: Path) -> None:
    adapter = FakeAdapter(
        project_path=project_file,
        variables={
            "patch_w": ParameterValue(name="patch_w", value=10.0, unit="mm"),
            "patch_l": ParameterValue(name="patch_l", value=12.0, unit="mm"),
        },
        solve_duration_s=0.01,
    )
    store = JobStore(tmp_path / "jobs.sqlite3")
    ckpt = CheckpointService(tmp_path / "ws")
    runner = TrialRunner(store, adapter, ckpt, poll_interval_s=0.01)
    manifest = build_manifest_for_tests(project_file)

    vector = ParameterVector(
        values=[
            ParameterValue(name="patch_w", value=15.0, unit="mm"),
            ParameterValue(name="patch_l", value=14.0, unit="mm"),
        ]
    )
    job = submit_trial(
        store,
        runner,
        manifest,
        run_id="run_e2e",
        trial_id="trial_1",
        idempotency_key="e2e-key-1",
        setup="Setup1",
        sweep=None,
        parameters=vector,
        inline=True,
    )
    assert job.state == JobState.COMPLETED
    assert job.result_payload is not None
    assert "metrics" in job.result_payload
    assert "S11_dB" in job.result_payload["metrics"]
    assert job.result_payload["checkpoint"]["sha256"]
    assert Path(job.result_payload["checkpoint"]["checkpoint_path"]).is_file()
    # Original project not overwritten
    assert project_file.read_bytes() == b"FAKE_SOURCE_PROJECT\n"
    store.close()


def test_e2e_via_app_context(app_ctx: AppContext, sample_manifest, project_file: Path) -> None:
    reg = app_ctx.register_manifest(sample_manifest.model_dump(mode="json", by_alias=True))
    mid = reg["manifest_id"]
    # Ensure fake adapter has matching variables/setups after attach path
    start = app_ctx.trial_start(
        manifest_id=mid,
        run_id="runA",
        trial_id="trialA",
        idempotency_key="app-key-1",
        setup="Setup1",
        sweep=None,
        parameters={
            "values": [
                {"name": "patch_w", "value": 16.0, "unit": "mm"},
                {"name": "patch_l", "value": 13.0, "unit": "mm"},
            ]
        },
    )
    assert start["ok"] is True
    assert start["state"] == "completed"
    result = app_ctx.trial_result(start["job_id"])
    assert result["state"] == "completed"
    assert result["result"]["metrics"]["Gain_dBi"] is not None

    # Idempotent resubmit
    again = app_ctx.trial_start(
        manifest_id=mid,
        run_id="runA",
        trial_id="trialA",
        idempotency_key="app-key-1",
        setup="Setup1",
        sweep=None,
        parameters={
            "values": [
                {"name": "patch_w", "value": 16.0, "unit": "mm"},
                {"name": "patch_l", "value": 13.0, "unit": "mm"},
            ]
        },
    )
    assert again["reused"] is True
    assert again["job_id"] == start["job_id"]

    ckpts = app_ctx.checkpoint_list(run_id="runA")
    assert len(ckpts["checkpoints"]) >= 1


def test_policy_blocks_before_job(app_ctx: AppContext, sample_manifest) -> None:
    reg = app_ctx.register_manifest(sample_manifest.model_dump(mode="json", by_alias=True))
    mid = reg["manifest_id"]
    out = None
    try:
        app_ctx.trial_start(
            manifest_id=mid,
            run_id="runB",
            trial_id="trialB",
            idempotency_key="bad-key",
            setup="Setup1",
            sweep=None,
            parameters={
                "values": [
                    {"name": "patch_w", "value": 999.0, "unit": "mm"},
                    {"name": "patch_l", "value": 13.0, "unit": "mm"},
                ]
            },
        )
        raised = False
    except Exception as exc:
        raised = True
        out = exc
    assert raised
    assert getattr(out, "code", "") == "out_of_range"
