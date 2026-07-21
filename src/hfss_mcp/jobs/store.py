"""SQLite-backed durable job and run store with atomic claim and payload-hash idempotency."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from hfss_mcp.domain import TERMINAL_JOB_STATES, JobRecord, JobState, utc_now_iso
from hfss_mcp.errors import JobError
from hfss_mcp.ids import canonical_json_hash, new_id

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    run_id TEXT NOT NULL,
    trial_id TEXT NOT NULL,
    manifest_id TEXT NOT NULL,
    project_lock TEXT,
    input_payload TEXT NOT NULL,
    result_payload TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    artifact_paths TEXT NOT NULL DEFAULT '{}',
    worker_pid INTEGER,
    worker_heartbeat TEXT,
    attempt INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS idx_jobs_run ON jobs(run_id);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    manifest_id TEXT NOT NULL,
    state TEXT NOT NULL,
    strategy TEXT NOT NULL,
    seed INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL,
    config_json TEXT NOT NULL,
    journal_json TEXT NOT NULL DEFAULT '[]',
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    trials_completed INTEGER NOT NULL DEFAULT 0,
    best_metrics TEXT,
    workspace_path TEXT,
    original_sha256 TEXT
);

CREATE TABLE IF NOT EXISTS project_locks (
    lock_key TEXT PRIMARY KEY,
    holder_job_id TEXT,
    acquired_at TEXT
);

CREATE TABLE IF NOT EXISTS manifests (
    manifest_id TEXT PRIMARY KEY,
    body_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class JobStore:
    """Persistent jobs/runs; safe to reopen after process restart."""

    def __init__(self, db_path: Path | str, *, recover: bool = True) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._migrate()
            if recover:
                self.recover_interrupted()

    def _migrate(self) -> None:
        cols = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(jobs)").fetchall()
        }
        if "payload_hash" not in cols:
            self._conn.execute(
                "ALTER TABLE jobs ADD COLUMN payload_hash TEXT NOT NULL DEFAULT ''"
            )
        if "worker_pid" not in cols:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN worker_pid INTEGER")
        if "worker_heartbeat" not in cols:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN worker_heartbeat TEXT")
        if "attempt" not in cols:
            self._conn.execute(
                "ALTER TABLE jobs ADD COLUMN attempt INTEGER NOT NULL DEFAULT 0"
            )
        if "project_lock" not in cols:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN project_lock TEXT")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def recover_interrupted(self) -> list[str]:
        """Mark leftover running jobs interrupted; do not assume still running."""
        now = utc_now_iso()
        with self._lock:
            cur = self._conn.execute(
                "SELECT job_id FROM jobs WHERE state IN (?, ?)",
                (JobState.RUNNING.value, JobState.CANCEL_REQUESTED.value),
            )
            ids = [str(row["job_id"]) for row in cur.fetchall()]
            if ids:
                self._conn.execute(
                    """
                    UPDATE jobs
                    SET state = ?, updated_at = ?, finished_at = COALESCE(finished_at, ?),
                        error = COALESCE(error, ?), worker_pid = NULL
                    WHERE state IN (?, ?)
                    """,
                    (
                        JobState.INTERRUPTED.value,
                        now,
                        now,
                        json.dumps(
                            {
                                "code": "interrupted_on_restart",
                                "message": (
                                    "Job was running when the process stopped; "
                                    "marked interrupted (not assumed still running). "
                                    "Use run_resume for optimization runs."
                                ),
                            }
                        ),
                        JobState.RUNNING.value,
                        JobState.CANCEL_REQUESTED.value,
                    ),
                )
            # Runs left in running -> interrupted
            self._conn.execute(
                """
                UPDATE runs SET state = 'interrupted', updated_at = ?,
                error = COALESCE(error, ?)
                WHERE state IN ('running', 'cancel_requested')
                """,
                (
                    now,
                    json.dumps(
                        {
                            "code": "interrupted_on_restart",
                            "message": "Run was active when process stopped",
                        }
                    ),
                ),
            )
            # Clear locks
            self._conn.execute("DELETE FROM project_locks")
            return ids

    # ---- manifests ----

    def save_manifest(self, manifest_id: str, body: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO manifests(manifest_id, body_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(manifest_id) DO UPDATE SET body_json=excluded.body_json
                """,
                (manifest_id, json.dumps(body), utc_now_iso()),
            )

    def get_manifest_body(self, manifest_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT body_json FROM manifests WHERE manifest_id = ?",
                (manifest_id,),
            ).fetchone()
            if row is None:
                return None
            loaded: dict[str, Any] = json.loads(row["body_json"])
            return loaded

    # ---- jobs ----

    def create_job(
        self,
        *,
        idempotency_key: str,
        run_id: str,
        trial_id: str,
        manifest_id: str,
        input_payload: dict[str, Any],
        kind: str = "trial",
        job_id: str | None = None,
        project_lock: str | None = None,
    ) -> JobRecord:
        payload_hash = canonical_json_hash(input_payload)
        with self._lock:
            existing = self._get_by_idempotency_unlocked(idempotency_key)
            if existing is not None:
                if existing.input_payload.get("_payload_hash") == payload_hash or (
                    # compare stored hash column
                    self._payload_hash_for(existing.job_id) == payload_hash
                ):
                    return existing
                raise JobError(
                    "idempotency key reused with a different payload",
                    code="idempotency_conflict",
                    details={
                        "idempotency_key": idempotency_key,
                        "existing_job_id": existing.job_id,
                        "existing_payload_hash": self._payload_hash_for(existing.job_id),
                        "new_payload_hash": payload_hash,
                    },
                )
            now = utc_now_iso()
            stored_payload = dict(input_payload)
            stored_payload["_payload_hash"] = payload_hash
            record = JobRecord(
                job_id=job_id or new_id("job_"),
                idempotency_key=idempotency_key,
                kind=kind,
                state=JobState.QUEUED,
                run_id=run_id,
                trial_id=trial_id,
                manifest_id=manifest_id,
                input_payload=stored_payload,
                result_payload=None,
                error=None,
                created_at=now,
                updated_at=now,
                started_at=None,
                finished_at=None,
                artifact_paths={},
            )
            try:
                self._conn.execute(
                    """
                    INSERT INTO jobs (
                        job_id, idempotency_key, payload_hash, kind, state, run_id, trial_id,
                        manifest_id, project_lock, input_payload, result_payload, error,
                        created_at, updated_at, started_at, finished_at, artifact_paths,
                        worker_pid, worker_heartbeat, attempt
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL, NULL, ?, NULL, NULL, 0
                    )
                    """,
                    (
                        record.job_id,
                        record.idempotency_key,
                        payload_hash,
                        record.kind,
                        record.state.value,
                        record.run_id,
                        record.trial_id,
                        record.manifest_id,
                        project_lock,
                        json.dumps(record.input_payload),
                        record.created_at,
                        record.updated_at,
                        json.dumps(record.artifact_paths),
                    ),
                )
            except sqlite3.IntegrityError:
                existing = self._get_by_idempotency_unlocked(idempotency_key)
                if existing is not None:
                    if self._payload_hash_for(existing.job_id) == payload_hash:
                        return existing
                    raise JobError(
                        "idempotency key reused with a different payload",
                        code="idempotency_conflict",
                        details={"idempotency_key": idempotency_key},
                    ) from None
                raise JobError(
                    "failed to create job due to constraint conflict",
                    code="job_create_conflict",
                ) from None
            return record

    def _payload_hash_for(self, job_id: str) -> str:
        row = self._conn.execute(
            "SELECT payload_hash FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return str(row["payload_hash"]) if row else ""

    def _row_to_record(self, row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            job_id=row["job_id"],
            idempotency_key=row["idempotency_key"],
            kind=row["kind"],
            state=JobState(row["state"]),
            run_id=row["run_id"],
            trial_id=row["trial_id"],
            manifest_id=row["manifest_id"],
            input_payload=json.loads(row["input_payload"]),
            result_payload=json.loads(row["result_payload"])
            if row["result_payload"] is not None
            else None,
            error=json.loads(row["error"]) if row["error"] is not None else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            artifact_paths=json.loads(row["artifact_paths"] or "{}"),
        )

    def _get_by_idempotency_unlocked(self, key: str) -> JobRecord | None:
        cur = self._conn.execute(
            "SELECT * FROM jobs WHERE idempotency_key = ?",
            (key,),
        )
        row = cur.fetchone()
        return self._row_to_record(row) if row else None

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            row = cur.fetchone()
            return self._row_to_record(row) if row else None

    def get_by_idempotency(self, key: str) -> JobRecord | None:
        with self._lock:
            return self._get_by_idempotency_unlocked(key)

    def list_jobs(self, *, state: JobState | None = None) -> list[JobRecord]:
        with self._lock:
            if state is None:
                cur = self._conn.execute("SELECT * FROM jobs ORDER BY created_at")
            else:
                cur = self._conn.execute(
                    "SELECT * FROM jobs WHERE state = ? ORDER BY created_at",
                    (state.value,),
                )
            return [self._row_to_record(row) for row in cur.fetchall()]

    def claim_next_job(
        self,
        *,
        worker_pid: int,
        project_lock: str | None = None,
    ) -> JobRecord | None:
        """Atomically claim one queued job (optional project filter)."""
        now = utc_now_iso()
        with self._lock:
            if project_lock:
                row = self._conn.execute(
                    """
                    SELECT job_id FROM jobs
                    WHERE state = ? AND (project_lock = ? OR project_lock IS NULL)
                    ORDER BY created_at LIMIT 1
                    """,
                    (JobState.QUEUED.value, project_lock),
                ).fetchone()
            else:
                row = self._conn.execute(
                    """
                    SELECT job_id FROM jobs WHERE state = ?
                    ORDER BY created_at LIMIT 1
                    """,
                    (JobState.QUEUED.value,),
                ).fetchone()
            if row is None:
                return None
            job_id = row["job_id"]
            cur = self._conn.execute(
                """
                UPDATE jobs SET state = ?, updated_at = ?, started_at = COALESCE(started_at, ?),
                    worker_pid = ?, worker_heartbeat = ?, attempt = attempt + 1
                WHERE job_id = ? AND state = ?
                """,
                (
                    JobState.RUNNING.value,
                    now,
                    now,
                    worker_pid,
                    now,
                    job_id,
                    JobState.QUEUED.value,
                ),
            )
            if cur.rowcount != 1:
                return None
            return self.get(job_id)

    def heartbeat(self, job_id: str, *, worker_pid: int) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE jobs SET worker_heartbeat = ?, worker_pid = ?, updated_at = ?
                WHERE job_id = ? AND state IN (?, ?)
                """,
                (
                    utc_now_iso(),
                    worker_pid,
                    utc_now_iso(),
                    job_id,
                    JobState.RUNNING.value,
                    JobState.CANCEL_REQUESTED.value,
                ),
            )

    def transition(
        self,
        job_id: str,
        new_state: JobState,
        *,
        expected_states: set[JobState] | None = None,
        error: dict[str, Any] | None = None,
        result_payload: dict[str, Any] | None = None,
        artifact_paths: dict[str, str] | None = None,
        worker_pid: int | None = None,
    ) -> JobRecord:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
            row = cur.fetchone()
            if row is None:
                raise JobError(
                    f"job not found: {job_id}",
                    code="job_not_found",
                    details={"job_id": job_id},
                )
            record = self._row_to_record(row)
            if expected_states is not None and record.state not in expected_states:
                raise JobError(
                    f"invalid job transition from {record.state.value} to {new_state.value}",
                    code="invalid_transition",
                    details={
                        "job_id": job_id,
                        "from": record.state.value,
                        "to": new_state.value,
                        "expected": sorted(s.value for s in expected_states),
                    },
                )
            now = utc_now_iso()
            started_at = record.started_at
            finished_at = record.finished_at
            if new_state == JobState.RUNNING and started_at is None:
                started_at = now
            if new_state in TERMINAL_JOB_STATES and finished_at is None:
                finished_at = now
            new_error = error if error is not None else record.error
            new_result = (
                result_payload if result_payload is not None else record.result_payload
            )
            new_artifacts = (
                artifact_paths if artifact_paths is not None else record.artifact_paths
            )
            self._conn.execute(
                """
                UPDATE jobs SET
                    state = ?, updated_at = ?, started_at = ?, finished_at = ?,
                    error = ?, result_payload = ?, artifact_paths = ?,
                    worker_pid = CASE WHEN ? IS NOT NULL THEN ? ELSE worker_pid END
                WHERE job_id = ?
                """,
                (
                    new_state.value,
                    now,
                    started_at,
                    finished_at,
                    json.dumps(new_error) if new_error is not None else None,
                    json.dumps(new_result) if new_result is not None else None,
                    json.dumps(new_artifacts),
                    worker_pid,
                    worker_pid,
                    job_id,
                ),
            )
            if new_state in TERMINAL_JOB_STATES:
                self._conn.execute(
                    "UPDATE jobs SET worker_pid = NULL WHERE job_id = ?",
                    (job_id,),
                )
                # release project lock if held
                self._conn.execute(
                    "DELETE FROM project_locks WHERE holder_job_id = ?",
                    (job_id,),
                )
            updated = self.get(job_id)
            assert updated is not None
            return updated

    def request_cancel(self, job_id: str) -> JobRecord:
        record = self.get(job_id)
        if record is None:
            raise JobError(
                f"job not found: {job_id}",
                code="job_not_found",
                details={"job_id": job_id},
            )
        if record.state in TERMINAL_JOB_STATES:
            return record
        if record.state == JobState.QUEUED:
            return self.transition(
                job_id,
                JobState.CANCELLED,
                expected_states={JobState.QUEUED},
                error={
                    "code": "cancelled_before_start",
                    "message": "Job cancelled while still queued",
                },
            )
        return self.transition(
            job_id,
            JobState.CANCEL_REQUESTED,
            expected_states={JobState.RUNNING, JobState.CANCEL_REQUESTED},
        )

    def try_acquire_project_lock(self, lock_key: str, job_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT holder_job_id FROM project_locks WHERE lock_key = ?",
                (lock_key,),
            ).fetchone()
            if row is not None and row["holder_job_id"] not in (None, job_id):
                holder = row["holder_job_id"]
                # stale lock if holder terminal
                holder_job = self.get(str(holder))
                if holder_job is not None and holder_job.state not in TERMINAL_JOB_STATES:
                    return False
                self._conn.execute(
                    "DELETE FROM project_locks WHERE lock_key = ?", (lock_key,)
                )
            self._conn.execute(
                """
                INSERT INTO project_locks(lock_key, holder_job_id, acquired_at)
                VALUES (?, ?, ?)
                ON CONFLICT(lock_key) DO UPDATE SET
                    holder_job_id=excluded.holder_job_id,
                    acquired_at=excluded.acquired_at
                """,
                (lock_key, job_id, utc_now_iso()),
            )
            return True

    def release_project_lock(self, lock_key: str, job_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM project_locks WHERE lock_key = ? AND holder_job_id = ?",
                (lock_key, job_id),
            )

    # ---- runs ----

    def create_run(
        self,
        *,
        run_id: str,
        manifest_id: str,
        strategy: str,
        seed: int,
        idempotency_key: str,
        config: dict[str, Any],
        workspace_path: str | None = None,
        original_sha256: str | None = None,
    ) -> dict[str, Any]:
        payload_hash = canonical_json_hash(config)
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row is not None:
                if row["payload_hash"] != payload_hash:
                    raise JobError(
                        "run idempotency key reused with different payload",
                        code="idempotency_conflict",
                        details={"idempotency_key": idempotency_key},
                    )
                return self._row_to_run(row)
            now = utc_now_iso()
            self._conn.execute(
                """
                INSERT INTO runs (
                    run_id, manifest_id, state, strategy, seed, idempotency_key,
                    payload_hash, config_json, journal_json, created_at, updated_at,
                    workspace_path, original_sha256
                ) VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?)
                """,
                (
                    run_id,
                    manifest_id,
                    strategy,
                    seed,
                    idempotency_key,
                    payload_hash,
                    json.dumps(config),
                    now,
                    now,
                    workspace_path,
                    original_sha256,
                ),
            )
            return self.get_run(run_id)  # type: ignore[return-value]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            return self._row_to_run(row) if row else None

    def _row_to_run(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "manifest_id": row["manifest_id"],
            "state": row["state"],
            "strategy": row["strategy"],
            "seed": row["seed"],
            "idempotency_key": row["idempotency_key"],
            "payload_hash": row["payload_hash"],
            "config": json.loads(row["config_json"]),
            "journal": json.loads(row["journal_json"] or "[]"),
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": json.loads(row["error"]) if row["error"] else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "trials_completed": row["trials_completed"],
            "best_metrics": json.loads(row["best_metrics"])
            if row["best_metrics"]
            else None,
            "workspace_path": row["workspace_path"],
            "original_sha256": row["original_sha256"],
        }

    def update_run(
        self,
        run_id: str,
        *,
        state: str | None = None,
        journal_append: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        trials_completed: int | None = None,
        best_metrics: dict[str, float] | None = None,
        workspace_path: str | None = None,
        original_sha256: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            run = self.get_run(run_id)
            if run is None:
                raise JobError(f"run not found: {run_id}", code="run_not_found")
            now = utc_now_iso()
            journal = list(run["journal"])
            if journal_append is not None:
                journal.append(journal_append)
            new_state = state or run["state"]
            started = run["started_at"]
            finished = run["finished_at"]
            if new_state == "running" and not started:
                started = now
            if new_state in {
                "completed",
                "failed",
                "cancelled",
                "interrupted",
                "requires_recovery",
            }:
                finished = finished or now
            self._conn.execute(
                """
                UPDATE runs SET
                    state = ?, updated_at = ?, started_at = ?, finished_at = ?,
                    journal_json = ?, result_json = ?, error = ?,
                    trials_completed = ?, best_metrics = ?,
                    workspace_path = COALESCE(?, workspace_path),
                    original_sha256 = COALESCE(?, original_sha256)
                WHERE run_id = ?
                """,
                (
                    new_state,
                    now,
                    started,
                    finished,
                    json.dumps(journal),
                    json.dumps(result) if result is not None else (
                        json.dumps(run["result"]) if run["result"] is not None else None
                    ),
                    json.dumps(error) if error is not None else (
                        json.dumps(run["error"]) if run["error"] is not None else None
                    ),
                    trials_completed
                    if trials_completed is not None
                    else run["trials_completed"],
                    json.dumps(best_metrics)
                    if best_metrics is not None
                    else (
                        json.dumps(run["best_metrics"])
                        if run["best_metrics"] is not None
                        else None
                    ),
                    workspace_path,
                    original_sha256,
                    run_id,
                ),
            )
            out = self.get_run(run_id)
            assert out is not None
            return out
