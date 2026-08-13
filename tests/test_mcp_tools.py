"""MCP tool surface schema/smoke for the engineer-session tools."""

from __future__ import annotations

from pathlib import Path

from hfss_mcp.app import AppContext, build_allowlist_for_tests
from hfss_mcp.server import (
    FORBIDDEN_TOOL_NAMES,
    PUBLIC_TOOL_NAMES,
    allowlist_load,
    analyze_start,
    analyze_status,
    health,
    list_registered_tool_names,
    project_save,
    report_create,
    report_export,
    report_types,
    session_list,
    set_app,
    snapshot,
    variable_map,
    variables_set,
    view_capture,
)


def test_public_tools_registered() -> None:
    names = set(list_registered_tool_names())
    for required in PUBLIC_TOOL_NAMES:
        assert required in names, f"missing tool {required}"
    assert "trial_start" not in names
    assert "run_start" not in names


def test_forbidden_tools_absent() -> None:
    names = set(list_registered_tool_names())
    for banned in FORBIDDEN_TOOL_NAMES:
        assert banned not in names
    joined = " ".join(names).lower()
    assert "run_python" not in joined
    assert "exec" not in names


def test_tool_smoke_with_injected_app(tmp_path: Path) -> None:
    project = tmp_path / "ant.aedt"
    project.write_bytes(b"FAKE_SOURCE_PROJECT\n")
    ctx = AppContext(data_dir=tmp_path / "data", use_fake=True)
    set_app(ctx)
    try:
        h = health()
        assert h["ok"] is True
        assert h["adapter"] == "fake"
        assert h["real_hfss_ready"] is False
        assert h["connection_mode"] == "in_process_fake"

        sessions = session_list()
        assert sessions["ok"] is True

        loaded = allowlist_load(
            allowlist=build_allowlist_for_tests(project).model_dump(mode="json", by_alias=True)
        )
        assert loaded["ok"] is True

        snap = snapshot()
        assert snap["ok"] is True
        assert snap["snapshot"]["revision"]
        assert "patch_w" in snap["snapshot"]["variables"]

        changed = variables_set(
            parameters=[{"name": "patch_w", "value": 11.0, "unit": "mm"}]
        )
        assert changed["ok"] is True
        assert changed["saved"] is False
        assert changed["readback"]["patch_w"]["value"] == 11.0

        started = analyze_start(setup="Setup1")
        assert started["ok"] is True
        job_id = started["job_id"]
        status = analyze_status(job_id)
        assert status["job"]["state"] == "completed"

        types = report_types()
        assert any(item["id"] == "modal_s" for item in types["types"])
        created = report_create(report_type="modal_s", setup="Setup1")
        exported = report_export(created["report"]["report_id"])
        assert exported["format"] == "csv"
        assert Path(exported["path"]).is_file()

        pictured = view_capture()
        assert Path(pictured["path"]).is_file()

        z_rep = report_create(report_type="terminal_z", setup="Setup1")
        z_out = report_export(z_rep["report"]["report_id"])
        assert z_out["format"] == "csv"
        assert "re,im" in Path(z_out["path"]).read_text(encoding="utf-8").splitlines()[0]

        ff_rep = report_create(report_type="farfield_2d", setup="Setup1", frequency="2.4GHz")
        ff_out = report_export(ff_rep["report"]["report_id"])
        assert ff_out["format"] == "csv"

        field_rep = report_create(
            report_type="field_face",
            setup="Setup1",
            face="Patch",
            frequency="2.4GHz",
        )
        field_out = report_export(field_rep["report"]["report_id"])
        assert field_out["format"] == "image"
        assert Path(field_out["path"]).is_file()

        mapped = variable_map(names=["patch_w"])
        assert mapped["ok"] is True
        assert "patch_w" in mapped["usages"]

        saved = project_save(mode="save_as", path=str(tmp_path / "v2.aedt"))
        assert saved["ok"] is True
        assert Path(tmp_path / "v2.aedt").is_file()
    finally:
        set_app(None)
        ctx.close()
