"""Checkpoint create + hash integrity tests."""

from __future__ import annotations

from pathlib import Path

from hfss_mcp.adapter.fake import FakeAdapter
from hfss_mcp.checkpoint import CheckpointService
from hfss_mcp.domain import ParameterValue
from hfss_mcp.ids import file_sha256


def test_checkpoint_create_hash_no_overwrite(tmp_path: Path) -> None:
    original = tmp_path / "user_project.aedt"
    original.write_bytes(b"ORIGINAL_BYTES_v1")
    original_hash = file_sha256(original)

    adapter = FakeAdapter(
        project_path=original,
        variables={
            "patch_w": ParameterValue(name="patch_w", value=1.0, unit="mm"),
        },
    )
    adapter.attach_project(original, "HFSSDesign1")

    svc = CheckpointService(tmp_path / "workspace")
    record = svc.create_checkpoint(
        adapter=adapter,
        original_project_path=original,
        manifest_id="abc",
        run_id="run1",
        trial_id="trial1",
        source_file=original,
    )

    assert Path(record.checkpoint_path).is_file()
    assert Path(record.checkpoint_path).resolve() != original.resolve()
    assert record.sha256 == file_sha256(record.checkpoint_path)
    # Original untouched
    assert original.read_bytes() == b"ORIGINAL_BYTES_v1"
    assert file_sha256(original) == original_hash
    assert record.manifest_id == "abc"
    assert record.run_id == "run1"
    assert record.trial_id == "trial1"

    listed = svc.list_checkpoints(run_id="run1")
    assert len(listed) == 1
    assert listed[0].checkpoint_id == record.checkpoint_id


def test_checkpoint_via_adapter_copy(tmp_path: Path) -> None:
    original = tmp_path / "proj.aedt"
    original.write_bytes(b"src")
    adapter = FakeAdapter(project_path=original)
    adapter.attach_project(original, "HFSSDesign1")
    svc = CheckpointService(tmp_path / "ws")
    record = svc.create_checkpoint(
        adapter=adapter,
        original_project_path=original,
        manifest_id="m",
        run_id="r",
    )
    assert Path(record.checkpoint_path).read_bytes().startswith(b"FAKE_AEDT_PROJECT")
