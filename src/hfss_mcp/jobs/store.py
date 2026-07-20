"""SQLite-backed durable job store with restart recovery."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from hfss_mcp.domain import TERMINAL_JOB_STATES, JobRecord, JobState, utc_now_iso
from hfss_mcp.errors import JobError
from hfss_mcp.ids import new_id

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    run_id TEXT NOT NULL,
    trial_id TEXT NOT NULL,
    manifest_id TEXT NOT NULL,
    input_payload TEXT NOT NULL,
    result_payload TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    artifact_paths TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS idx_jobs_run ON jobs(run_id);
"""


class JobStore:
    """Persistent jobs; safe to reopen after process restart."""

    def __init__(self, db_path: Path | str) -> None:
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
            self.recover_interrupted()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def recover_interrupted(self) -> list[str]:
        """Mark leftover running/cancel_requested jobs as interrupted on startup."""
        now = utc_now_iso()
        with self._lock:
            cur = self._conn.execute(
                "SELECT job_id FROM jobs WHERE state IN (?, ?)",
                (JobState.RUNNING.value, JobState.CANCEL_REQUESTED.value),
            )
            ids = [str(row["job_id"]) for row in cur.fetchall()]
            if not ids:
                return []
            self._conn.execute(
                """
                UPDATE jobs
                SET state = ?, updated_at = ?, finished_at = COALESCE(finished_at, ?),
                    error = COALESCE(error, ?)
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
                                "marked interrupted and is not assumed still running"
                            ),
                        }
                    ),
                    JobState.RUNNING.value,
                    JobState.CANCEL_REQUESTED.value,
                ),
            )
            return ids

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
    ) -> JobRecord:
        """Create a queued job, or return the existing one for the same idempotency key."""
        with self._lock:
            existing = self._get_by_idempotency_unlocked(idempotency_key)
            if existing is not None:
                return existing
            now = utc_now_iso()
            record = JobRecord(
                job_id=job_id or new_id("job_"),
                idempotency_key=idempotency_key,
                kind=kind,
                state=JobState.QUEUED,
                run_id=run_id,
                trial_id=trial_id,
                manifest_id=manifest_id,
                input_payload=input_payload,
                result_payload=None,
                error=None,
                created_at=now,
                updated_at=now,
                started_at=None,
                finished_at=None,
                artifact_paths={},
            )
            try:
                self._insert_unlocked(record)
            except sqlite3.IntegrityError:
                # Race: another writer inserted the same idempotency key
                existing = self._get_by_idempotency_unlocked(idempotency_key)
                if existing is not None:
                    return existing
                raise JobError(
                    "failed to create job due to constraint conflict",
                    code="job_create_conflict",
                    details={"idempotency_key": idempotency_key},
                ) from None
            return record

    def _insert_unlocked(self, record: JobRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO jobs (
                job_id, idempotency_key, kind, state, run_id, trial_id, manifest_id,
                input_payload, result_payload, error, created_at, updated_at,
                started_at, finished_at, artifact_paths
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.job_id,
                record.idempotency_key,
                record.kind,
                record.state.value,
                record.run_id,
                record.trial_id,
                record.manifest_id,
                json.dumps(record.input_payload),
                json.dumps(record.result_payload) if record.result_payload is not None else None,
                json.dumps(record.error) if record.error is not None else None,
                record.created_at,
                record.updated_at,
                record.started_at,
                record.finished_at,
                json.dumps(record.artifact_paths),
            ),
        )

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

    def transition(
        self,
        job_id: str,
        new_state: JobState,
        *,
        expected_states: set[JobState] | None = None,
        error: dict[str, Any] | None = None,
        result_payload: dict[str, Any] | None = None,
        artifact_paths: dict[str, str] | None = None,
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
            new_result = result_payload if result_payload is not None else record.result_payload
            new_artifacts = (
                artifact_paths if artifact_paths is not None else record.artifact_paths
            )
            self._conn.execute(
                """
                UPDATE jobs SET
                    state = ?, updated_at = ?, started_at = ?, finished_at = ?,
                    error = ?, result_payload = ?, artifact_paths = ?
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
                    job_id,
                ),
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
