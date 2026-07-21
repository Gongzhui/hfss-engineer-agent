"""FakeAdapter end-to-end trial via AppContext / worker path."""

from __future__ import annotations

import time
from pathlib import Path

from hfss_mcp.app import AppContext, build_manifest_for_tests
from hfss_mcp.ids import file_sha256


def test_fake_adapter_e2e_trial(tmp_path: Path, project_file: Path) -> None:
    original_hash = file_sha256(project_file)
    ctx = AppContext(
        data_dir=tmp_path / "data",
        use_fake=True,
        inline_trials=True,
        start_supervisor=True,
    )
    try:
        manifest = build_manifest_for_tests(project_file, sweep=None)
        reg = ctx.register_manifest(manifest.model_dump(mode="json", by_alias=True))
        mid = reg["manifest_id"]
        start = ctx.trial_start(
            manifest_id=mid,
            run_id="run_e2e",
            trial_id="trial_1",
            idempotency_key="e2e-key-1",
            setup="Setup1",
            sweep=None,
            parameters={
                "values": [
                    {"name": "patch_w", "value": 15.0, "unit": "mm"},
                    {"name": "patch_l", "value": 14.0, "unit": "mm"},
                ]
            },
        )
        assert start["ok"] is True
        # inline fake completes immediately
        job_id = start["job_id"]
        # wait briefly if needed
        for _ in range(50):
            st = ctx.trial_status(job_id)
            if st["job"]["state"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.05)
        result = ctx.trial_result(job_id)
        assert result["state"] == "completed"
        assert result["result"] is not None
        assert "metrics" in result["result"]
        assert "S11_min_dB" in result["result"]["metrics"]
        assert file_sha256(project_file) == original_hash
        assert project_file.read_bytes() == b"FAKE_SOURCE_PROJECT\n"
    finally:
        ctx.close()


def test_e2e_via_app_context(app_ctx: AppContext, sample_manifest, project_file: Path) -> None:
    reg = app_ctx.register_manifest(sample_manifest.model_dump(mode="json", by_alias=True))
    mid = reg["manifest_id"]
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
    for _ in range(50):
        if app_ctx.trial_status(start["job_id"])["job"]["state"] == "completed":
            break
        time.sleep(0.05)
    result = app_ctx.trial_result(start["job_id"])
    assert result["state"] == "completed"
    assert result["result"]["metrics"]

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

    conflict = app_ctx.trial_start(
        manifest_id=mid,
        run_id="runA",
        trial_id="trialB",
        idempotency_key="app-key-1",
        setup="Setup1",
        sweep=None,
        parameters={
            "values": [
                {"name": "patch_w", "value": 17.0, "unit": "mm"},
                {"name": "patch_l", "value": 13.0, "unit": "mm"},
            ]
        },
    )
    assert conflict.get("ok") is False
    assert conflict["error"]["code"] == "idempotency_conflict"

    ckpts = app_ctx.checkpoint_list(run_id="runA")
    assert len(ckpts["checkpoints"]) >= 1


def test_policy_blocks_before_job(app_ctx: AppContext, sample_manifest) -> None:
    reg = app_ctx.register_manifest(sample_manifest.model_dump(mode="json", by_alias=True))
    mid = reg["manifest_id"]
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
        out = None
    except Exception as exc:
        raised = True
        out = exc
    assert raised
    assert getattr(out, "code", "") == "out_of_range"


def test_run_seeded_random_offline(app_ctx: AppContext, sample_manifest) -> None:
    reg = app_ctx.register_manifest(sample_manifest.model_dump(mode="json", by_alias=True))
    mid = reg["manifest_id"]
    # lower max trials via re-register is hard; use stop conditions from manifest (10)
    # Override by building tighter manifest
    body = sample_manifest.model_dump(mode="json", by_alias=True)
    body["stop_conditions"]["max_trials"] = 2
    body["stop_conditions"]["max_runtime_seconds"] = 60
    body["stop_conditions"]["metric_targets"] = {}
    reg2 = app_ctx.register_manifest(body)
    mid = reg2["manifest_id"]
    started = app_ctx.run_start(
        manifest_id=mid,
        idempotency_key="run-opt-1",
        strategy="seeded_random",
        seed=42,
    )
    assert started["ok"] is True
    run_id = started["run"]["run_id"]
    for _ in range(200):
        st = app_ctx.run_status(run_id)
        if st["run"]["state"] in {
            "completed",
            "failed",
            "cancelled",
            "requires_recovery",
        }:
            break
        time.sleep(0.1)
    final = app_ctx.run_result(run_id)
    assert final["run"]["state"] == "completed"
    assert final["run"]["trials_completed"] >= 1
