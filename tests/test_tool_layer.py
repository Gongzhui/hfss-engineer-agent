"""Tool-layer changes: table sweeps, ledger, summarize, constraints, view warning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hfss_mcp.app import AppContext, build_allowlist_for_tests
from hfss_mcp.errors import PolicyError
from hfss_mcp.metrics import summarize_modal_s_csv, summarize_terminal_z_csv


def _ctx(tmp_path: Path) -> AppContext:
    return AppContext(data_dir=tmp_path / "data", use_fake=True)


def _load(ctx: AppContext, project: Path, **kwargs: object) -> None:
    ctx.allowlist_load(
        allowlist=build_allowlist_for_tests(project, **kwargs).model_dump(
            mode="json", by_alias=True
        )
    )


def test_linear_step_points_match_hfss_lin(tmp_path: Path, project_file: Path) -> None:
    ctx = _ctx(tmp_path)
    try:
        _load(ctx, project_file)
        out = ctx.parametric_create(
            name="P_off_grid",
            sweeps=[
                {
                    "variable": "patch_w",
                    "variation": "linear_step",
                    "start": 10.0,
                    "stop": 11.0,
                    "step": 0.3,
                    "unit": "mm",
                }
            ],
        )
        assert out["setup"]["points"] == 5
    finally:
        ctx.close()


def test_table_sweep_is_zipped_not_cartesian(tmp_path: Path, project_file: Path) -> None:
    ctx = _ctx(tmp_path)
    try:
        _load(ctx, project_file)
        out = ctx.parametric_create(
            name="P_table",
            sweeps=[
                {
                    "variation": "table",
                    "rows": [
                        {"patch_w": 10.0, "patch_l": 11.0},
                        {"patch_w": 12.0, "patch_l": 13.0},
                        {"patch_w": 14.0, "patch_l": 15.0},
                    ],
                }
            ],
        )
        assert out["ok"] is True
        assert out["setup"]["points"] == 3
        assert out["setup"]["sync_indices"] == [0, 1]
        assert out["setup"]["variables"] == ["patch_w", "patch_l"]
        table = ctx.parametric_export_table("P_table")
        text = Path(table["path"]).read_text(encoding="utf-8")
        assert "10.0" in text and "15.0" in text
        started = ctx.parametric_start("P_table")
        assert started["done"] is True
        listed = ctx.solved_points_list(source="P_table")
        assert listed["count"] == 3
        assert listed["points"][0]["variables"]["patch_w"] == 10.0
    finally:
        ctx.close()


def test_constraints_block_variables_set_and_rows(
    tmp_path: Path, project_file: Path
) -> None:
    ctx = _ctx(tmp_path)
    try:
        _load(ctx, project_file, constraints=["patch_w < patch_l"])
        loaded = ctx.allowlist_load(
            allowlist=build_allowlist_for_tests(
                project_file, constraints=["patch_w < patch_l"]
            ).model_dump(mode="json", by_alias=True)
        )
        assert loaded["constraints"] == ["patch_w < patch_l"]
        ctx.variables_set(
            [{"name": "patch_w", "value": 10.0, "unit": "mm"},
             {"name": "patch_l", "value": 20.0, "unit": "mm"}]
        )
        with pytest.raises(PolicyError) as ei:
            ctx.variables_set([{"name": "patch_w", "value": 21.0, "unit": "mm"}])
        assert ei.value.code == "constraint_violated"
        with pytest.raises(PolicyError) as bad:
            ctx.parametric_create(
                name="P_bad",
                sweeps=[
                    {
                        "variation": "table",
                        "rows": [
                            {"patch_w": 10.0, "patch_l": 20.0},
                            {"patch_w": 12.0, "patch_l": 11.0},
                        ],
                    }
                ],
            )
        assert bad.value.code == "parametric_row_infeasible"
        assert bad.value.details["rows"][0]["index"] == 1
    finally:
        ctx.close()


def test_export_table_adds_context_columns(tmp_path: Path, project_file: Path) -> None:
    ctx = _ctx(tmp_path)
    try:
        _load(ctx, project_file)
        ctx.variables_set(
            [
                {"name": "patch_w", "value": 10.0, "unit": "mm"},
                {"name": "patch_l", "value": 18.0, "unit": "mm"},
            ]
        )
        ctx.parametric_create(
            name="P_w",
            sweeps=[
                {
                    "variable": "patch_w",
                    "variation": "values",
                    "values": [10.0, 11.0],
                    "unit": "mm",
                }
            ],
        )
        table = ctx.parametric_export_table("P_w")
        assert table["context"]["patch_l"] == 18.0
        header = Path(table["path"]).read_text(encoding="utf-8").splitlines()[0]
        assert "patch_l" in header
    finally:
        ctx.close()


def test_jobs_and_ledger_survive_restart(tmp_path: Path, project_file: Path) -> None:
    allowlist_path = tmp_path / "allowlist.json"
    allowlist_path.write_text(
        json.dumps(
            build_allowlist_for_tests(project_file).model_dump(mode="json", by_alias=True)
        ),
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    ctx1 = AppContext(data_dir=data_dir, use_fake=True)
    try:
        ctx1.allowlist_load(path=str(allowlist_path))
        ctx1.parametric_create(
            name="P_restart",
            sweeps=[
                {
                    "variable": "patch_w",
                    "variation": "values",
                    "values": [10.0, 11.0],
                    "unit": "mm",
                }
            ],
        )
        started = ctx1.parametric_start("P_restart")
        job_id = started["job_id"]
        assert started["done"] is True
    finally:
        ctx1.close()

    ctx2 = AppContext(data_dir=data_dir, use_fake=True)
    try:
        status = ctx2.analyze_status(job_id)
        assert status["ok"] is True
        assert status["job"]["state"] == "completed"
        listed = ctx2.solved_points_list(source="P_restart")
        assert listed["count"] == 2
    finally:
        ctx2.close()


def test_report_export_path_and_summarize(tmp_path: Path, project_file: Path) -> None:
    ctx = _ctx(tmp_path)
    try:
        _load(ctx, project_file)
        created = ctx.report_create("modal_s", name="S11")
        dest = tmp_path / "round-000-s11.csv"
        exported = ctx.report_export(
            created["report"]["report_id"],
            path=str(dest),
            summarize={"target_ghz": 2.4, "threshold_db": -4.0},
        )
        assert Path(exported["path"]).resolve() == dest.resolve()
        assert dest.is_file()
        summary = exported["summary"]
        assert summary["traces"]
        trace = summary["traces"][0]
        assert trace["band_truncated_by_sweep"] is True
        assert trace["touches_sweep_edge"] is True
        png_out = ctx.report_export(
            created["report"]["report_id"],
            png=True,
            summarize={"target_ghz": 2.4},
        )
        assert "png" in png_out or "png_error" in png_out
    finally:
        ctx.close()


def test_view_capture_warns_when_fit_is_hidden(
    tmp_path: Path, project_file: Path
) -> None:
    ctx = _ctx(tmp_path)
    try:
        _load(ctx, project_file)
        ctx.view_hide(["AirBox"])
        cap = ctx.view_capture(fit=["AirBox", "Patch"])
        assert cap["hidden_in_fit"] == ["AirBox"]
        assert "AirBox" in cap["warning"]
    finally:
        ctx.close()


def test_summarize_modal_s_and_terminal_z(tmp_path: Path) -> None:
    s11 = tmp_path / "s11.csv"
    s11.write_text(
        "freq_ghz,s11_db\n70,-8\n76,-12\n77,-14\n80,-11\n90,-6\n",
        encoding="utf-8",
    )
    summary = summarize_modal_s_csv(s11, target_ghz=77.0, threshold_db=-10.0)
    trace = summary["traces"][0]
    assert trace["band_ghz"] == [76.0, 80.0]
    assert trace["band_truncated_by_sweep"] is False
    assert abs(trace["fbw"] - 2.0 * 4.0 / 156.0) < 1e-9

    truncated = tmp_path / "edge.csv"
    truncated.write_text(
        "freq_ghz,s11_db\n70,-12\n77,-14\n80,-11\n",
        encoding="utf-8",
    )
    edge = summarize_modal_s_csv(truncated, target_ghz=77.0, threshold_db=-10.0)
    assert edge["traces"][0]["band_truncated_by_sweep"] is True
    assert edge["traces"][0]["touches_sweep_edge"] is True

    z = tmp_path / "z.csv"
    z.write_text(
        "freq_ghz,re,im\n70,20,10\n77,50,-2\n80,55,4\n",
        encoding="utf-8",
    )
    zsum = summarize_terminal_z_csv(z, target_ghz=77.0)
    assert zsum["at_target"]["re"] == 50.0
    assert zsum["at_sweep_edges"]["low"]["im"] == 10.0
    assert zsum["im_zero_crossings"] == 2
