"""Application context wiring adapters, jobs, checkpoints, and manifests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from hfss_mcp.adapter.fake import FakeAdapter
from hfss_mcp.adapter.protocol import AedtAdapter
from hfss_mcp.checkpoint import CheckpointService
from hfss_mcp.domain import ParameterVector
from hfss_mcp.environment import EnvironmentStatus, inspect_environment
from hfss_mcp.errors import HfssMcpError, JobError, PolicyError
from hfss_mcp.ids import new_id
from hfss_mcp.jobs.runner import TrialRunner, submit_trial
from hfss_mcp.jobs.store import JobStore
from hfss_mcp.manifest import TuneManifest, load_manifest
from hfss_mcp.policy import explain_manifest, validate_manifest_dict, validate_trial_request


def default_data_dir() -> Path:
    env = os.environ.get("HFSS_MCP_DATA_DIR")
    if env:
        return Path(env)
    return Path.home() / ".hfss-mcp"


class AppContext:
    """Process-local application services shared by MCP tools."""

    def __init__(
        self,
        *,
        data_dir: Path | None = None,
        adapter: AedtAdapter | None = None,
        use_fake: bool = True,
        inline_trials: bool = True,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = JobStore(self.data_dir / "jobs.sqlite3")
        self.checkpoints = CheckpointService(self.data_dir / "workspace")
        self.use_fake = use_fake
        self.inline_trials = inline_trials
        self._manifests: dict[str, TuneManifest] = {}
        if adapter is not None:
            self.adapter: AedtAdapter = adapter
        elif use_fake:
            self.adapter = FakeAdapter()
        else:
            from hfss_mcp.adapter.pyaedt_adapter import PyAedtAdapter

            self.adapter = PyAedtAdapter()
        self.runner = TrialRunner(self.store, self.adapter, self.checkpoints)

    def close(self) -> None:
        try:
            self.adapter.disconnect(close_desktop=False)
        finally:
            self.store.close()

    def environment_status(self) -> dict[str, Any]:
        status: EnvironmentStatus = inspect_environment()
        payload = status.to_public_dict()
        payload["adapter"] = "fake" if isinstance(self.adapter, FakeAdapter) else "pyaedt"
        payload["data_dir"] = str(self.data_dir)
        return payload

    def register_manifest(self, data: dict[str, Any]) -> dict[str, Any]:
        manifest = validate_manifest_dict(data)
        mid = manifest.manifest_id()
        self._manifests[mid] = manifest
        return explain_manifest(manifest)

    def get_manifest(self, manifest_id: str) -> TuneManifest:
        if manifest_id in self._manifests:
            return self._manifests[manifest_id]
        raise PolicyError(
            "manifest not registered in this process; call manifest_validate first",
            code="manifest_not_registered",
            details={"manifest_id": manifest_id},
        )

    def design_snapshot(self, manifest_id: str) -> dict[str, Any]:
        manifest = self.get_manifest(manifest_id)
        snap = self.adapter.attach_project(Path(manifest.project_path), manifest.design_name)
        return {
            "ok": True,
            "manifest_id": manifest_id,
            "snapshot": snap.model_dump(mode="json"),
        }

    def trial_start(
        self,
        *,
        manifest_id: str,
        run_id: str | None,
        trial_id: str | None,
        idempotency_key: str,
        setup: str,
        sweep: str | None,
        parameters: dict[str, Any],
        expected_revision: str | None = None,
    ) -> dict[str, Any]:
        manifest = self.get_manifest(manifest_id)
        vector = ParameterVector.model_validate(parameters)
        validate_trial_request(
            manifest,
            manifest_id=manifest_id,
            setup=setup,
            sweep=sweep,
            parameters=vector,
        )
        rid = run_id or new_id("run_")
        tid = trial_id or new_id("trial_")
        prior = self.store.get_by_idempotency(idempotency_key)
        job = submit_trial(
            self.store,
            self.runner,
            manifest,
            run_id=rid,
            trial_id=tid,
            idempotency_key=idempotency_key,
            setup=setup,
            sweep=sweep,
            parameters=vector,
            expected_revision=expected_revision,
            inline=self.inline_trials,
        )
        return {
            "ok": True,
            "job_id": job.job_id,
            "run_id": job.run_id,
            "trial_id": job.trial_id,
            "manifest_id": job.manifest_id,
            "idempotency_key": job.idempotency_key,
            "state": job.state.value,
            "reused": prior is not None,
            "job": job.model_dump(mode="json"),
        }

    def trial_status(self, job_id: str) -> dict[str, Any]:
        job = self.store.get(job_id)
        if job is None:
            raise JobError(
                f"job not found: {job_id}",
                code="job_not_found",
                details={"job_id": job_id},
            )
        return {"ok": True, "job": job.model_dump(mode="json")}

    def trial_result(self, job_id: str) -> dict[str, Any]:
        job = self.store.get(job_id)
        if job is None:
            raise JobError(
                f"job not found: {job_id}",
                code="job_not_found",
                details={"job_id": job_id},
            )
        return {
            "ok": True,
            "state": job.state.value,
            "result": job.result_payload,
            "error": job.error,
            "job": job.model_dump(mode="json"),
        }

    def trial_cancel(self, job_id: str) -> dict[str, Any]:
        job = self.store.request_cancel(job_id)
        return {"ok": True, "job": job.model_dump(mode="json")}

    def checkpoint_list(
        self,
        *,
        run_id: str | None = None,
        manifest_id: str | None = None,
    ) -> dict[str, Any]:
        items = self.checkpoints.list_checkpoints(run_id=run_id, manifest_id=manifest_id)
        return {
            "ok": True,
            "checkpoints": [c.model_dump(mode="json") for c in items],
        }


def error_envelope(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, HfssMcpError):
        return exc.to_dict()
    return {
        "ok": False,
        "error": {
            "code": "internal_error",
            "message": str(exc),
            "details": {"type": type(exc).__name__},
        },
    }


def build_manifest_for_tests(
    project_path: Path,
    *,
    parameters: list[dict[str, Any]] | None = None,
) -> TuneManifest:
    """Helper used by tests and smoke scripts."""
    data: dict[str, Any] = {
        "schema_version": "1.0",
        "project_path": str(project_path.resolve(strict=False)),
        "project_name": project_path.stem,
        "design_name": "HFSSDesign1",
        "allowed_setups": [{"setup": "Setup1", "sweep": None}],
        "parameters": parameters
        or [
            {"name": "patch_w", "unit": "mm", "min": 1.0, "max": 50.0},
            {"name": "patch_l", "unit": "mm", "min": 1.0, "max": 50.0},
        ],
        "allowed_metrics": ["S11_dB", "Gain_dBi"],
        "stop_conditions": {"max_trials": 10, "max_runtime_seconds": 30.0},
        "concurrency": {"mode": "serial", "max_concurrent": 1},
        "checkpoint": {"mode": "before_first_mutation"},
    }
    return load_manifest(data)
