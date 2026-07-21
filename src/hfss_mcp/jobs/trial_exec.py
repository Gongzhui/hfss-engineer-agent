"""Execute one trial end-to-end against an exclusive adapter + workspace copy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hfss_mcp.adapter.fake import FakeAdapter
from hfss_mcp.adapter.protocol import AedtAdapter
from hfss_mcp.checkpoint import CheckpointService
from hfss_mcp.domain import JobState, ParameterVector, SolveState, utc_now_iso
from hfss_mcp.errors import HfssMcpError, PolicyError
from hfss_mcp.jobs.store import JobStore
from hfss_mcp.manifest import TuneManifest
from hfss_mcp.policy import validate_trial_request


def assert_project_identity(snap: Any, manifest: TuneManifest) -> None:
    if snap.design_name != manifest.design_name:
        raise PolicyError(
            "attached design name does not match manifest",
            code="design_identity_mismatch",
            details={"expected": manifest.design_name, "actual": snap.design_name},
        )
    # project_name in AEDT may omit path; compare stem-insensitive
    expected = manifest.project_name
    actual = snap.project_name
    if actual != expected and Path(actual).stem != Path(expected).stem:
        # Also accept working copy renamed to same stem
        if Path(snap.project_path).stem != Path(manifest.project_path).stem and Path(
            snap.project_path
        ).stem != expected:
            raise PolicyError(
                "attached project name does not match manifest",
                code="project_identity_mismatch",
                details={"expected": expected, "actual": actual},
            )


def execute_trial(
    *,
    store: JobStore,
    job_id: str,
    manifest: TuneManifest,
    adapter: AedtAdapter,
    checkpoints: CheckpointService,
    working_project: Path,
    original_project: Path,
    original_sha256: str,
    recover_on_failure: bool = True,
) -> dict[str, Any]:
    """Run claimed job; updates store; returns result summary."""
    job = store.get(job_id)
    if job is None:
        raise HfssMcpError(f"job not found {job_id}", code="job_not_found")
    if job.state not in {JobState.RUNNING, JobState.QUEUED}:
        return {"state": job.state.value, "skipped": True}

    if job.state == JobState.QUEUED:
        store.transition(
            job_id,
            JobState.RUNNING,
            expected_states={JobState.QUEUED},
        )

    payload = job.input_payload
    vector = ParameterVector.model_validate(payload["parameters"])
    setup = str(payload["setup"])
    sweep = payload.get("sweep")
    sweep_s = str(sweep) if sweep is not None else None
    expected_revision = payload.get("expected_revision")
    checkpoint_record = None
    apply_result = None

    try:
        validate_trial_request(
            manifest,
            manifest_id=job.manifest_id,
            setup=setup,
            sweep=sweep_s,
            parameters=vector,
        )

        snap = adapter.attach_project(working_project, manifest.design_name)
        assert_project_identity(snap, manifest)

        # Checkpoint before mutation when policy requires
        mode = manifest.checkpoint.mode
        if mode in {"before_first_mutation", "every_trial"}:
            checkpoint_record = checkpoints.create_checkpoint(
                adapter=adapter,
                original_project_path=original_project,
                manifest_id=job.manifest_id,
                run_id=job.run_id,
                trial_id=job.trial_id,
                notes=f"auto {mode}",
                source_file=working_project if working_project.is_file() else None,
            )

        # Cancel check
        job = store.get(job_id)
        assert job is not None
        if job.state == JobState.CANCEL_REQUESTED:
            store.transition(
                job_id,
                JobState.CANCELLED,
                expected_states={JobState.CANCEL_REQUESTED},
                error={"code": "cancelled", "message": "Cancelled before mutation"},
                result_payload={
                    "checkpoint": checkpoint_record.model_dump(mode="json")
                    if checkpoint_record
                    else None
                },
            )
            return {"state": "cancelled"}

        revision = str(expected_revision or snap.revision)
        apply_result = adapter.apply_parameter_vector(vector, expected_revision=revision)
        if not apply_result.ok:
            raise HfssMcpError(
                "parameter apply reported failure",
                code="apply_failed",
                details=apply_result.model_dump(mode="json"),
            )

        job = store.get(job_id)
        assert job is not None
        if job.state == JobState.CANCEL_REQUESTED:
            # restore checkpoint
            if checkpoint_record and recover_on_failure:
                _try_restore(
                    adapter,
                    checkpoints,
                    checkpoint_record.checkpoint_path,
                    working_project,
                )
            store.transition(
                job_id,
                JobState.CANCELLED,
                expected_states={JobState.CANCEL_REQUESTED, JobState.RUNNING},
                error={"code": "cancelled", "message": "Cancelled after apply"},
                result_payload={
                    "checkpoint": checkpoint_record.model_dump(mode="json")
                    if checkpoint_record
                    else None,
                    "apply_diff": [d.model_dump(mode="json") for d in apply_result.diff],
                },
            )
            return {"state": "cancelled"}

        validation = adapter.validate_design(setup, sweep_s)
        if not validation.get("ok", False):
            raise HfssMcpError(
                "design/setup validation failed",
                code="validation_failed",
                details=dict(validation),
            )

        handle = adapter.start_solve(setup, sweep_s)
        # Poll until complete (blocking solves already complete)
        status = adapter.query_solve(handle)
        if status.state == SolveState.RUNNING:
            import time

            deadline = time.monotonic() + float(manifest.stop_conditions.max_runtime_seconds)
            while status.state == SolveState.RUNNING:
                job = store.get(job_id)
                if job is not None and job.state == JobState.CANCEL_REQUESTED:
                    cancel = adapter.cancel_solve(handle)
                    status = adapter.query_solve(handle)
                    if cancel.cancelled or status.state == SolveState.CANCELLED:
                        break
                if time.monotonic() >= deadline:
                    adapter.cancel_solve(handle)
                    raise HfssMcpError(
                        "solve timed out",
                        code="solve_timeout",
                        details=status.model_dump(mode="json"),
                    )
                time.sleep(0.5)
                status = adapter.query_solve(handle)

        if status.state == SolveState.CANCELLED:
            if checkpoint_record and recover_on_failure:
                _try_restore(
                    adapter,
                    checkpoints,
                    checkpoint_record.checkpoint_path,
                    working_project,
                )
            store.transition(
                job_id,
                JobState.CANCELLED,
                expected_states={JobState.RUNNING, JobState.CANCEL_REQUESTED},
                error={"code": "cancelled", "message": "Solve cancelled"},
                result_payload={
                    "solve": status.model_dump(mode="json"),
                    "checkpoint": checkpoint_record.model_dump(mode="json")
                    if checkpoint_record
                    else None,
                },
                artifact_paths={
                    "checkpoint": checkpoint_record.checkpoint_path
                }
                if checkpoint_record
                else {},
            )
            return {"state": "cancelled"}

        if status.state != SolveState.COMPLETED:
            raise HfssMcpError(
                f"solve ended in state {status.state.value}",
                code="solve_failed",
                details=status.model_dump(mode="json"),
            )

        # Metrics
        metrics: dict[str, float]
        if isinstance(adapter, FakeAdapter):
            metrics = adapter.extract_metrics([m.name for m in manifest.allowed_metrics])
        else:
            extract = getattr(adapter, "extract_metric_specs", None)
            if not callable(extract):
                raise HfssMcpError(
                    "adapter cannot extract metric specs",
                    code="metrics_unsupported",
                )
            metrics = extract(list(manifest.allowed_metrics))

        finished_job = store.get(job_id)
        assert finished_job is not None
        result = {
            "trial_id": finished_job.trial_id,
            "run_id": finished_job.run_id,
            "manifest_id": finished_job.manifest_id,
            "job_id": job_id,
            "state": JobState.COMPLETED.value,
            "parameters": vector.model_dump(mode="json"),
            "metrics": metrics,
            "apply_diff": [d.model_dump(mode="json") for d in apply_result.diff],
            "checkpoint": checkpoint_record.model_dump(mode="json")
            if checkpoint_record
            else None,
            "revision_before": apply_result.revision_before,
            "revision_after": apply_result.revision_after,
            "working_project": str(working_project),
            "original_project": str(original_project),
            "original_sha256": original_sha256,
            "finished_at": utc_now_iso(),
        }
        store.transition(
            job_id,
            JobState.COMPLETED,
            expected_states={JobState.RUNNING, JobState.CANCEL_REQUESTED},
            result_payload=result,
            artifact_paths={
                "checkpoint": checkpoint_record.checkpoint_path
            }
            if checkpoint_record
            else {},
        )
        return result

    except Exception as exc:
        error: dict[str, Any]
        if isinstance(exc, HfssMcpError):
            error = exc.to_dict()["error"]
        else:
            error = {
                "code": "internal_error",
                "message": str(exc),
                "details": {"type": type(exc).__name__},
            }
        requires_recovery = False
        if recover_on_failure and checkpoint_record is not None:
            try:
                _try_restore(
                    adapter,
                    checkpoints,
                    checkpoint_record.checkpoint_path,
                    working_project,
                )
                error["recovered_from_checkpoint"] = checkpoint_record.checkpoint_id
            except Exception as rex:  # noqa: BLE001
                requires_recovery = True
                error["recovery_failed"] = str(rex)
        final_state = (
            JobState.FAILED
            if not requires_recovery
            else JobState.FAILED
        )
        result_payload = {
            "requires_recovery": requires_recovery,
            "checkpoint": checkpoint_record.model_dump(mode="json")
            if checkpoint_record
            else None,
            "apply_diff": [d.model_dump(mode="json") for d in apply_result.diff]
            if apply_result is not None
            else [],
        }
        try:
            store.transition(
                job_id,
                final_state,
                expected_states={
                    JobState.RUNNING,
                    JobState.CANCEL_REQUESTED,
                    JobState.QUEUED,
                },
                error=error,
                result_payload=result_payload,
            )
        except Exception:
            store.transition(job_id, JobState.FAILED, error=error)
        return {"state": "failed", "error": error, "requires_recovery": requires_recovery}


def _try_restore(
    adapter: AedtAdapter,
    checkpoints: CheckpointService,
    checkpoint_path: str,
    working_project: Path,
) -> None:
    path = Path(checkpoint_path)
    restore = getattr(adapter, "restore_project_file", None)
    if callable(restore):
        restore(path)
        return
    # Fallback: copy over working project
    import shutil

    if path.is_file() and working_project.parent.exists():
        shutil.copy2(path, working_project)
