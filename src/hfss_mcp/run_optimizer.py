"""Unattended multi-trial run with seeded random search (deterministic)."""

from __future__ import annotations

import random
import threading
import time
from typing import Any

from hfss_mcp.domain import JobState, ParameterValue, ParameterVector, utc_now_iso
from hfss_mcp.errors import JobError, PolicyError
from hfss_mcp.ids import new_id
from hfss_mcp.jobs.store import JobStore
from hfss_mcp.jobs.supervisor import Supervisor
from hfss_mcp.manifest import TuneManifest
from hfss_mcp.workspace import WorkspaceService, project_lock_key


def sample_parameters(manifest: TuneManifest, rng: random.Random) -> ParameterVector:
    values: list[ParameterValue] = []
    for spec in manifest.parameters:
        v = rng.uniform(spec.min_value, spec.max_value)
        # modest rounding for reproducibility display
        v = round(v, 6)
        values.append(ParameterValue(name=spec.name, value=v, unit=spec.unit))
    return ParameterVector(values=values)


def targets_met(metrics: dict[str, float], targets: dict[str, float]) -> bool:
    if not targets:
        return False
    for name, target in targets.items():
        if name not in metrics:
            return False
        # For S11 dB metrics, success is metric <= target (more negative is better)
        if "freq" in name.lower():
            continue
        if metrics[name] > target:
            return False
    return True


class RunOrchestrator:
    def __init__(
        self,
        store: JobStore,
        supervisor: Supervisor,
        workspaces: WorkspaceService,
    ) -> None:
        self.store = store
        self.supervisor = supervisor
        self.workspaces = workspaces
        self._threads: dict[str, threading.Thread] = {}

    def start_run(
        self,
        *,
        manifest: TuneManifest,
        strategy: str,
        seed: int,
        idempotency_key: str,
        setup: str | None = None,
        sweep: str | None = None,
    ) -> dict[str, Any]:
        if strategy != "seeded_random":
            raise PolicyError(
                f"unsupported strategy {strategy!r}; v0 supports seeded_random",
                code="unsupported_strategy",
            )
        setup_ref = manifest.allowed_setups[0]
        use_setup = setup or setup_ref.setup
        use_sweep = sweep if sweep is not None else setup_ref.sweep
        run_id = new_id("run_")
        config = {
            "strategy": strategy,
            "seed": seed,
            "setup": use_setup,
            "sweep": use_sweep,
            "manifest_id": manifest.manifest_id(),
            "max_trials": manifest.stop_conditions.max_trials,
            "max_runtime_seconds": manifest.stop_conditions.max_runtime_seconds,
            "metric_targets": manifest.stop_conditions.metric_targets,
            "concurrency": manifest.concurrency.model_dump(mode="json"),
        }
        try:
            run = self.store.create_run(
                run_id=run_id,
                manifest_id=manifest.manifest_id(),
                strategy=strategy,
                seed=seed,
                idempotency_key=idempotency_key,
                config=config,
            )
        except JobError:
            raise
        # If reused completed/running run, return it
        if run["run_id"] != run_id or run["state"] not in {"queued"}:
            return run

        # Create workspace copy
        ws = self.workspaces.create_run_workspace(
            run_id=run["run_id"],
            original_project=manifest.project_path,
            project_name=manifest.project_name,
        )
        self.store.update_run(
            run["run_id"],
            state="running",
            workspace_path=str(ws.root),
            original_sha256=ws.original_sha256,
        )
        t = threading.Thread(
            target=self._run_loop,
            args=(run["run_id"], manifest),
            name=f"run-{run['run_id']}",
            daemon=True,
        )
        self._threads[run["run_id"]] = t
        t.start()
        out = self.store.get_run(run["run_id"])
        assert out is not None
        return out

    def resume_run(self, run_id: str, manifest: TuneManifest) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise JobError(f"run not found: {run_id}", code="run_not_found")
        if run["state"] in {"completed", "cancelled", "failed"}:
            return run
        self.store.update_run(run_id, state="running", error=None)
        t = threading.Thread(
            target=self._run_loop,
            args=(run_id, manifest),
            name=f"run-resume-{run_id}",
            daemon=True,
        )
        self._threads[run_id] = t
        t.start()
        out = self.store.get_run(run_id)
        assert out is not None
        return out

    def _run_loop(self, run_id: str, manifest: TuneManifest) -> None:
        run = self.store.get_run(run_id)
        if run is None:
            return
        cfg = run["config"]
        seed = int(cfg["seed"])
        rng = random.Random(seed + int(run.get("trials_completed") or 0))
        max_trials = int(cfg["max_trials"])
        max_runtime = float(cfg["max_runtime_seconds"])
        started = time.monotonic()
        best: dict[str, float] | None = run.get("best_metrics")
        trials_done = int(run.get("trials_completed") or 0)
        setup = str(cfg["setup"])
        sweep = cfg.get("sweep")
        ws = self.workspaces.load_run_workspace(run_id)
        if ws is None:
            self.store.update_run(
                run_id,
                state="failed",
                error={"code": "workspace_missing", "message": "run workspace missing"},
            )
            return

        lock_key = project_lock_key(manifest.project_path)
        try:
            while trials_done < max_trials:
                run = self.store.get_run(run_id)
                if run is None:
                    return
                if run["state"] in {"cancel_requested", "cancelled"}:
                    self.store.update_run(run_id, state="cancelled")
                    return
                if time.monotonic() - started > max_runtime:
                    self.store.update_run(
                        run_id,
                        state="completed",
                        result={
                            "reason": "max_runtime",
                            "trials_completed": trials_done,
                            "best_metrics": best,
                        },
                        best_metrics=best,
                        trials_completed=trials_done,
                    )
                    return

                vector = sample_parameters(manifest, rng)
                trial_id = new_id("trial_")
                idem = f"{run_id}:{trials_done}:{vector.model_dump_json()}"
                input_payload = {
                    "setup": setup,
                    "sweep": sweep,
                    "parameters": vector.model_dump(mode="json"),
                    "expected_revision": None,
                    "manifest_id": manifest.manifest_id(),
                    "run_id": run_id,
                    "trial_id": trial_id,
                    "working_project": str(ws.working_project),
                    "original_project": str(ws.original_project),
                    "original_sha256": ws.original_sha256,
                    "project_lock": lock_key,
                }
                job = self.store.create_job(
                    idempotency_key=idem[:200],
                    run_id=run_id,
                    trial_id=trial_id,
                    manifest_id=manifest.manifest_id(),
                    input_payload=input_payload,
                    project_lock=lock_key,
                )
                # Wait for completion
                while True:
                    j = self.store.get(job.job_id)
                    assert j is not None
                    if j.state in {
                        JobState.COMPLETED,
                        JobState.FAILED,
                        JobState.CANCELLED,
                        JobState.INTERRUPTED,
                    }:
                        break
                    run = self.store.get_run(run_id)
                    if run and run["state"] == "cancel_requested":
                        self.store.request_cancel(job.job_id)
                    time.sleep(0.3)

                j = self.store.get(job.job_id)
                assert j is not None
                metrics = (j.result_payload or {}).get("metrics") or {}
                trials_done += 1
                entry = {
                    "trial_id": trial_id,
                    "job_id": job.job_id,
                    "state": j.state.value,
                    "parameters": vector.model_dump(mode="json"),
                    "metrics": metrics,
                    "error": j.error,
                    "at": utc_now_iso(),
                }
                if metrics:
                    if best is None:
                        best = dict(metrics)
                    else:
                        key = "S11_min_dB"
                        better = (
                            key not in best
                            or (
                                key in metrics
                                and key in best
                                and metrics[key] < best[key]
                            )
                        )
                        if better:
                            best = dict(metrics)
                self.store.update_run(
                    run_id,
                    journal_append=entry,
                    trials_completed=trials_done,
                    best_metrics=best,
                )
                if j.state == JobState.FAILED and (j.result_payload or {}).get(
                    "requires_recovery"
                ):
                    self.store.update_run(
                        run_id,
                        state="requires_recovery",
                        error={
                            "code": "requires_recovery",
                            "message": "Trial failed and checkpoint restore failed",
                            "job_id": job.job_id,
                        },
                        trials_completed=trials_done,
                        best_metrics=best,
                    )
                    return
                if metrics and targets_met(metrics, cfg.get("metric_targets") or {}):
                    self.store.update_run(
                        run_id,
                        state="completed",
                        result={
                            "reason": "metric_targets",
                            "trials_completed": trials_done,
                            "best_metrics": best,
                        },
                        best_metrics=best,
                        trials_completed=trials_done,
                    )
                    return

            self.store.update_run(
                run_id,
                state="completed",
                result={
                    "reason": "max_trials",
                    "trials_completed": trials_done,
                    "best_metrics": best,
                },
                best_metrics=best,
                trials_completed=trials_done,
            )
        except Exception as exc:  # noqa: BLE001
            self.store.update_run(
                run_id,
                state="failed",
                error={"code": "run_error", "message": str(exc)},
            )

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise JobError(f"run not found: {run_id}", code="run_not_found")
        if run["state"] in {"completed", "failed", "cancelled"}:
            return run
        self.store.update_run(run_id, state="cancel_requested")
        for job in self.store.list_jobs():
            if job.run_id == run_id and job.state in {
                JobState.QUEUED,
                JobState.RUNNING,
            }:
                self.store.request_cancel(job.job_id)
        out = self.store.get_run(run_id)
        assert out is not None
        return out
