"""Unit tests for COM session helpers (no live AEDT required)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from hfss_mcp.com_session import (
    _ironpython_runner_script,
    desktop_prog_id,
    ensure_graphical_project,
    list_com_projects,
    normalize_aedt_version,
    open_project_on_desktop,
)


def test_normalize_and_prog_id() -> None:
    assert normalize_aedt_version("2023.2") == "2023.2"
    assert normalize_aedt_version("23.2") == "2023.2"
    assert normalize_aedt_version("232") == "2023.2"
    assert desktop_prog_id("2023.2") == "Ansoft.ElectronicsDesktop.2023.2"
    assert desktop_prog_id(None) == "Ansoft.ElectronicsDesktop"


def test_open_project_activates_existing() -> None:
    import tempfile
    from pathlib import Path

    design = SimpleNamespace(GetName=lambda: "HFSSDesign1")
    proj = SimpleNamespace(
        SetActiveDesign=lambda _n: design,
        GetTopDesignList=lambda: ["HFSSDesign1"],
        GetPath=lambda: r"C:\proj",
        GetName=lambda: "Example1",
    )
    desktop = SimpleNamespace(
        GetProcessID=lambda: 42,
        GetProjectList=lambda: ["Example1"],
        SetActiveProject=lambda _n: proj,
        OpenProject=lambda _p: (_ for _ in ()).throw(AssertionError("should not open")),
    )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "Example1.aedt"
        p.write_text("x", encoding="utf-8")
        desktop.GetProjectList = lambda: [p.stem]
        info = open_project_on_desktop(desktop, p, "HFSSDesign1")
        assert info["process_id"] == 42
        assert info["project_name"] == p.stem
        assert info["design"] == "HFSSDesign1"


def test_ensure_graphical_uses_existing_com_project() -> None:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "Demo.aedt"
        p.write_text("x", encoding="utf-8")
        item = {
            "process_id": 99,
            "project_name": "Demo",
            "project_path": str(p.parent),
            "project_file": str(p),
            "designs": ["HFSSDesign1"],
            "source": "com_rot",
        }
        desktop = SimpleNamespace(
            GetProcessID=lambda: 99,
            SetActiveProject=lambda _n: SimpleNamespace(
                SetActiveDesign=lambda _d: None
            ),
        )
        with mock.patch(
            "hfss_mcp.com_session.find_com_project",
            return_value=(desktop, item),
        ):
            out = ensure_graphical_project(
                project_path=p,
                design_name="HFSSDesign1",
                version="2023.2",
            )
        assert out["process_id"] == 99
        assert out["design"] == "HFSSDesign1"


def test_runner_skips_set_active_when_already_on_project() -> None:
    from pathlib import Path

    text = _ironpython_runner_script(Path("req.json"), Path("out.json"))
    assert "oProject = oDesktop.GetActiveProject()" in text
    assert "switched = True" in text
    assert "if (not oProject) or (str(oProject.GetName()) != target_name):" in text


def test_list_com_projects_does_not_activate_the_only_open_project() -> None:
    proj = SimpleNamespace(
        GetName=lambda: "uwb_circular_notch",
        GetPath=lambda: r"C:\sandbox",
        GetTopDesignList=lambda: ["CircularMonopole"],
    )
    calls: list[str] = []

    desktop = SimpleNamespace(
        GetProcessID=lambda: 17044,
        GetProjectList=lambda: ["uwb_circular_notch"],
        GetActiveProject=lambda: proj,
        SetActiveProject=lambda name: calls.append(name) or proj,
    )
    items = list_com_projects(desktop)
    assert calls == []
    assert items[0]["project_name"] == "uwb_circular_notch"
    assert items[0]["designs"] == ["CircularMonopole"]
    assert items[0]["is_active_project"] is True
