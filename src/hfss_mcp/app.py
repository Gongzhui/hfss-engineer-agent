"""Application context: production wiring for durable trials and runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hfss_mcp.adapter.fake import FakeAdapter
from hfss_mcp.checkpoint import CheckpointService
from hfss_mcp.config import RuntimeConfig, load_runtime_config
from hfss_mcp.domain import ParameterVector
from hfss_mcp.environment import inspect_environment
from hfss_mcp.errors import HfssMcpError, JobError, PolicyError
from hfss_mcp.ids import file_sha256, new_id
from hfss_mcp.jobs.store import JobStore
from hfss_mcp.jobs.supervisor import Supervisor
from hfss_mcp.manifest import TuneManifest, default_s11_metrics, load_manifest
from hfss_mcp.policy import explain_manifest, validate_manifest_dict, validate_trial_request
from hfss_mcp.run_optimizer import RunOrchestrator
from hfss_mcp.workspace import WorkspaceService, project_lock_key


class AppContext:
    """Process-local application services shared by MCP tools."""

    def __init__(
        self,
        *,
        data_dir: Path | None = None,
        config: RuntimeConfig | None = None,
        adapter_name: str | None = None,
        use_fake: bool | None = None,
        inline_trials: bool | None = None,
        start_supervisor: bool = True,
    ) -> None:
        if use_fake is True:
            adapter_name = "fake"
        elif use_fake is False:
            adapter_name = "pyaedt"
        self.config = config or load_runtime_config(
            adapter=adapter_name,  # type: ignore[arg-type]
            data_dir=data_dir,
            force_inline=inline_trials,
        )
        self.data_dir = self.config.data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = JobStore(self.data_dir / "jobs.sqlite3")
        self.workspaces = WorkspaceService(self.data_dir / "workspace")
        ckpt_root = self.data_dir / "workspace" / "checkpoints"
        self.checkpoints = CheckpointService(ckpt_root)
        self._manifests: dict[str, TuneManifest] = {}
        self.supervisor = Supervisor(
            self.store, self.config, workspace_root=self.data_dir / "workspace"
        )
        self.orchestrator = RunOrchestrator(
            self.store, self.supervisor, self.workspaces
        )
        if start_supervisor:
            self.supervisor.start()

    def close(self) -> None:
        try:
            self.supervisor.stop(kill_workers=False)
        finally:
            self.store.close()

    def health(self) -> dict[str, Any]:
        env = inspect_environment()
        preferred = env.preferred
        real_ready = (
            self.config.adapter == "pyaedt"
            and preferred is not None
            and preferred.exe_exists
        )
        from hfss_mcp import __version__ as pkg_version

        payload: dict[str, Any] = {
            "ok": True,
            "version": str(pkg_version),
            "mode": "tune_only_v0_real" if self.config.adapter == "pyaedt" else "demo_fake",
            "adapter": self.config.adapter,
            "demo_mode": self.config.demo_mode,
            "real_hfss_ready": real_ready,
            "aedt_version_configured": self.config.aedt_version,
            "connection_mode": (
                "worker_process_exclusive_desktop"
                if self.config.adapter == "pyaedt"
                else "in_process_fake"
            ),
            "inline_trials": self.config.inline_trials,
            "data_dir": str(self.data_dir),
            "environment": env.to_public_dict(),
            "warnings": (
                []
                if real_ready or self.config.adapter == "fake"
                else ["AEDT executable not found; pyaedt adapter will fail until installed"]
            ),
        }
        return payload

    def environment_status(self) -> dict[str, Any]:
        h = self.health()
        env = h["environment"]
        if not isinstance(env, dict):
            env = {}
        payload: dict[str, Any] = dict(env)
        payload["ok"] = True
        payload["adapter"] = h["adapter"]
        payload["real_hfss_ready"] = h["real_hfss_ready"]
        payload["demo_mode"] = h["demo_mode"]
        payload["connection_mode"] = h["connection_mode"]
        payload["data_dir"] = h["data_dir"]
        return payload

    def register_manifest(self, data: dict[str, Any]) -> dict[str, Any]:
        manifest = validate_manifest_dict(data)
        mid = manifest.manifest_id()
        self._manifests[mid] = manifest
        # Persist for workers
        self.store.save_manifest(
            mid, manifest.model_dump(mode="json", by_alias=True)
        )
        # Also write file
        man_dir = self.data_dir / "manifests"
        man_dir.mkdir(parents=True, exist_ok=True)
        (man_dir / f"{mid}.json").write_text(
            json.dumps(manifest.model_dump(mode="json", by_alias=True), indent=2),
            encoding="utf-8",
        )
        return explain_manifest(manifest)

    def get_manifest(self, manifest_id: str) -> TuneManifest:
        if manifest_id in self._manifests:
            return self._manifests[manifest_id]
        body = self.store.get_manifest_body(manifest_id)
        if body is not None:
            m = load_manifest(body)
            self._manifests[manifest_id] = m
            return m
        path = self.data_dir / "manifests" / f"{manifest_id}.json"
        if path.is_file():
            m = load_manifest(json.loads(path.read_text(encoding="utf-8")))
            self._manifests[manifest_id] = m
            return m
        raise PolicyError(
            "manifest not registered; call manifest_validate first",
            code="manifest_not_registered",
            details={"manifest_id": manifest_id},
        )

    def design_snapshot(self, manifest_id: str) -> dict[str, Any]:
        """Read-only snapshot via a short-lived exclusive adapter session."""
        manifest = self.get_manifest(manifest_id)
        # Use workspace temp copy so we never open user project for write
        run_id = new_id("snap_")
        ws = self.workspaces.create_run_workspace(
            run_id=run_id,
            original_project=manifest.project_path,
            project_name=manifest.project_name,
        )
        adapter: Any
        if self.config.adapter == "fake":
            from hfss_mcp.domain import ParameterValue

            adapter = FakeAdapter(
                project_path=ws.working_project,
                project_name=manifest.project_name,
                design_name=manifest.design_name,
                variables={
                    p.name: ParameterValue(
                        name=p.name,
                        value=(p.min_value + p.max_value) / 2,
                        unit=p.unit,
                    )
                    for p in manifest.parameters
                },
                setups=[s.setup for s in manifest.allowed_setups],
            )
        else:
            from hfss_mcp.adapter.pyaedt_adapter import PyAedtAdapter

            adapter = PyAedtAdapter(
                version=self.config.aedt_version,
                non_graphical=self.config.non_graphical,
                new_desktop=True,
                close_on_exit=True,
            )
        try:
            snap = adapter.attach_project(ws.working_project, manifest.design_name)
            if snap.design_name != manifest.design_name:
                raise PolicyError(
                    "design identity mismatch",
                    code="design_identity_mismatch",
                    details={
                        "expected": manifest.design_name,
                        "actual": snap.design_name,
                    },
                )
            if (
                snap.project_name != manifest.project_name
                and Path(snap.project_path).stem != Path(manifest.project_path).stem
            ):
                raise PolicyError(
                    "project identity mismatch",
                    code="project_identity_mismatch",
                    details={
                        "expected": manifest.project_name,
                        "actual": snap.project_name,
                    },
                )
            return {
                "ok": True,
                "manifest_id": manifest_id,
                "snapshot": snap.model_dump(mode="json"),
                "workspace": ws.meta_dict(),
                "original_sha256": ws.original_sha256,
            }
        finally:
            try:
                adapter.disconnect(close_desktop=True)
            except Exception:
                pass

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
        # Ensure workspace for this run
        ws = self.workspaces.create_run_workspace(
            run_id=rid,
            original_project=manifest.project_path,
            project_name=manifest.project_name,
        )
        lock_key = project_lock_key(manifest.project_path)
        input_payload = {
            "setup": setup,
            "sweep": sweep,
            "parameters": vector.model_dump(mode="json"),
            "expected_revision": expected_revision,
            "manifest_id": manifest_id,
            "run_id": rid,
            "trial_id": tid,
            "working_project": str(ws.working_project),
            "original_project": str(ws.original_project),
            "original_sha256": ws.original_sha256,
            "project_lock": lock_key,
        }
        prior = self.store.get_by_idempotency(idempotency_key)
        try:
            job = self.store.create_job(
                idempotency_key=idempotency_key,
                run_id=rid,
                trial_id=tid,
                manifest_id=manifest_id,
                input_payload=input_payload,
                project_lock=lock_key,
            )
        except JobError as exc:
            if exc.code == "idempotency_conflict":
                return exc.to_dict()
            raise

        reused = prior is not None
        # Fake + inline for unit tests
        if self.config.adapter == "fake" and self.config.inline_trials and not reused:
            if job.state.value == "queued":
                # mark running then execute
                self.store.transition(
                    job.job_id,
                    __import__("hfss_mcp.domain", fromlist=["JobState"]).JobState.RUNNING,
                    expected_states={
                        __import__("hfss_mcp.domain", fromlist=["JobState"]).JobState.QUEUED
                    },
                )
                self.supervisor.run_job_inline_fake(job.job_id)
                job = self.store.get(job.job_id) or job
        # else supervisor will pick up queued jobs

        job = self.store.get(job.job_id) or job
        return {
            "ok": True,
            "job_id": job.job_id,
            "run_id": job.run_id,
            "trial_id": job.trial_id,
            "manifest_id": job.manifest_id,
            "idempotency_key": job.idempotency_key,
            "state": job.state.value,
            "reused": reused,
            "workspace": ws.meta_dict(),
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

    def checkpoint_restore(
        self,
        *,
        checkpoint_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        rec = self.checkpoints.get(checkpoint_id)
        if rec is None:
            raise JobError(
                f"checkpoint not found: {checkpoint_id}",
                code="checkpoint_not_found",
            )
        if rec.run_id != run_id:
            raise PolicyError(
                "checkpoint does not belong to run",
                code="checkpoint_run_mismatch",
                details={"checkpoint_run": rec.run_id, "run_id": run_id},
            )
        # Must be inside workspace
        path = self.workspaces.assert_path_in_workspace(run_id, rec.checkpoint_path)
        ws = self.workspaces.load_run_workspace(run_id)
        if ws is None:
            raise PolicyError("workspace missing", code="workspace_not_found")
        import shutil

        shutil.copy2(path, ws.working_project)
        return {
            "ok": True,
            "restored_to": str(ws.working_project),
            "from_checkpoint": rec.model_dump(mode="json"),
            "original_unchanged": ws.verify_original_unchanged(),
            "original_sha256": ws.original_sha256,
        }

    def run_start(
        self,
        *,
        manifest_id: str,
        idempotency_key: str,
        strategy: str = "seeded_random",
        seed: int = 0,
        setup: str | None = None,
        sweep: str | None = None,
    ) -> dict[str, Any]:
        manifest = self.get_manifest(manifest_id)
        try:
            run = self.orchestrator.start_run(
                manifest=manifest,
                strategy=strategy,
                seed=seed,
                idempotency_key=idempotency_key,
                setup=setup,
                sweep=sweep,
            )
        except JobError as exc:
            if exc.code == "idempotency_conflict":
                return exc.to_dict()
            raise
        return {"ok": True, "run": run}

    def run_status(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise JobError(f"run not found: {run_id}", code="run_not_found")
        return {"ok": True, "run": run}

    def run_result(self, run_id: str) -> dict[str, Any]:
        return self.run_status(run_id)

    def run_cancel(self, run_id: str) -> dict[str, Any]:
        run = self.orchestrator.cancel_run(run_id)
        return {"ok": True, "run": run}

    def run_resume(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise JobError(f"run not found: {run_id}", code="run_not_found")
        manifest = self.get_manifest(run["manifest_id"])
        out = self.orchestrator.resume_run(run_id, manifest)
        return {"ok": True, "run": out}


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
    setup: str = "Setup1",
    sweep: str | None = "Sweep1",
    design_name: str = "HFSSDesign1",
) -> TuneManifest:
    data: dict[str, Any] = {
        "schema_version": "1.1",
        "project_path": str(project_path.resolve(strict=False)),
        "project_name": project_path.stem,
        "design_name": design_name,
        "allowed_setups": [{"setup": setup, "sweep": sweep}],
        "parameters": parameters
        or [
            {"name": "patch_w", "unit": "mm", "min": 1.0, "max": 50.0},
            {"name": "patch_l", "unit": "mm", "min": 1.0, "max": 50.0},
        ],
        "allowed_metrics": default_s11_metrics(
            setup=setup, sweep=sweep, f_min_ghz=1.0, f_max_ghz=10.0, f_target_ghz=2.4
        ),
        "stop_conditions": {
            "max_trials": 10,
            "max_runtime_seconds": 120.0,
            "metric_targets": {"S11_min_dB": -15.0},
        },
        "concurrency": {"mode": "serial", "max_concurrent": 1},
        "checkpoint": {"mode": "every_trial"},
    }
    return load_manifest(data)


def verify_original_hash(path: Path, expected: str) -> bool:
    return file_sha256(path) == expected
