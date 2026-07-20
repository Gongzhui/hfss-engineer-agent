"""FakeAdapter parameter transaction tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from hfss_mcp.adapter.fake import FakeAdapter
from hfss_mcp.domain import ParameterValue, ParameterVector
from hfss_mcp.errors import ReadbackMismatchError, RevisionConflictError


def _adapter(tmp_path: Path) -> FakeAdapter:
    project = tmp_path / "demo.aedt"
    project.write_bytes(b"src")
    return FakeAdapter(
        project_path=project,
        variables={
            "patch_w": ParameterValue(name="patch_w", value=10.0, unit="mm"),
            "patch_l": ParameterValue(name="patch_l", value=12.0, unit="mm"),
        },
    )


def test_apply_success_with_diff_and_readback(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    snap = adapter.attach_project(tmp_path / "demo.aedt", "HFSSDesign1")
    vector = ParameterVector(
        values=[
            ParameterValue(name="patch_w", value=11.5, unit="mm"),
            ParameterValue(name="patch_l", value=12.0, unit="mm"),
        ]
    )
    result = adapter.apply_parameter_vector(vector, expected_revision=snap.revision)
    assert result.ok is True
    assert result.revision_after != result.revision_before
    assert result.readback["patch_w"].value == 11.5
    changed = [d for d in result.diff if d.name == "patch_w"][0]
    assert changed.changed is True
    assert changed.before_value == 10.0
    assert changed.after_value == 11.5


def test_revision_conflict(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.attach_project(tmp_path / "demo.aedt", "HFSSDesign1")
    vector = ParameterVector(
        values=[
            ParameterValue(name="patch_w", value=11.0, unit="mm"),
            ParameterValue(name="patch_l", value=12.0, unit="mm"),
        ]
    )
    with pytest.raises(RevisionConflictError) as exc:
        adapter.apply_parameter_vector(vector, expected_revision="deadbeef")
    assert exc.value.code == "revision_conflict"


def test_readback_mismatch_does_not_report_success(tmp_path: Path) -> None:
    project = tmp_path / "demo.aedt"
    project.write_bytes(b"src")
    adapter = FakeAdapter(
        project_path=project,
        variables={
            "patch_w": ParameterValue(name="patch_w", value=10.0, unit="mm"),
            "patch_l": ParameterValue(name="patch_l", value=12.0, unit="mm"),
        },
        fail_readback_names={"patch_w"},
    )
    snap = adapter.attach_project(project, "HFSSDesign1")
    vector = ParameterVector(
        values=[
            ParameterValue(name="patch_w", value=11.0, unit="mm"),
            ParameterValue(name="patch_l", value=12.0, unit="mm"),
        ]
    )
    with pytest.raises(ReadbackMismatchError) as exc:
        adapter.apply_parameter_vector(vector, expected_revision=snap.revision)
    assert exc.value.code == "readback_mismatch"
    # Rolled back
    current = adapter.read_variables(["patch_w"])["patch_w"].value
    assert current == 10.0


def test_cancel_supported(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.attach_project(tmp_path / "demo.aedt", "HFSSDesign1")
    # Long solve
    adapter._solve_duration_s = 10.0
    handle = adapter.start_solve("Setup1")
    result = adapter.cancel_solve(handle)
    assert result.cancelled is True
    assert result.state.value == "cancelled"


def test_cancel_honest_limitation(tmp_path: Path) -> None:
    project = tmp_path / "demo.aedt"
    project.write_bytes(b"src")
    adapter = FakeAdapter(
        project_path=project,
        cancel_supported=False,
        solve_duration_s=10.0,
    )
    adapter.attach_project(project, "HFSSDesign1")
    handle = adapter.start_solve("Setup1")
    result = adapter.cancel_solve(handle)
    assert result.cancelled is False
    assert result.honest_limitation is not None
