"""Background trial runner: policy → checkpoint → apply → solve → metrics."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hfss_mcp.adapter.protocol import AedtAdapter
from hfss_mcp.checkpoint import CheckpointService
from hfss_mcp.domain import (
    JobRecord,
    JobState,
    ParameterVector,
    SolveHandle,
    SolveState,
    TrialResult,
    utc_now_iso,
)
from hfss_mcp.errors import HfssMcpError, PolicyError
from hfss_mcp.jobs.store import JobStore
from hfss_mcp.manifest import TuneManifest
from hfss_mcp.policy import validate_trial_request


class TrialRunner:
    """Executes trial jobs against an adapter with durable state updates."""

    def __init__(
        self,
        store: JobStore,
        adapter: AedtAdapter,
        checkpoint_service: CheckpointService,
        *,
        poll_interval_s: float = 0.05,
        solve_timeout_s: float | None = None,
    ) -> None:
        self.store = store
        self.adapter = adapter
        self.checkpoints = checkpoint_service
        self.poll_interval_s = poll_interval_s
        self.solve_timeout_s = solve_timeout_s
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()

    def start_job(self, job: JobRecord, manifest: TuneManifest) -> JobRecord:
        """Schedule execution for a queued job (no-op if already started/terminal)."""
        if job.state != JobState.QUEUED:
            return job
        with self._lock:
            if job.job_id in self._threads and self._threads[job.job_id].is_alive():
                return job

            def target() -> None:
                self._run_trial(job.job_id, manifest)

            thread = threading.Thread(
                target=target,
                name=f"trial-{job.job_id}",
                daemon=True,
            )
            self._threads[job.job_id] = thread
            thread.start()
        return job

    def run_inline(self, job: JobRecord, manifest: TuneManifest) -> JobRecord:
        """Run synchronously (preferred in tests)."""
        self._run_trial(job.job_id, manifest)
        result = self.store.get(job.job_id)
        assert result is not None
        return result

    def _run_trial(self, job_id: str, manifest: TuneManifest) -> None:
        job = self.store.get(job_id)
        if job is None:
            return
        if job.state != JobState.QUEUED:
            return

        self.store.transition(
            job_id,
            JobState.RUNNING,
            expected_states={JobState.QUEUED},
        )

        try:
            payload = job.input_payload
            vector = ParameterVector.model_validate(payload["parameters"])
            setup = str(payload["setup"])
            sweep = payload.get("sweep")
            sweep_s = str(sweep) if sweep is not None else None
            expected_revision = payload.get("expected_revision")

            validate_trial_request(
                manifest,
                manifest_id=job.manifest_id,
                setup=setup,
                sweep=sweep_s,
                parameters=vector,
            )

            # Attach approved project
            snap = self.adapter.attach_project(
                Path(manifest.project_path),
                manifest.design_name,
            )
            if snap.design_name != manifest.design_name:
                raise PolicyError(
                    "attached design name does not match manifest",
                    code="design_identity_mismatch",
                    details={
                        "expected": manifest.design_name,
                        "actual": snap.design_name,
                    },
                )

            # Checkpoint before first mutation
            ckpt = self.checkpoints.create_checkpoint(
                adapter=self.adapter,
                original_project_path=manifest.project_path,
                manifest_id=job.manifest_id,
                run_id=job.run_id,
                trial_id=job.trial_id,
                notes="auto before first mutation",
            )

            revision = expected_revision or snap.revision
            apply_result = self.adapter.apply_parameter_vector(
                vector,
                expected_revision=str(revision),
            )
            if not apply_result.ok:
                raise HfssMcpError(
                    "parameter apply reported failure",
                    code="apply_failed",
                    details=apply_result.model_dump(mode="json"),
                )

            # Re-check cancel request
            job = self.store.get(job_id)
            assert job is not None
            if job.state == JobState.CANCEL_REQUESTED:
                self.store.transition(
                    job_id,
                    JobState.CANCELLED,
                    expected_states={JobState.CANCEL_REQUESTED},
                    result_payload={
                        "checkpoint": ckpt.model_dump(mode="json"),
                        "apply_diff": [d.model_dump(mode="json") for d in apply_result.diff],
                        "cancelled_phase": "pre_solve",
                    },
                    error={
                        "code": "cancelled",
                        "message": "Cancelled after parameter apply, before solve",
                    },
                )
                return

            validation = self.adapter.validate_design(setup, sweep_s)
            if not validation.get("ok", False):
                raise HfssMcpError(
                    "design/setup validation failed",
                    code="validation_failed",
                    details=dict(validation),
                )

            handle = self.adapter.start_solve(setup, sweep_s)
            final_status = self._wait_solve(job_id, handle, manifest)

            if final_status.state == SolveState.CANCELLED:
                self.store.transition(
                    job_id,
                    JobState.CANCELLED,
                    expected_states={
                        JobState.RUNNING,
                        JobState.CANCEL_REQUESTED,
                    },
                    result_payload={
                        "checkpoint": ckpt.model_dump(mode="json"),
                        "apply_diff": [d.model_dump(mode="json") for d in apply_result.diff],
                        "solve": final_status.model_dump(mode="json"),
                        "revision_before": apply_result.revision_before,
                        "revision_after": apply_result.revision_after,
                    },
                    error={"code": "cancelled", "message": "Solve cancelled"},
                    artifact_paths={"checkpoint": ckpt.checkpoint_path},
                )
                return

            if final_status.state != SolveState.COMPLETED:
                raise HfssMcpError(
                    f"solve ended in state {final_status.state.value}",
                    code="solve_failed",
                    details=final_status.model_dump(mode="json"),
                )

            metrics = self.adapter.extract_metrics(list(manifest.allowed_metrics))

            trial_result = TrialResult(
                trial_id=job.trial_id,
                run_id=job.run_id,
                manifest_id=job.manifest_id,
                job_id=job_id,
                state=JobState.COMPLETED,
                parameters=vector,
                metrics=metrics,
                apply_diff=apply_result.diff,
                checkpoint=ckpt,
                revision_before=apply_result.revision_before,
                revision_after=apply_result.revision_after,
                artifacts={"checkpoint": ckpt.checkpoint_path},
                started_at=job.started_at,
                finished_at=utc_now_iso(),
            )
            self.store.transition(
                job_id,
                JobState.COMPLETED,
                expected_states={JobState.RUNNING, JobState.CANCEL_REQUESTED},
                result_payload=trial_result.model_dump(mode="json"),
                artifact_paths={"checkpoint": ckpt.checkpoint_path},
            )
        except HfssMcpError as exc:
            self._fail(job_id, exc.to_dict()["error"])
        except Exception as exc:  # noqa: BLE001 — durable failure boundary
            self._fail(
                job_id,
                {
                    "code": "internal_error",
                    "message": str(exc),
                    "details": {"type": type(exc).__name__},
                },
            )

    def _fail(self, job_id: str, error: dict[str, Any]) -> None:
        current = self.store.get(job_id)
        if current is None or current.state in {
            JobState.COMPLETED,
            JobState.CANCELLED,
            JobState.INTERRUPTED,
        }:
            return
        try:
            self.store.transition(
                job_id,
                JobState.FAILED,
                expected_states={
                    JobState.RUNNING,
                    JobState.CANCEL_REQUESTED,
                    JobState.QUEUED,
                },
                error=error,
            )
        except Exception:
            # Last resort: force update without expected_states
            self.store.transition(job_id, JobState.FAILED, error=error)

    def _wait_solve(
        self,
        job_id: str,
        handle: SolveHandle,
        manifest: TuneManifest,
    ) -> Any:
        deadline = None
        timeout = self.solve_timeout_s
        if timeout is None:
            timeout = float(manifest.stop_conditions.max_runtime_seconds)
        if timeout > 0:
            deadline = time.monotonic() + timeout

        while True:
            job = self.store.get(job_id)
            if job is not None and job.state == JobState.CANCEL_REQUESTED:
                cancel = self.adapter.cancel_solve(handle)
                status = self.adapter.query_solve(handle)
                if cancel.cancelled or status.state == SolveState.CANCELLED:
                    return status
                # Honest non-cancel: keep polling until host finishes
                if status.state in {
                    SolveState.COMPLETED,
                    SolveState.FAILED,
                    SolveState.CANCELLED,
                }:
                    return status

            status = self.adapter.query_solve(handle)
            if status.state in {
                SolveState.COMPLETED,
                SolveState.FAILED,
                SolveState.CANCELLED,
            }:
                return status

            if deadline is not None and time.monotonic() >= deadline:
                # Timeout: try cancel, then fail
                self.adapter.cancel_solve(handle)
                status = self.adapter.query_solve(handle)
                if status.state == SolveState.CANCELLED:
                    return status
                raise HfssMcpError(
                    "solve timed out",
                    code="solve_timeout",
                    details=status.model_dump(mode="json"),
                )

            time.sleep(self.poll_interval_s)


def submit_trial(
    store: JobStore,
    runner: TrialRunner,
    manifest: TuneManifest,
    *,
    run_id: str,
    trial_id: str,
    idempotency_key: str,
    setup: str,
    sweep: str | None,
    parameters: ParameterVector,
    expected_revision: str | None = None,
    inline: bool = False,
) -> JobRecord:
    """Create (or reuse) a job and start execution."""
    # Policy gate before any durable enqueue side effects beyond idempotent create
    validate_trial_request(
        manifest,
        manifest_id=manifest.manifest_id(),
        setup=setup,
        sweep=sweep,
        parameters=parameters,
    )
    existing = store.get_by_idempotency(idempotency_key)
    if existing is not None:
        # Never re-mutate or re-solve for a duplicate key
        return existing

    job = store.create_job(
        idempotency_key=idempotency_key,
        run_id=run_id,
        trial_id=trial_id,
        manifest_id=manifest.manifest_id(),
        input_payload={
            "setup": setup,
            "sweep": sweep,
            "parameters": parameters.model_dump(mode="json"),
            "expected_revision": expected_revision,
            "manifest_id": manifest.manifest_id(),
            "run_id": run_id,
            "trial_id": trial_id,
        },
    )
    # create_job itself is idempotent; if we lost a race, do not start twice
    if job.state != JobState.QUEUED:
        return job

    # Detect reuse: if trial_id/run_id differ from request, another writer won — still OK
    if inline:
        return runner.run_inline(job, manifest)
    runner.start_job(job, manifest)
    refreshed = store.get(job.job_id)
    assert refreshed is not None
    return refreshed


# Type for dependency injection in server
AdapterFactory = Callable[[], AedtAdapter]
