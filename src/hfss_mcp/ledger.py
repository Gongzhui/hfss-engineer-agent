"""Persistent solve ledger and job registry for MCP host restarts."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from hfss_mcp.domain import utc_now_iso


class SolveLedger:
    """Append-only JSONL of solved (or failed) design points + job snapshots."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._jobs_path = self.path.with_name("jobs.json")

    def append_point(self, record: dict[str, Any]) -> None:
        payload = dict(record)
        payload.setdefault("recorded_at", utc_now_iso())
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def list_points(
        self,
        *,
        project: str | None = None,
        design: str | None = None,
        source: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        with self._lock:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        for raw in text.splitlines():
            if not raw.strip():
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            if project and item.get("project") != project:
                continue
            if design and item.get("design") != design:
                continue
            if source and item.get("source") != source:
                continue
            rows.append(item)
        if limit > 0:
            rows = rows[-limit:]
        return rows

    def save_jobs(self, jobs: dict[str, dict[str, Any]]) -> None:
        slim: dict[str, dict[str, Any]] = {}
        for job_id, rec in jobs.items():
            slim[job_id] = {
                k: rec.get(k)
                for k in (
                    "job_id",
                    "kind",
                    "state",
                    "setup",
                    "created_at",
                    "started_at",
                    "finished_at",
                    "error",
                    "progress",
                    "messages",
                    "messages_updated_at",
                    "points",
                    "context",
                    "project",
                    "process_id",
                    "design",
                    "rows",
                    "variables",
                    "source",
                    "geometry_failed",
                )
                if k in rec or k in {"job_id", "kind", "state", "setup"}
            }
        with self._lock:
            self._jobs_path.write_text(
                json.dumps(slim, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def load_jobs(self) -> dict[str, dict[str, Any]]:
        if not self._jobs_path.is_file():
            return {}
        try:
            with self._lock:
                raw = json.loads(self._jobs_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        out: dict[str, dict[str, Any]] = {}
        for key, value in raw.items():
            if isinstance(value, dict) and value.get("job_id"):
                out[str(key)] = dict(value)
        return out
