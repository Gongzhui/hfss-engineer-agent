"""Application context: production wiring for durable trials and runs."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from hfss_mcp.adapter.fake import FakeAdapter
from hfss_mcp.checkpoint import CheckpointService
from hfss_mcp.config import RuntimeConfig, load_runtime_config
from hfss_mcp.domain import JobState, ParameterVector
from hfss_mcp.environment import inspect_environment
from hfss_mcp.errors import HfssMcpError, JobError, PolicyError
from hfss_mcp.ids import file_sha256, new_id
from hfss_mcp.jobs.store import JobStore
from hfss_mcp.jobs.supervisor import Supervisor
from hfss_mcp.jobs.trial_exec import execute_trial
from hfss_mcp.manifest import TuneManifest, default_s11_metrics, load_manifest
from hfss_mcp.policy import explain_manifest, validate_manifest_dict, validate_trial_request
from hfss_mcp.run_optimizer import RunOrchestrator
from hfss_mcp.session_discovery import (
    SessionDiscoveryResult,
    discover_running_sessions,
    find_open_project,
)
from hfss_mcp.workspace import WorkspaceService, project_lock_key


@contextmanager
def suppress_exc() -> Iterator[None]:
    try:
        yield
    except Exception:
        pass


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
        self._gui_adapter: Any | None = None
        self._gui_pid: int | None = None
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
            if self._gui_adapter is not None:
                with suppress_exc():
                    self._gui_adapter.disconnect(close_desktop=False)
                self._gui_adapter = None
            self.supervisor.stop(kill_workers=False)
        finally:
            self.store.close()

    def discover_sessions(self) -> SessionDiscoveryResult:
        return discover_running_sessions(version=self.config.aedt_version)

    def _resolve_connection_mode(self, discovery: SessionDiscoveryResult) -> str:
        if self.config.adapter == "fake":
            return "in_process_fake"
        mode = self.config.session_mode
        if mode == "new":
            return "worker_process_exclusive_desktop"
        if mode == "attach":
            return "attach_gui_session"
        # auto
        if discovery.any_gui_session:
            return "attach_gui_session"
        return "worker_process_exclusive_desktop"

    def health(self) -> dict[str, Any]:
        env = inspect_environment()
        preferred = env.preferred
        real_ready = (
            self.config.adapter == "pyaedt"
            and preferred is not None
            and preferred.exe_exists
        )
        discovery = (
            self.discover_sessions()
            if self.config.adapter == "pyaedt"
            else SessionDiscoveryResult()
        )
        from hfss_mcp import __version__ as pkg_version

        conn = self._resolve_connection_mode(discovery)
        payload: dict[str, Any] = {
            "ok": True,
            "version": str(pkg_version),
            "mode": "tune_only_v0_real" if self.config.adapter == "pyaedt" else "demo_fake",
            "adapter": self.config.adapter,
            "demo_mode": self.config.demo_mode,
            "real_hfss_ready": real_ready,
            "aedt_version_configured": self.config.aedt_version,
            "session_mode": self.config.session_mode,
            "connection_mode": conn,
            "gui_attached": self._gui_adapter is not None,
            "gui_process_id": self._gui_pid,
            "inline_trials": self.config.inline_trials,
            "data_dir": str(self.data_dir),
            "environment": env.to_public_dict(),
            "sessions": discovery.to_public_dict(),
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
        payload["session_mode"] = h["session_mode"]
        payload["sessions"] = h["sessions"]
        payload["gui_attached"] = h["gui_attached"]
        payload["gui_process_id"] = h["gui_process_id"]
        payload["data_dir"] = h["data_dir"]
        return payload

    def session_list(self) -> dict[str, Any]:
        """List running AEDT sessions and open projects/designs."""
        discovery = self.discover_sessions()
        return {
            "ok": True,
            "session_mode": self.config.session_mode,
            "connection_mode": self._resolve_connection_mode(discovery),
            **discovery.to_public_dict(),
        }

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

    def _should_attach_gui(self, discovery: SessionDiscoveryResult | None = None) -> bool:
        if self.config.adapter != "pyaedt":
            return False
        if self.config.session_mode == "new":
            return False
        if self.config.session_mode == "attach":
            return True
        # auto
        disc = discovery or self.discover_sessions()
        return bool(disc.any_gui_session)

    def _get_or_attach_gui(
        self,
        *,
        project_path: Path,
        design_name: str,
        process_id: int | None = None,
        grpc_port: int | None = None,
    ) -> Any:
        from hfss_mcp.adapter.pyaedt_adapter import PyAedtAdapter

        if (
            self._gui_adapter is not None
            and self._gui_pid is not None
            and (process_id is None or process_id == self._gui_pid)
        ):
            self._gui_adapter.attach_project(project_path, design_name)
            return self._gui_adapter

        if self._gui_adapter is not None:
            with suppress_exc():
                self._gui_adapter.disconnect(close_desktop=False)
            self._gui_adapter = None

        adapter = PyAedtAdapter(
            version=self.config.aedt_version,
            non_graphical=False,
            new_desktop=False,
            close_on_exit=False,
            aedt_process_id=process_id,
            grpc_port=grpc_port,
        )
        adapter.attach_project(project_path, design_name)
        self._gui_adapter = adapter
        self._gui_pid = adapter.desktop_pid or process_id
        return adapter

    def design_snapshot(self, manifest_id: str) -> dict[str, Any]:
        """Snapshot design: prefer attaching to GUI-open project when available."""
        manifest = self.get_manifest(manifest_id)
        discovery = self.discover_sessions()
        match = find_open_project(discovery, manifest.project_path)
        attached = False
        adapter: Any
        ws_meta: dict[str, Any] | None = None
        original_sha: str | None = None

        if self.config.adapter == "fake":
            from hfss_mcp.domain import ParameterValue

            run_id = new_id("snap_")
            ws = self.workspaces.create_run_workspace(
                run_id=run_id,
                original_project=manifest.project_path,
                project_name=manifest.project_name,
            )
            ws_meta = ws.meta_dict()
            original_sha = ws.original_sha256
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
            try:
                snap = adapter.attach_project(ws.working_project, manifest.design_name)
            finally:
                with suppress_exc():
                    adapter.disconnect(close_desktop=False)
        elif self._should_attach_gui(discovery) and match is not None:
            sess, proj = match
            path = Path(proj.project_path or manifest.project_path)
            design = manifest.design_name
            # Prefer active design if names align
            if proj.designs:
                active = next((d for d in proj.designs if d.is_active), None)
                if active and (
                    active.design_name == design
                    or design in {d.design_name for d in proj.designs}
                ):
                    design = (
                        design
                        if design in {d.design_name for d in proj.designs}
                        else active.design_name
                    )
            adapter = self._get_or_attach_gui(
                project_path=path,
                design_name=design,
                process_id=sess.process_id,
                grpc_port=sess.grpc_port,
            )
            snap = adapter.snapshot()
            attached = True
            if path.is_file():
                original_sha = file_sha256(path)
        else:
            # Fallback: workspace copy + new desktop
            from hfss_mcp.adapter.pyaedt_adapter import PyAedtAdapter

            run_id = new_id("snap_")
            ws = self.workspaces.create_run_workspace(
                run_id=run_id,
                original_project=manifest.project_path,
                project_name=manifest.project_name,
            )
            ws_meta = ws.meta_dict()
            original_sha = ws.original_sha256
            adapter = PyAedtAdapter(
                version=self.config.aedt_version,
                non_graphical=self.config.non_graphical,
                new_desktop=True,
                close_on_exit=True,
            )
            try:
                snap = adapter.attach_project(ws.working_project, manifest.design_name)
            finally:
                with suppress_exc():
                    adapter.disconnect(close_desktop=True)

        if snap.design_name != manifest.design_name:
            # Soft mismatch when GUI active design differs but is listed
            if not attached:
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
            "attached_to_gui": attached,
            "gui_process_id": self._gui_pid if attached else None,
            "workspace": ws_meta,
            "original_sha256": original_sha,
            "sessions": discovery.to_public_dict(),
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
        discovery = self.discover_sessions()
        match = find_open_project(discovery, manifest.project_path)
        use_gui = (
            self._should_attach_gui(discovery)
            and match is not None
            and self.config.attach_live_project
            and self.config.adapter == "pyaedt"
        )

        # Checkpoint target / working path
        if use_gui:
            sess, proj = match  # type: ignore[misc]
            live_path = Path(proj.project_path or manifest.project_path)
            original_path = live_path
            working_path = live_path
            original_sha = file_sha256(live_path) if live_path.is_file() else ""
            ws_meta = {
                "mode": "live_gui",
                "process_id": sess.process_id,
                "project_path": str(live_path),
            }
            attach_pid: int | None = sess.process_id
            attach_port: int | None = sess.grpc_port
        else:
            ws = self.workspaces.create_run_workspace(
                run_id=rid,
                original_project=manifest.project_path,
                project_name=manifest.project_name,
            )
            original_path = Path(manifest.project_path)
            working_path = ws.working_project
            original_sha = ws.original_sha256
            ws_meta = ws.meta_dict()
            attach_pid = None
            attach_port = None

        lock_key = project_lock_key(manifest.project_path)
        input_payload = {
            "setup": setup,
            "sweep": sweep,
            "parameters": vector.model_dump(mode="json"),
            "expected_revision": expected_revision,
            "manifest_id": manifest_id,
            "run_id": rid,
            "trial_id": tid,
            "working_project": str(working_path),
            "original_project": str(original_path),
            "original_sha256": original_sha,
            "project_lock": lock_key,
            "attach_mode": use_gui,
            "aedt_process_id": attach_pid,
            "grpc_port": attach_port,
            "design_name": manifest.design_name,
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
        if not reused and job.state == JobState.QUEUED:
            if self.config.adapter == "fake" and self.config.inline_trials:
                self.store.transition(
                    job.job_id,
                    JobState.RUNNING,
                    expected_states={JobState.QUEUED},
                )
                self.supervisor.run_job_inline_fake(job.job_id)
            elif use_gui:
                # Run against live GUI session in this process (do not spawn new Desktop)
                self.store.transition(
                    job.job_id,
                    JobState.RUNNING,
                    expected_states={JobState.QUEUED},
                )
                adapter = self._get_or_attach_gui(
                    project_path=working_path,
                    design_name=manifest.design_name,
                    process_id=attach_pid,
                    grpc_port=attach_port,
                )
                execute_trial(
                    store=self.store,
                    job_id=job.job_id,
                    manifest=manifest,
                    adapter=adapter,
                    checkpoints=self.checkpoints,
                    working_project=working_path,
                    original_project=original_path,
                    original_sha256=original_sha or "",
                    recover_on_failure=True,
                )
            # else: supervisor worker (new exclusive desktop on workspace copy)

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
            "attached_to_gui": use_gui,
            "gui_process_id": attach_pid if use_gui else None,
            "workspace": ws_meta,
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
