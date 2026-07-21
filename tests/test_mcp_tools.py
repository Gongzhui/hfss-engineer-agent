"""MCP tool surface schema/smoke and forbidden tool checks."""

from __future__ import annotations

import time
from pathlib import Path

from hfss_mcp.app import AppContext, build_manifest_for_tests
from hfss_mcp.server import (
    FORBIDDEN_TOOL_NAMES,
    PUBLIC_TOOL_NAMES,
    checkpoint_list,
    design_snapshot,
    environment_status,
    health,
    list_registered_tool_names,
    manifest_validate,
    set_app,
    trial_cancel,
    trial_result,
    trial_start,
    trial_status,
)


def test_public_tools_registered() -> None:
    names = set(list_registered_tool_names())
    for required in PUBLIC_TOOL_NAMES:
        assert required in names, f"missing tool {required}"


def test_forbidden_tools_absent() -> None:
    names = set(list_registered_tool_names())
    for banned in FORBIDDEN_TOOL_NAMES:
        assert banned not in names
    joined = " ".join(names).lower()
    assert "run_python" not in joined
    assert "exec" not in names
    assert "invoke" not in names


def test_tool_smoke_with_injected_app(tmp_path: Path) -> None:
    project = tmp_path / "ant.aedt"
    project.write_bytes(b"FAKE_SOURCE_PROJECT\n")
    ctx = AppContext(
        data_dir=tmp_path / "data",
        use_fake=True,
        inline_trials=True,
        start_supervisor=True,
    )
    set_app(ctx)
    try:
        h = health()
        assert h["ok"] is True
        assert h["adapter"] == "fake"
        assert h["real_hfss_ready"] is False
        assert h["demo_mode"] is True

        env = environment_status()
        assert env["ok"] is True
        assert env["adapter"] == "fake"

        manifest = build_manifest_for_tests(project, sweep=None)
        validated = manifest_validate(manifest.model_dump(mode="json", by_alias=True))
        assert validated["ok"] is True
        mid = validated["manifest_id"]

        snap = design_snapshot(mid)
        assert snap["ok"] is True
        assert snap["snapshot"]["revision"]

        started = trial_start(
            manifest_id=mid,
            idempotency_key="mcp-smoke-1",
            setup="Setup1",
            parameters=[
                {"name": "patch_w", "value": 11.0, "unit": "mm"},
                {"name": "patch_l", "value": 12.5, "unit": "mm"},
            ],
            sweep=None,
            run_id="run_mcp",
            trial_id="trial_mcp",
        )
        assert started["ok"] is True
        job_id = started["job_id"]
        for _ in range(50):
            if trial_status(job_id)["job"]["state"] == "completed":
                break
            time.sleep(0.05)

        status = trial_status(job_id)
        assert status["ok"] is True
        assert status["job"]["state"] == "completed"

        result = trial_result(job_id)
        assert result["ok"] is True
        assert result["result"]["metrics"]

        ck = checkpoint_list(run_id="run_mcp")
        assert ck["ok"] is True
        assert len(ck["checkpoints"]) >= 1

        cancelled = trial_cancel(job_id)
        assert cancelled["ok"] is True
    finally:
        set_app(None)
        ctx.close()


def test_manifest_validate_rejects_bad_path(tmp_path: Path) -> None:
    bad = {
        "schema_version": "1.1",
        "project_path": "not/absolute.aedt",
        "project_name": "x",
        "design_name": "y",
        "allowed_setups": [{"setup": "S1"}],
        "parameters": [{"name": "a", "unit": "mm", "min": 0, "max": 1}],
        "allowed_metrics": [
            {
                "name": "S11_min_dB",
                "kind": "s11_min_in_band",
                "setup": "S1",
                "f_min_ghz": 1.0,
                "f_max_ghz": 2.0,
                "unit": "dB",
            }
        ],
        "stop_conditions": {"max_trials": 1, "max_runtime_seconds": 1.0},
    }
    ctx = AppContext(
        data_dir=tmp_path / "data",
        use_fake=True,
        inline_trials=True,
        start_supervisor=False,
    )
    set_app(ctx)
    try:
        out = manifest_validate(bad)
        assert out["ok"] is False
        assert "error" in out
    finally:
        set_app(None)
        ctx.close()
