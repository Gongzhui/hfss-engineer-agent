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
    optimetrics_list,
    optimetrics_types,
    parametric_create,
    parametric_export_table,
    parametric_start,
    project_save,
    report_create,
    report_export,
    report_list,
    report_types,
    session_attach,
    session_list,
    set_app,
    snapshot,
    variable_map,
    variables_set,
    view_capture,
    view_hide,
    view_show,
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

        attached = session_attach()
        assert attached["ok"] is True
        assert attached["bound"]["project_name"] == "ant"

        snap = snapshot()
        assert snap["ok"] is True
        assert snap["snapshot"]["revision"]
        assert "patch_w" in snap["snapshot"]["variables"]
        assert "Patch" in snap["snapshot"]["objects"]

        hidden = view_hide(names=["AirBox", "Ground"])
        assert hidden["ok"] is True
        assert "AirBox" in hidden["hidden"]
        shown = view_show(names=["AirBox"])
        assert shown["ok"] is True
        assert "AirBox" not in shown["hidden"]
        assert "Ground" in shown["hidden"]
        shown_all = view_show(all_objects=True)
        assert shown_all["hidden"] == []

        changed = variables_set(
            parameters=[{"name": "patch_w", "value": 11.0, "unit": "mm"}]
        )
        assert changed["ok"] is True
        assert changed["saved"] is False
        assert changed["needs_solve"] is True
        assert changed["readback"]["patch_w"]["value"] == 11.0
        aliased = variables_set(
            parameters=[{"variable": "patch_l", "value": 12.5, "unit": "mm"}]
        )
        assert aliased["ok"] is True
        assert aliased["needs_solve"] is True
        assert aliased["readback"]["patch_l"]["value"] == 12.5

        started = analyze_start(setup="Setup1")
        assert started["ok"] is True
        job_id = started["job_id"]
        status = analyze_status(job_id)
        assert status["job"]["state"] == "completed"

        types = report_types()
        assert any(item["id"] == "modal_s" for item in types["types"])
        listed_empty = report_list()
        assert listed_empty["ok"] is True
        assert listed_empty["reports"] == []
        missing = report_export("S11")
        assert missing["ok"] is False
        assert missing["error"]["code"] == "report_not_in_results"
        created = report_create(report_type="modal_s", setup="Setup1")
        assert created["report"]["name"] == "S11"
        assert created["report"]["in_results"] is True
        listed = report_list()
        assert any(item["name"] == "S11" for item in listed["reports"])
        exported = report_export(created["report"]["report_id"])
        assert exported["format"] == "csv"
        assert exported["csv_format"] == "single"
        assert exported["traces"] == 1
        assert Path(exported["path"]).is_file()

        pictured = view_capture()
        assert Path(pictured["path"]).is_file()
        assert pictured["hidden"] == []
        fitted = view_capture(fit=["Patch"])
        assert fitted["fit"] == ["Patch"]

        z_rep = report_create(report_type="terminal_z", setup="Setup1")
        z_out = report_export(z_rep["report"]["report_id"])
        assert z_out["format"] == "csv"
        assert "re,im" in Path(z_out["path"]).read_text(encoding="utf-8").splitlines()[0]

        ff_rep = report_create(report_type="farfield_2d", setup="Setup1", frequency="2.4GHz")
        ff_out = report_export(ff_rep["report"]["report_id"])
        assert ff_out["format"] == "csv"

        missing_field = report_export("Field_Patch_2_4GHz")
        assert missing_field["ok"] is False
        assert missing_field["error"]["code"] == "report_not_in_results"
        field_rep = report_create(
            report_type="field_face",
            setup="Setup1",
            face="Patch",
            frequency="2.4GHz",
        )
        assert field_rep["report"]["tree"] == "Field Overlays"
        assert field_rep["report"]["quantity"] == "Mag_E"
        listed_field = report_list()
        assert any(item["name"] == field_rep["report"]["name"] for item in listed_field["reports"])
        field_out = report_export(field_rep["report"]["report_id"])
        assert field_out["format"] == "image"
        assert Path(field_out["path"]).is_file()

        jsurf = report_create(
            report_type="field_face",
            setup="Setup1",
            face="Patch",
            frequency="2.4GHz",
            quantity="Mag_Jsurf",
        )
        assert jsurf["ok"] is True
        assert jsurf["report"]["quantity"] == "Mag_Jsurf"
        assert jsurf["report"]["name"] != field_rep["report"]["name"]

        bad_qty = report_create(
            report_type="field_face",
            setup="Setup1",
            face="Patch",
            frequency="2.4GHz",
            quantity="Mag_H",
        )
        assert bad_qty["ok"] is False
        assert bad_qty["error"]["code"] == "field_quantity_unknown"

        opt_types = optimetrics_types()
        assert [item["id"] for item in opt_types["types"]] == ["parametric"]
        assert optimetrics_list()["setups"] == []
        missing_para = parametric_export_table("Parametric_patch_w")
        assert missing_para["ok"] is False
        assert missing_para["error"]["code"] == "report_not_in_results"
        missing_start = parametric_start("Parametric_patch_w")
        assert missing_start["ok"] is False
        assert missing_start["error"]["code"] == "report_not_in_results"
        para = parametric_create(
            sweeps=[
                {
                    "variable": "patch_w",
                    "variation": "linear_step",
                    "start": 10.0,
                    "stop": 11.0,
                    "step": 0.5,
                    "unit": "mm",
                }
            ]
        )
        assert para["ok"] is True
        assert para["setup"]["name"] == "Parametric_patch_w"
        assert para["setup"]["tree"] == "Optimetrics"
        assert para["setup"]["points"] == 3
        assert any(item["name"] == "Parametric_patch_w" for item in optimetrics_list()["setups"])
        table = parametric_export_table("Parametric_patch_w")
        assert Path(table["path"]).is_file()
        started = parametric_start("Parametric_patch_w")
        assert started["ok"] is True
        assert started["done"] is True
        assert started["poll"] is None
        assert started["job"]["kind"] == "parametric"
        assert started["job"]["state"] == "completed"
        edited = parametric_create(
            name="Parametric_patch_w",
            sweeps=[
                {
                    "variable": "patch_w",
                    "variation": "linear_count",
                    "start": 10.0,
                    "stop": 12.0,
                    "count": 5,
                    "unit": "mm",
                },
                {
                    "variable": "patch_l",
                    "variation": "linear_count",
                    "start": 11.0,
                    "stop": 13.0,
                    "count": 3,
                    "unit": "mm",
                },
            ],
        )
        assert edited["ok"] is True
        assert edited["setup"]["reused"] is True
        assert edited["setup"]["edited"] is True
        assert edited["setup"]["points"] == 15
        family = report_create(
            "modal_s",
            name="Parametric_patch_w_S11",
            parametric="Parametric_patch_w",
        )
        assert family["ok"] is True
        assert family["report"]["families_applied"] is True
        assert family["report"]["family_variables"] == ["patch_w", "patch_l"]
        assert "patch_w" not in family["report"]["nominal_variables"]
        family_out = report_export(family["report"]["report_id"])
        family_text = Path(family_out["path"]).read_text(encoding="utf-8")
        assert family_text.splitlines()[0] == "freq_ghz,variation,s11_db"
        assert family_out["csv_format"] == "family"
        assert family_out["traces"] == 2
        assert family_out["labeled"] is True
        assert "patch_w='10mm'" in family_text
        assert "stale_solution" not in family_out
        pinned = report_create("modal_s", name="S11_nominal", families=[])
        assert pinned["ok"] is True
        assert pinned["report"]["families_applied"] is False
        assert pinned["report"]["family_variables"] == []
        assert "patch_w" in pinned["report"]["nominal_variables"]
        pinned_out = report_export(pinned["report"]["report_id"])
        assert pinned_out["csv_format"] == "single"
        assert pinned_out["traces"] == 1
        isolated = report_create("modal_s", name="S11_after_sweeps")
        assert isolated["ok"] is True
        assert isolated["report"]["families_applied"] is False
        assert isolated["report"]["family_variables"] == []
        assert "patch_w" in isolated["report"]["nominal_variables"]
        reused_family = report_create(
            "modal_s",
            name="Parametric_patch_w_S11",
            parametric="Parametric_patch_w",
        )
        assert reused_family["ok"] is False
        assert reused_family["error"]["code"] == "report_exists"
        named_sweep = parametric_create(
            name="Parametric_alias",
            sweeps=[
                {
                    "name": "patch_w",
                    "variation": "values",
                    "values": [10.0, 11.0],
                    "unit": "mm",
                }
            ],
        )
        assert named_sweep["ok"] is True
        assert named_sweep["setup"]["variables"] == ["patch_w"]
        assert ctx._fake is not None
        ctx._fake._optimetrics[0]["variables"] = []
        filled = next(
            item
            for item in optimetrics_list()["setups"]
            if item["name"] == "Parametric_patch_w"
        )
        assert filled["variables"] == ["patch_w", "patch_l"]
        dirty = variables_set(
            parameters=[{"name": "patch_w", "value": 10.5, "unit": "mm"}]
        )
        assert dirty["needs_solve"] is True
        stale = report_export(created["report"]["report_id"])
        assert stale["stale_solution"] is True
        joint = parametric_create(
            name="Parametric_joint",
            sweeps=[
                {
                    "variable": "patch_w",
                    "variation": "linear_count",
                    "start": 10.0,
                    "stop": 12.0,
                    "count": 9,
                    "unit": "mm",
                },
                {
                    "variable": "patch_l",
                    "variation": "linear_count",
                    "start": 11.0,
                    "stop": 13.0,
                    "count": 9,
                    "unit": "mm",
                },
            ],
        )
        assert joint["ok"] is True
        assert joint["setup"]["points"] == 81
        too_wide = parametric_create(
            sweeps=[
                {
                    "variable": "patch_w",
                    "start": 1.0,
                    "stop": 999.0,
                    "step": 1.0,
                    "unit": "mm",
                }
            ]
        )
        assert too_wide["ok"] is False
        assert too_wide["error"]["code"] == "out_of_bounds"
        too_many = parametric_create(
            sweeps=[
                {
                    "variable": "patch_w",
                    "variation": "linear_count",
                    "start": 10.0,
                    "stop": 11.0,
                    "count": 257,
                    "unit": "mm",
                }
            ]
        )
        assert too_many["ok"] is False
        assert too_many["error"]["code"] == "parametric_too_many_points"

        mapped = variable_map(names=["patch_w"])
        assert mapped["ok"] is True
        assert "patch_w" in mapped["usages"]

        saved = project_save(mode="save_as", path=str(tmp_path / "v2.aedt"))
        assert saved["ok"] is True
        assert Path(tmp_path / "v2.aedt").is_file()
    finally:
        set_app(None)
        ctx.close()


def test_hfss_message_failure_is_setup_specific() -> None:
    from hfss_mcp.live import crash_message, failure_message_for_setup

    messages = [
        "Error in command execution",
        "Report S11 has no data for export",
        "Script macro error: Solution 'P_feed_ground' was not found.",
    ]
    hit = failure_message_for_setup(messages, "P_feed_ground")
    assert hit is not None
    assert "P_feed_ground" in hit
    assert failure_message_for_setup(messages, "P_g1_slot") is None

    crash_lines = [
        "Parametric analysis started",
        "The solver process has been terminated.",
    ]
    crash = crash_message(crash_lines)
    assert crash is not None
    assert "terminated" in crash.lower()
    assert failure_message_for_setup(crash_lines, "P_g1_slot") is None
    assert failure_message_for_setup(messages, "Setup1") is None
