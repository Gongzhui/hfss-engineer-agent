"""Progress must return while both RunScript and direct COM are blocked."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from hfss_mcp.app import AppContext, build_allowlist_for_tests
from hfss_mcp.domain import JobState


class BlockedLive:
    project_name = "DemoAntenna"
    design_name = "HFSSDesign1"
    process_id = 42

    def __init__(self) -> None:
        self.solve_release = threading.Event()
        self.messages_release = threading.Event()
        self.messages_entered = threading.Event()
        self.message_calls = 0

    def analyze(self, _setup: str) -> None:
        assert self.solve_release.wait(5)

    analyze_parametric = analyze

    def read_messages(self, **_kwargs: Any) -> list[str]:
        self.message_calls += 1
        self.messages_entered.set()
        assert self.messages_release.wait(5)
        return ["Normal completion of simulation"]


def bounded(call: Callable[[], Any]) -> Any:
    values: list[Any] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            values.append(call())
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(0.5)
    assert not thread.is_alive(), "Progress/start waited for the blocked AEDT call"
    assert not errors, errors
    return values[0]


@pytest.mark.parametrize("kind", ["analyze", "parametric"])
def test_start_and_poll_while_com_blocked(
    tmp_path: Path, project_file: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    ctx = AppContext(data_dir=tmp_path / "data", use_fake=True)
    ctx.allowlist_load(allowlist=build_allowlist_for_tests(project_file).model_dump(mode="json"))
    ctx.config = replace(ctx.config, adapter="pyaedt", demo_mode=False)
    live = BlockedLive()
    assert ctx._allowlist is not None
    live.project_name = ctx._allowlist.project_name
    live.design_name = ctx._allowlist.design_name
    live.project_path = str(project_file)
    allowlist = ctx._allowlist
    monkeypatch.setattr(ctx, "_require_allowlist", lambda: allowlist)
    monkeypatch.setattr(ctx, "_live", live)
    monkeypatch.setattr(ctx, "_ensure_session", lambda **_kw: None)
    monkeypatch.setattr(ctx, "_variable_floats", lambda: {"patch_w": 10.0})
    monkeypatch.setattr(
        ctx,
        "_optimetrics_setups",
        lambda: [{"name": "R1", "setup_kind": "parametric", "has_result": True}],
    )
    try:
        start = bounded(
            lambda: ctx.analyze_start("Setup1") if kind == "analyze" else ctx.parametric_start("R1")
        )
        job_id = start["job_id"]
        assert live.messages_entered.wait(0.5)
        # Simulate GUI discovery queued behind the solve's RunScript lock.
        monkeypatch.setattr(ctx, "_ensure_session", lambda **_kw: live.solve_release.wait(5))
        for _ in range(20):
            result = bounded(lambda: ctx.analyze_status(job_id))
            assert result["done"] is False
            assert result["state_verified"] is True
            assert result["messages_refresh_pending"] is True
        assert live.message_calls == 1  # never pile up blocked COM readers
        result["job"]["state"] = "completed"
        assert ctx._jobs[job_id]["state"] == "running"  # detached response snapshot
        live.messages_release.set()
        live.solve_release.set()
        assert ctx._analyze_thread is not None
        ctx._analyze_thread.join(1)
        final = bounded(lambda: ctx.analyze_status(job_id))
        assert final["done"] is True
        assert final["job"]["state"] == "completed"
    finally:
        live.solve_release.set()
        live.messages_release.set()
        if ctx._analyze_thread:
            ctx._analyze_thread.join(1)
        ctx.close()


def test_restored_job_never_uses_partial_results_or_follows_other_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = AppContext(data_dir=tmp_path, use_fake=True)
    job = writer._new_job_record(kind="parametric", setup="R1")
    writer._jobs[job["job_id"]] = job
    writer._persist_jobs()
    reader = AppContext(data_dir=tmp_path, use_fake=False)
    calls: list[str] = []
    monkeypatch.setattr(reader, "_ensure_session", lambda **_kw: calls.append("attach"))
    monkeypatch.setattr(
        reader,
        "_optimetrics_setups",
        lambda: calls.append("tree") or [{"name": "R1", "has_result": True}],
    )
    try:
        result = bounded(lambda: reader.analyze_status(job["job_id"]))
        assert not result["done"] and not result["state_verified"]
        assert result["status_source"] == "persisted"
        assert "recovery_hint" in result
        assert calls == []
        writer._finish_job(job, state=JobState.COMPLETED.value)
        refreshed = bounded(lambda: reader.analyze_status(job["job_id"]))
        assert refreshed["done"] and refreshed["state_verified"]
    finally:
        reader.close()
        writer.close()


def test_finished_worker_preserves_failure_messages(tmp_path: Path) -> None:
    ctx = AppContext(data_dir=tmp_path, use_fake=True)
    job = ctx._new_job_record(kind="parametric", setup="R1")
    ctx._jobs[job["job_id"]] = job
    try:
        ctx._finish_job(
            job, state=JobState.COMPLETED.value, messages=["[error] Solver process was terminated"]
        )
        assert ctx.analyze_status(job["job_id"])["job"]["state"] == "failed"
    finally:
        ctx.close()


def test_restored_progress_binds_job_not_active_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = AppContext(data_dir=tmp_path, use_fake=False)
    live = BlockedLive()
    live.messages_release.set()
    calls: list[dict[str, Any]] = []

    def attach(**kwargs: Any) -> BlockedLive:
        calls.append(kwargs)
        return live

    monkeypatch.setattr("hfss_mcp.app.attach_live", attach)
    job = {
        "job_id": "old_job",
        "state": "running",
        "setup": "R1",
        "project": live.project_name,
        "design": live.design_name,
        "process_id": 42,
        "kind": "parametric",
    }
    ctx._jobs["old_job"] = job
    try:
        out = bounded(lambda: ctx.analyze_status("old_job"))
        assert not out["done"] and not out["state_verified"]
        assert ctx._progress_thread is not None
        ctx._progress_thread.join(1)
        out = bounded(lambda: ctx.analyze_status("old_job"))
        assert out["messages_updated_at"]
        assert out["messages"] == ["Normal completion of simulation"]
        assert not out["done"]  # a historical message cannot finish this job
        assert calls == [
            {
                "version": "2023.2",
                "process_id": 42,
                "project_name": live.project_name,
                "design_name": live.design_name,
            }
        ]
        assert ctx._live is None  # status must not switch the user's active bind
    finally:
        ctx.close()
