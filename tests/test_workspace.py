"""Workspace copy never mutates original project."""

from __future__ import annotations

from pathlib import Path

from hfss_mcp.ids import file_sha256
from hfss_mcp.workspace import WorkspaceService


def test_workspace_copy_preserves_original(tmp_path: Path) -> None:
    original = tmp_path / "user.aedt"
    original.write_bytes(b"USER_ORIGINAL_BYTES")
    digest = file_sha256(original)
    svc = WorkspaceService(tmp_path / "ws")
    ws = svc.create_run_workspace(run_id="run1", original_project=original)
    assert ws.working_project != original
    assert ws.working_project.read_bytes() == b"USER_ORIGINAL_BYTES"
    ws.working_project.write_bytes(b"MUTATED")
    assert original.read_bytes() == b"USER_ORIGINAL_BYTES"
    assert file_sha256(original) == digest
    assert ws.verify_original_unchanged()
