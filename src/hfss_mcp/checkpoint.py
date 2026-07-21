"""Project checkpoint service: copy before mutation, hash, never overwrite original."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Protocol

from hfss_mcp.domain import CheckpointRecord, utc_now_iso
from hfss_mcp.errors import CheckpointError
from hfss_mcp.ids import file_sha256, new_id


class ProjectCopyPort(Protocol):
    def save_project_copy(self, destination: Path) -> None: ...


class CheckpointService:
    """Creates hashed project copies under a workspace directory."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = Path(workspace_root)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self._index_path = self.workspace_root / "checkpoints.jsonl"
        self._records: list[CheckpointRecord] = []
        self._load_index()

    def _load_index(self) -> None:
        if not self._index_path.is_file():
            return
        for line in self._index_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            self._records.append(CheckpointRecord.model_validate_json(line))

    def _append_index(self, record: CheckpointRecord) -> None:
        with self._index_path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")
        self._records.append(record)

    def create_checkpoint(
        self,
        *,
        adapter: ProjectCopyPort,
        original_project_path: Path | str,
        manifest_id: str,
        run_id: str,
        trial_id: str | None = None,
        notes: str | None = None,
        source_file: Path | str | None = None,
    ) -> CheckpointRecord:
        """Create a checkpoint without overwriting the original project path.

        If ``source_file`` exists on disk, copy it; otherwise use adapter.save_project_copy.
        """
        original = Path(original_project_path).resolve(strict=False)
        checkpoint_id = new_id("ckpt_")
        dest_dir = self.workspace_root / "checkpoints" / checkpoint_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / original.name

        if dest.resolve(strict=False) == original.resolve(strict=False):
            raise CheckpointError(
                "checkpoint destination resolves to the original project path",
                code="checkpoint_overwrite_denied",
                details={"original": str(original), "destination": str(dest)},
            )

        try:
            if source_file is not None and Path(source_file).is_file():
                src = Path(source_file)
                if src.resolve(strict=False) == dest.resolve(strict=False):
                    raise CheckpointError(
                        "source and destination are the same path",
                        code="checkpoint_overwrite_denied",
                    )
                shutil.copy2(src, dest)
            else:
                adapter.save_project_copy(dest)
        except CheckpointError:
            raise
        except Exception as exc:
            raise CheckpointError(
                f"failed to create checkpoint: {exc}",
                details={"original": str(original), "destination": str(dest)},
            ) from exc

        if not dest.is_file():
            raise CheckpointError(
                "checkpoint file was not created",
                details={"destination": str(dest)},
            )

        digest = file_sha256(dest)
        # Sidecar metadata
        meta_path = dest_dir / "checkpoint.json"
        record = CheckpointRecord(
            checkpoint_id=checkpoint_id,
            original_project_path=str(original),
            checkpoint_path=str(dest.resolve(strict=False)),
            sha256=digest,
            created_at=utc_now_iso(),
            manifest_id=manifest_id,
            run_id=run_id,
            trial_id=trial_id,
            notes=notes,
        )
        meta_path.write_text(
            json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self._append_index(record)
        return record

    def reload(self) -> None:
        """Re-read durable index (e.g. after worker process wrote checkpoints)."""
        self._records = []
        self._load_index()

    def list_checkpoints(
        self,
        *,
        run_id: str | None = None,
        manifest_id: str | None = None,
    ) -> list[CheckpointRecord]:
        self.reload()
        items = list(self._records)
        if run_id is not None:
            items = [r for r in items if r.run_id == run_id]
        if manifest_id is not None:
            items = [r for r in items if r.manifest_id == manifest_id]
        return items

    def get(self, checkpoint_id: str) -> CheckpointRecord | None:
        self.reload()
        for record in self._records:
            if record.checkpoint_id == checkpoint_id:
                return record
        return None
