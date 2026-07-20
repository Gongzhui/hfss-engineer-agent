"""Unit tests for PyAedtAdapter with an injected fake Hfss object (no AEDT launch)."""

from __future__ import annotations

from pathlib import Path

from hfss_mcp.adapter.pyaedt_adapter import PyAedtAdapter
from hfss_mcp.domain import ParameterValue, ParameterVector


class _Vm:
    def __init__(self) -> None:
        self.independent_design_variables = {
            "patch_w": "10mm",
            "patch_l": "12mm",
        }

    def get_expression(self, name: str) -> str:
        return self.independent_design_variables[name]

    def set_variable(self, name: str, *, expression: str) -> None:
        self.independent_design_variables[name] = expression


class _FakeHfss:
    def __init__(self) -> None:
        self.variable_manager = _Vm()
        self.setup_names = ["Setup1"]
        self.project_name = "Demo"
        self.design_name = "HFSSDesign1"
        self._analyzed: list[str] = []

    def analyze_setup(self, setup: str, blocking: bool = True) -> None:
        self._analyzed.append(setup)
        if blocking:
            return


def test_pyaedt_adapter_apply_with_injected_hfss(tmp_path: Path) -> None:
    project = tmp_path / "demo.aedt"
    project.write_bytes(b"proj")
    hfss = _FakeHfss()
    adapter = PyAedtAdapter(hfss=hfss, new_desktop=False)
    snap = adapter.attach_project(project, "HFSSDesign1")
    assert snap.revision
    vector = ParameterVector(
        values=[
            ParameterValue(name="patch_w", value=11.0, unit="mm"),
            ParameterValue(name="patch_l", value=12.0, unit="mm"),
        ]
    )
    result = adapter.apply_parameter_vector(vector, expected_revision=snap.revision)
    assert result.ok is True
    assert result.readback["patch_w"].value == 11.0
    dest = tmp_path / "ckpt" / "demo.aedt"
    adapter.save_project_copy(dest)
    assert dest.is_file()
    # Cancel is honest
    handle = adapter.start_solve("Setup1")
    cancel = adapter.cancel_solve(handle)
    assert cancel.cancelled is False
    assert cancel.honest_limitation is not None
    adapter.disconnect(close_desktop=False)
