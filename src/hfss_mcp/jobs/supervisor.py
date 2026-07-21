"""Process supervisor: spawn exclusive workers; never share one PyAEDT adapter."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from hfss_mcp.config import RuntimeConfig
from hfss_mcp.domain import TERMINAL_JOB_STATES, JobState
from hfss_mcp.jobs.store import JobStore


class Supervisor:
    """Background poller that claims queued jobs and launches worker processes."""

    def __init__(
        self,
        store: JobStore,
        config: RuntimeConfig,
        *,
        workspace_root: Path,
    ) -> None:
        self.store = store
        self.config = config
        self.workspace_root = Path(workspace_root)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._children: dict[str, subprocess.Popen[Any]] = {}
        self._log_handles: dict[str, Any] = {}
        self._lock = threading.RLock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="hfss-mcp-supervisor", daemon=True
        )
        self._thread.start()

    def stop(self, *, kill_workers: bool = False) -> None:
        self._stop.set()
        if kill_workers:
            with self._lock:
                for job_id, proc in list(self._children.items()):
                    self._terminate_worker(job_id, proc)
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._reap_children()
                self._dispatch_cancel()
                self._maybe_spawn()
            except Exception:
                pass
            self._stop.wait(0.25)

    def _active_count(self) -> int:
        with self._lock:
            return sum(1 for p in self._children.values() if p.poll() is None)

    def _maybe_spawn(self) -> None:
        if self._active_count() >= self.config.max_worker_processes:
            return
        # Look for queued jobs
        queued = self.store.list_jobs(state=JobState.QUEUED)
        for job in queued:
            if self._active_count() >= self.config.max_worker_processes:
                break
            lock_key = job.input_payload.get("project_lock")
            if lock_key:
                if not self.store.try_acquire_project_lock(str(lock_key), job.job_id):
                    continue
            # Spawn worker without pre-claiming — worker/claim via transition when process starts
            # Claim atomically first
            claimed = self._claim_for_spawn(job.job_id)
            if not claimed:
                if lock_key:
                    self.store.release_project_lock(str(lock_key), job.job_id)
                continue
            self._spawn(job.job_id)

    def _claim_for_spawn(self, job_id: str) -> bool:
        job = self.store.get(job_id)
        if job is None or job.state != JobState.QUEUED:
            return False
        try:
            self.store.transition(
                job_id,
                JobState.RUNNING,
                expected_states={JobState.QUEUED},
                worker_pid=os.getpid(),  # supervisor pid until worker heartbeats
            )
            return True
        except Exception:
            return False

    def _spawn(self, job_id: str) -> None:
        cmd = [
            sys.executable,
            "-m",
            "hfss_mcp.jobs.worker",
            "--db",
            str(self.store.db_path),
            "--job-id",
            job_id,
            "--adapter",
            self.config.adapter,
            "--aedt-version",
            self.config.aedt_version,
            "--non-graphical",
            "1" if self.config.non_graphical else "0",
            "--workspace-root",
            str(self.workspace_root),
        ]
        env = os.environ.copy()
        env["HFSS_MCP_ADAPTER"] = self.config.adapter
        env["HFSS_MCP_SOLVE_BLOCKING"] = "1"
        # CREATE_NEW_PROCESS_GROUP on Windows for cleaner kill
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        log_path = self.workspace_root / "worker_logs" / f"{job_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(log_path, "w", encoding="utf-8", errors="replace")  # noqa: SIM115
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        with self._lock:
            self._children[job_id] = proc
            self._log_handles[job_id] = log_handle
        # Record worker pid
        self.store.heartbeat(job_id, worker_pid=proc.pid)

    def _reap_children(self) -> None:
        with self._lock:
            items = list(self._children.items())
        for job_id, proc in items:
            code = proc.poll()
            if code is None:
                # still running — check cancel
                job = self.store.get(job_id)
                if job and job.state == JobState.CANCEL_REQUESTED:
                    self._terminate_worker(job_id, proc)
                continue
            # exited
            with self._lock:
                self._children.pop(job_id, None)
                handle = self._log_handles.pop(job_id, None)
                if handle is not None:
                    with suppress(Exception):
                        handle.close()
            job = self.store.get(job_id)
            if job is None:
                continue
            if job.state not in TERMINAL_JOB_STATES:
                # Worker died without finalizing
                self.store.transition(
                    job_id,
                    JobState.FAILED,
                    expected_states={JobState.RUNNING, JobState.CANCEL_REQUESTED},
                    error={
                        "code": "worker_exit",
                        "message": f"worker exited with code {code} without terminal state",
                        "exit_code": code,
                    },
                )

    def _dispatch_cancel(self) -> None:
        for job in self.store.list_jobs(state=JobState.CANCEL_REQUESTED):
            with self._lock:
                proc = self._children.get(job.job_id)
            if proc is not None and proc.poll() is None:
                self._terminate_worker(job.job_id, proc)

    def _terminate_worker(self, job_id: str, proc: subprocess.Popen[Any]) -> None:
        job = self.store.get(job_id)
        pid = proc.pid
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            pass
        # Also kill recorded worker_pid AEDT children if any remain — worker should handle
        if job is not None and job.state not in TERMINAL_JOB_STATES:
            try:
                self.store.transition(
                    job_id,
                    JobState.CANCELLED,
                    expected_states={JobState.RUNNING, JobState.CANCEL_REQUESTED},
                    error={"code": "cancelled", "message": "Worker process terminated"},
                )
            except Exception:
                pass
        with self._lock:
            self._children.pop(job_id, None)

    def wait_job(self, job_id: str, *, timeout_s: float = 600.0) -> JobState:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            job = self.store.get(job_id)
            if job is None:
                raise RuntimeError("job disappeared")
            if job.state in TERMINAL_JOB_STATES:
                return job.state
            time.sleep(0.2)
        raise TimeoutError(f"job {job_id} did not finish within {timeout_s}s")

    def run_job_inline_fake(self, job_id: str) -> None:
        """Test helper: execute worker logic in-process for fake adapter."""
        from hfss_mcp.jobs.worker import run_worker

        run_worker(
            db_path=self.store.db_path,
            job_id=job_id,
            adapter_name="fake",
            aedt_version=self.config.aedt_version,
            non_graphical=True,
            workspace_root=self.workspace_root,
        )
