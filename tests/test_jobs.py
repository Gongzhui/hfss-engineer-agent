"""Durable job store: transitions, idempotency hash, restart recovery, cancel."""

from __future__ import annotations

from pathlib import Path

import pytest

from hfss_mcp.domain import JobState
from hfss_mcp.errors import JobError
from hfss_mcp.jobs.store import JobStore


def test_job_state_transitions(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = store.create_job(
        idempotency_key="k1",
        run_id="run1",
        trial_id="t1",
        manifest_id="m1",
        input_payload={"x": 1},
    )
    assert job.state == JobState.QUEUED
    running = store.transition(
        job.job_id,
        JobState.RUNNING,
        expected_states={JobState.QUEUED},
    )
    assert running.state == JobState.RUNNING
    assert running.started_at is not None
    done = store.transition(
        job.job_id,
        JobState.COMPLETED,
        expected_states={JobState.RUNNING},
        result_payload={"metrics": {"S11_min_dB": -10.0}},
    )
    assert done.state == JobState.COMPLETED
    assert done.finished_at is not None
    assert done.result_payload == {"metrics": {"S11_min_dB": -10.0}}
    store.close()


def test_idempotency_returns_same_job(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    j1 = store.create_job(
        idempotency_key="same-key",
        run_id="run1",
        trial_id="t1",
        manifest_id="m1",
        input_payload={"a": 1},
    )
    j2 = store.create_job(
        idempotency_key="same-key",
        run_id="run2",
        trial_id="t2",
        manifest_id="m1",
        input_payload={"a": 1},
    )
    assert j1.job_id == j2.job_id
    assert j2.run_id == "run1"
    store.close()


def test_idempotency_conflict_different_payload(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    store.create_job(
        idempotency_key="same-key",
        run_id="run1",
        trial_id="t1",
        manifest_id="m1",
        input_payload={"a": 1},
    )
    with pytest.raises(JobError) as exc:
        store.create_job(
            idempotency_key="same-key",
            run_id="run2",
            trial_id="t2",
            manifest_id="m1",
            input_payload={"a": 2},
        )
    assert exc.value.code == "idempotency_conflict"
    store.close()


def test_restart_reloads_jobs(tmp_path: Path) -> None:
    db = tmp_path / "jobs.sqlite3"
    store1 = JobStore(db)
    job = store1.create_job(
        idempotency_key="persist",
        run_id="run1",
        trial_id="t1",
        manifest_id="m1",
        input_payload={"p": True},
    )
    store1.transition(job.job_id, JobState.COMPLETED, expected_states={JobState.QUEUED})
    store1.close()

    store2 = JobStore(db)
    loaded = store2.get(job.job_id)
    assert loaded is not None
    assert loaded.state == JobState.COMPLETED
    assert loaded.input_payload["p"] is True
    store2.close()


def test_running_becomes_interrupted_on_recover(tmp_path: Path) -> None:
    db = tmp_path / "jobs.sqlite3"
    store1 = JobStore(db)
    job = store1.create_job(
        idempotency_key="run-key",
        run_id="run1",
        trial_id="t1",
        manifest_id="m1",
        input_payload={},
    )
    store1.transition(job.job_id, JobState.RUNNING, expected_states={JobState.QUEUED})
    store1.close()

    store2 = JobStore(db)
    loaded = store2.get(job.job_id)
    assert loaded is not None
    assert loaded.state == JobState.INTERRUPTED
    assert loaded.error is not None
    assert loaded.error["code"] == "interrupted_on_restart"
    store2.close()


def test_cancel_queued(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = store.create_job(
        idempotency_key="cq",
        run_id="r",
        trial_id="t",
        manifest_id="m",
        input_payload={},
    )
    cancelled = store.request_cancel(job.job_id)
    assert cancelled.state == JobState.CANCELLED
    store.close()


def test_cancel_running_marks_cancel_requested(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = store.create_job(
        idempotency_key="cr",
        run_id="r",
        trial_id="t",
        manifest_id="m",
        input_payload={},
    )
    store.transition(job.job_id, JobState.RUNNING, expected_states={JobState.QUEUED})
    requested = store.request_cancel(job.job_id)
    assert requested.state == JobState.CANCEL_REQUESTED
    store.close()


def test_atomic_claim(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite3")
    store.create_job(
        idempotency_key="c1",
        run_id="r",
        trial_id="t",
        manifest_id="m",
        input_payload={},
    )
    claimed = store.claim_next_job(worker_pid=1234)
    assert claimed is not None
    assert claimed.state == JobState.RUNNING
    assert store.claim_next_job(worker_pid=99) is None
    store.close()
