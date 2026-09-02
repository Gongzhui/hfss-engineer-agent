"""Real AEDT 2023 R2: attach to a user-style GUI session (COM ROT)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from hfss_mcp.app import AppContext
from hfss_mcp.errors import PolicyError
from hfss_mcp.live import list_rot_sessions

pytestmark = pytest.mark.real_aedt

AEDT_EXE = Path(r"C:\Program Files\AnsysEM\v232\Win64\ansysedt.exe")


def _aedt_available() -> bool:
    return AEDT_EXE.is_file()


def _ensure_user_style_desktop() -> None:
    sessions = list_rot_sessions(version="2023.2")
    if sessions:
        return
    subprocess.Popen(
        [str(AEDT_EXE)],
        cwd=str(AEDT_EXE.parent),
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    deadline = time.time() + 90
    while time.time() < deadline:
        if list_rot_sessions(version="2023.2"):
            time.sleep(6)
            return
        time.sleep(1)
    pytest.fail("AEDT GUI did not become COM-visible")


def _rot_projects() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sess in list_rot_sessions(version="2023.2"):
        pid = sess.get("process_id")
        for item in sess.get("projects") or []:
            rec = dict(item)
            rec["process_id"] = pid
            out.append(rec)
    return out


def _pick_open_sandbox() -> dict[str, Any]:
    projects = _rot_projects()
    if not projects:
        pytest.skip("no COM-visible AEDT project is open")
    preferred = next(
        (p for p in projects if str(p.get("project_name") or "") == "Project6"),
        None,
    )
    if preferred:
        return preferred
    active = next((p for p in projects if p.get("is_active_project")), None)
    return active or projects[0]


def test_live_open_project_table_sync_and_constraints(tmp_path: Path) -> None:
    """Exercise the postmortem tool layer against whatever project the user has open."""
    if not _aedt_available():
        pytest.skip("AEDT 2023 R2 not installed")
    _ensure_user_style_desktop()
    sessions = list_rot_sessions(version="2023.2")
    assert sessions, "expected a COM-visible Desktop"
    pid_before = {s["process_id"] for s in sessions}
    opened = _pick_open_sandbox()
    project_name = str(opened.get("project_name") or "")
    designs = [str(x) for x in (opened.get("designs") or []) if str(x).strip()]
    design_name = designs[0] if designs else "HFSSDesign1"
    project_file = str(
        opened.get("project_file")
        or Path(str(opened.get("project_path") or "")) / f"{project_name}.aedt"
    )

    ctx = AppContext(data_dir=tmp_path / "hfss_mcp_data", use_fake=False)
    try:
        loaded = ctx.allowlist_load(
            allowlist={
                "project_path": project_file,
                "project_name": project_name,
                "design_name": design_name,
                "parameters": [
                    {"name": "a", "unit": "mm", "min": 0.1, "max": 20.0},
                    {"name": "b", "unit": "mm", "min": 0.1, "max": 20.0},
                    {"name": "c", "unit": "mm", "min": 0.1, "max": 20.0},
                ],
                "constraints": ["a + b <= c + 5"],
            }
        )
        assert loaded["ok"] is True
        snap0 = ctx.snapshot()["snapshot"]
        variables = snap0.get("variables") or {}
        names = [n for n in ("a", "b", "c") if n in variables]
        if len(names) < 3:
            pytest.skip(
                f"open project {project_name} needs design variables a, b, c to test the table path"
            )
        objects = [str(x) for x in (snap0.get("objects") or []) if str(x).strip()]
        assert loaded["constraints"] == ["a + b <= c + 5"]

        original = {n: float(variables[n]["value"]) for n in names}
        changed = ctx.variables_set([{"name": "a", "value": 1.2, "unit": "mm"}])
        assert changed["ok"] is True
        assert abs(changed["readback"]["a"]["value"] - 1.2) < 1e-6
        with pytest.raises(PolicyError) as ei:
            ctx.variables_set(
                [
                    {"name": "a", "value": 10.0, "unit": "mm"},
                    {"name": "b", "value": 10.0, "unit": "mm"},
                    {"name": "c", "value": 1.0, "unit": "mm"},
                ]
            )
        assert ei.value.code == "constraint_violated"

        off = ctx.parametric_create(
            name="P_live_off_grid",
            sweeps=[
                {
                    "variable": "a",
                    "variation": "linear_step",
                    "start": 1.0,
                    "stop": 1.4,
                    "step": 0.3,
                    "unit": "mm",
                }
            ],
        )
        assert off["setup"]["points"] == 3

        table = ctx.parametric_create(
            name="P_live_table",
            sweeps=[
                {
                    "variation": "table",
                    "rows": [
                        {"a": 1.0, "b": 1.1},
                        {"a": 1.2, "b": 1.3},
                        {"a": 1.4, "b": 1.5},
                    ],
                }
            ],
        )
        assert table["setup"]["points"] == 3
        assert table["setup"]["sync_indices"] == [0, 1]
        listed = ctx.optimetrics_list()
        assert any(item.get("name") == "P_live_table" for item in listed["setups"])
        exported = ctx.parametric_export_table("P_live_table")
        csv_text = Path(exported["path"]).read_text(encoding="utf-8")
        data_rows = [
            line
            for line in csv_text.splitlines()
            if line.strip() and not line.lstrip().startswith("*")
        ]
        assert len(data_rows) == 3, csv_text
        compact = csv_text.replace(" ", "")
        assert "1.4mm,1.5mm" in compact
        assert "1.4mm,1.1mm" not in compact
        assert exported["context"].get("c") is not None

        with pytest.raises(PolicyError) as bad:
            ctx.parametric_create(
                name="P_live_bad",
                sweeps=[
                    {
                        "variation": "table",
                        "rows": [{"a": 10.0, "b": 10.0, "c": 1.0}],
                    }
                ],
            )
        assert bad.value.code == "parametric_row_infeasible"

        if objects:
            hidden = objects[0]
            ctx.view_hide([hidden])
            cap = ctx.view_capture(fit=[hidden])
            assert cap["hidden_in_fit"] == [hidden]
            assert hidden in cap["warning"]
            pictured = ctx.view_capture()
            assert Path(pictured["path"]).is_file()
            ctx.view_show(all_objects=True)

        ctx.variables_set(
            [{"name": n, "value": original[n], "unit": "mm"} for n in names]
        )
        still = {s["process_id"] for s in list_rot_sessions(version="2023.2")}
        assert pid_before & still, "attach must not quit the user's Desktop"
    finally:
        ctx.close()
    still_after = {s["process_id"] for s in list_rot_sessions(version="2023.2")}
    assert pid_before & still_after, "closing AppContext must not quit AEDT"


def test_live_com_attach_snapshot_and_set(tmp_path: Path) -> None:
    if not _aedt_available():
        pytest.skip("AEDT 2023 R2 not installed")
    _ensure_user_style_desktop()
    sessions = list_rot_sessions(version="2023.2")
    assert sessions, "expected a COM-visible Desktop"
    pid_before = {s["process_id"] for s in sessions}
    opened = _pick_open_sandbox()
    project_name = str(opened.get("project_name") or "")
    designs = [str(x) for x in (opened.get("designs") or []) if str(x).strip()]
    design_name = designs[0] if designs else "HFSSDesign1"
    project_file = str(
        opened.get("project_file")
        or Path(str(opened.get("project_path") or "")) / f"{project_name}.aedt"
    )

    ctx = AppContext(data_dir=tmp_path / "hfss_mcp_data", use_fake=False)
    try:
        ctx.allowlist_load(
            allowlist={
                "project_path": project_file,
                "project_name": project_name,
                "design_name": design_name,
                "parameters": [
                    {"name": "a", "unit": "mm", "min": 0.1, "max": 20.0},
                    {"name": "gap", "unit": "mm", "min": 0.5, "max": 3.0},
                ],
            }
        )
        snap = ctx.snapshot()
        assert snap["ok"] is True
        assert snap["snapshot"]["design_name"]
        assert snap["snapshot"]["process_id"] in pid_before
        variables = snap["snapshot"]["variables"]
        knob = next((name for name in ("a", "gap") if name in variables), None)
        if knob is None:
            pytest.skip(f"open project {project_name} has no a/gap variable to set")
        original = float(variables[knob]["value"])
        unit = str(variables[knob].get("unit") or "mm")
        if knob == "gap":
            target = 1.3 if abs(original - 1.3) > 1e-6 else 1.4
        else:
            target = min(max(original + 0.2, 0.1), 20.0)
            if abs(target - original) < 1e-6:
                target = min(original + 0.3, 20.0)
        changed = ctx.variables_set([{"name": knob, "value": target, "unit": unit}])
        assert changed["ok"] is True
        assert changed["saved"] is False
        assert abs(changed["readback"][knob]["value"] - target) < 1e-6
        again = ctx.snapshot()
        assert abs(again["snapshot"]["variables"][knob]["value"] - target) < 1e-6
        pictured = ctx.view_capture()
        assert Path(pictured["path"]).is_file()
        mapped = ctx.variable_map(names=[knob])
        assert mapped["ok"] is True
        ctx.variables_set([{"name": knob, "value": original, "unit": unit}])
        still = {s["process_id"] for s in list_rot_sessions(version="2023.2")}
        assert pid_before & still, "attach must not quit the user's Desktop"
    finally:
        ctx.close()
    still_after = {s["process_id"] for s in list_rot_sessions(version="2023.2")}
    assert pid_before & still_after, "closing AppContext must not quit AEDT"


def test_live_session_list_and_snapshot_without_allowlist(tmp_path: Path) -> None:
    if not _aedt_available():
        pytest.skip("AEDT 2023 R2 not installed")
    _ensure_user_style_desktop()
    opened = _pick_open_sandbox()
    project_name = str(opened.get("project_name") or "")
    designs = [str(x) for x in (opened.get("designs") or []) if str(x).strip()]
    design_name = designs[0] if designs else None
    ctx = AppContext(data_dir=tmp_path / "hfss_mcp_data", use_fake=False)
    try:
        listed = ctx.session_list()
        assert listed["ok"] is True
        assert project_name in listed["open_projects"]
        snap = ctx.snapshot()
        assert snap["ok"] is True
        assert snap["bound"]["project_name"] == project_name
        assert snap["allowlist_loaded"] is False
        attached = ctx.session_attach(
            project_name=project_name,
            design_name=design_name,
        )
        assert attached["bound"]["project_name"] == project_name
    finally:
        ctx.close()
