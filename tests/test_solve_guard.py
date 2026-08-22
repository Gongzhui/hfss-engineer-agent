"""Calls that AEDT would defer behind a running sweep must fail fast.

Regression for the 2026-08-22 exam incident: variables_set issued after
parametric_start was deferred by AEDT until the sweep ended; every later
call (including analyze_status polls) queued behind it in AEDT's COM FIFO
and the agent went blind for 2h45m.
"""

from __future__ import annotations

import pytest

from hfss_mcp.app import AppContext, build_allowlist_for_tests
from hfss_mcp.domain import JobState, utc_now_iso
from hfss_mcp.errors import JobError


def _fake_running_job(ctx: AppContext) -> None:
    ctx._jobs["job_test_running"] = {
        "job_id": "job_test_running",
        "kind": "parametric",
        "state": JobState.RUNNING.value,
        "setup": "R1",
        "created_at": utc_now_iso(),
        "started_at": utc_now_iso(),
        "finished_at": None,
        "error": None,
    }


def test_mutations_fail_fast_while_solve_running(tmp_path, project_file) -> None:
    ctx = AppContext(data_dir=tmp_path / "data", use_fake=True)
    try:
        ctx.allowlist_load(
            allowlist=build_allowlist_for_tests(project_file).model_dump(
                mode="json", by_alias=True
            )
        )
        _fake_running_job(ctx)
        with pytest.raises(JobError) as ei:
            ctx.variables_set([{"name": "patch_w", "value": 11.0, "unit": "mm"}])
        assert ei.value.code == "solve_in_progress"
        with pytest.raises(JobError):
            ctx.parametric_create(
                name="R2",
                sweeps=[{"variable": "patch_w", "values": [10.0, 11.0]}],
            )
        with pytest.raises(JobError):
            ctx.report_create("modal_s", name="S11")
        # status polling stays available during the solve
        status = ctx.analyze_status("job_test_running")
        assert status["ok"] is True and status["done"] is False
    finally:
        ctx.close()


def test_mutations_allowed_after_solve_done(tmp_path, project_file) -> None:
    ctx = AppContext(data_dir=tmp_path / "data", use_fake=True)
    try:
        ctx.allowlist_load(
            allowlist=build_allowlist_for_tests(project_file).model_dump(
                mode="json", by_alias=True
            )
        )
        _fake_running_job(ctx)
        ctx._jobs["job_test_running"]["state"] = JobState.COMPLETED.value
        out = ctx.variables_set([{"name": "patch_w", "value": 11.0, "unit": "mm"}])
        assert out["ok"] is True
    finally:
        ctx.close()
