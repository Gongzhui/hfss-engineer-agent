"""Safe run workspaces: never mutate the user's original .aedt path."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from hfss_mcp.domain import utc_now_iso
from hfss_mcp.errors import HfssMcpError
from hfss_mcp.ids import file_sha256, sha256_hex


class WorkspaceError(HfssMcpError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "workspace_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class RunWorkspace:
    """Per-run directory holding the working project copy and metadata."""

    def __init__(
        self,
        root: Path,
        *,
        run_id: str,
        original_project: Path,
        original_sha256: str,
        working_project: Path,
        created_at: str,
    ) -> None:
        self.root = root
        self.run_id = run_id
        self.original_project = original_project
        self.original_sha256 = original_sha256
        self.working_project = working_project
        self.created_at = created_at

    def meta_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "original_project": str(self.original_project),
            "original_sha256": self.original_sha256,
            "working_project": str(self.working_project),
            "created_at": self.created_at,
            "root": str(self.root),
        }

    def verify_original_unchanged(self) -> bool:
        if not self.original_project.is_file():
            return False
        return file_sha256(self.original_project) == self.original_sha256


class WorkspaceService:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_run_workspace(
        self,
        *,
        run_id: str,
        original_project: Path | str,
        project_name: str | None = None,
    ) -> RunWorkspace:
        original = Path(original_project).resolve(strict=False)
        if not original.is_file():
            raise WorkspaceError(
                f"original project not found: {original}",
                code="original_missing",
                details={"path": str(original)},
            )
        if original.suffix.lower() not in {".aedt", ".aedtz"}:
            raise WorkspaceError(
                "original project must be .aedt/.aedtz",
                code="invalid_project_extension",
            )
        digest = file_sha256(original)
        root = self.base_dir / "runs" / run_id
        if root.exists():
            # Reuse existing workspace if meta matches
            meta_path = root / "workspace.json"
            if meta_path.is_file():
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                ws = RunWorkspace(
                    root=root,
                    run_id=run_id,
                    original_project=Path(data["original_project"]),
                    original_sha256=data["original_sha256"],
                    working_project=Path(data["working_project"]),
                    created_at=data["created_at"],
                )
                if ws.original_sha256 != digest:
                    raise WorkspaceError(
                        "original project hash changed since workspace creation",
                        code="original_hash_changed",
                        details={
                            "expected": ws.original_sha256,
                            "actual": digest,
                        },
                    )
                return ws
        root.mkdir(parents=True, exist_ok=True)
        work_dir = root / "work"
        work_dir.mkdir(parents=True, exist_ok=True)
        dest_name = (project_name or original.stem) + original.suffix
        # Sanitize dest name
        dest_name = dest_name.replace("/", "_").replace("\\", "_")
        dest = work_dir / dest_name
        if dest.resolve(strict=False) == original.resolve(strict=False):
            raise WorkspaceError(
                "working copy would overwrite original",
                code="workspace_overwrite_denied",
            )
        shutil.copy2(original, dest)
        # Copy lock-free; also try results folder companion if small — skip results
        created = utc_now_iso()
        ws = RunWorkspace(
            root=root,
            run_id=run_id,
            original_project=original,
            original_sha256=digest,
            working_project=dest,
            created_at=created,
        )
        (root / "workspace.json").write_text(
            json.dumps(ws.meta_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return ws

    def load_run_workspace(self, run_id: str) -> RunWorkspace | None:
        meta_path = self.base_dir / "runs" / run_id / "workspace.json"
        if not meta_path.is_file():
            return None
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return RunWorkspace(
            root=Path(data["root"]),
            run_id=data["run_id"],
            original_project=Path(data["original_project"]),
            original_sha256=data["original_sha256"],
            working_project=Path(data["working_project"]),
            created_at=data["created_at"],
        )

    def assert_path_in_workspace(self, run_id: str, path: Path | str) -> Path:
        ws = self.load_run_workspace(run_id)
        if ws is None:
            raise WorkspaceError(
                f"unknown run workspace: {run_id}",
                code="workspace_not_found",
            )
        target = Path(path).resolve(strict=False)
        root = ws.root.resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise WorkspaceError(
                "path is outside run workspace",
                code="path_outside_workspace",
                details={"path": str(target), "workspace": str(root)},
            ) from exc
        return target


def project_lock_key(project_path: Path | str) -> str:
    """Stable key for per-project serialization."""
    return sha256_hex(str(Path(project_path).resolve(strict=False)).lower())[:32]
