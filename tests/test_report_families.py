"""Family selections must survive creation, inspection and Z export."""

from pathlib import Path

import pytest

from hfss_mcp.app import AppContext, build_allowlist_for_tests
from hfss_mcp.errors import AdapterError, PolicyError
from hfss_mcp.live import LiveDesign
from hfss_mcp.metrics import csv_export_summary, normalize_exported_report_csv
from hfss_mcp.report_families import family_values


@pytest.mark.parametrize(
    "values", [[], ["All", 1.0], ["Nominal", "All"], ["nan"], [float("inf")], [True], ["1mm;bad"]]
)
def test_invalid_choices(values: list) -> None:
    with pytest.raises(PolicyError):
        family_values({"x": values}, {"x": "mm"})


def test_numeric_units_and_legacy() -> None:
    assert family_values({"x": [1, "1mm", "2 mm"]}, {"x": "mm"}) == {"x": ["1mm", "2mm"]}
    assert family_values(["x"], {"x": "mm"}) == {"x": ["All"]}
    with pytest.raises(PolicyError):
        family_values({"bad": [1]}, {"x": "mm"})


def test_multi_value_family_z_end_to_end(tmp_path: Path, project_file: Path) -> None:
    ctx = AppContext(data_dir=tmp_path / "data", use_fake=True)
    try:
        ctx.allowlist_load(
            allowlist=build_allowlist_for_tests(project_file).model_dump(mode="json", by_alias=True)
        )
        ctx.report_create(
            category="Z Parameter",
            quantity="Z(1,1)",
            function=["re", "im"],
            name="MultiZ",
            families={"patch_w": [10, 11], "patch_l": [12, 13]},
        )
        inspected = ctx.report_get("MultiZ")["report"]
        assert inspected["families"]["patch_w"] == ["10mm", "11mm"]
        changed = ctx.variables_set([{"name": "patch_w", "value": 10.5, "unit": "mm"}])
        assert changed["needs_solve"] is None
        out = ctx.report_export("MultiZ")
        assert out["header"] == ["freq_ghz", "variation", "re", "im"]
        assert out["traces"] == 4  # Cartesian, never zip the two axes.
        assert out["solution_validity"] == "unknown"
        assert "stale_solution" not in out
        data = Path(out["path"]).read_bytes()
        normalize_exported_report_csv(Path(out["path"]), "curve")
        assert Path(out["path"]).read_bytes() == data
    finally:
        ctx.close()


def test_query_failure_does_not_export_cached_data(monkeypatch: pytest.MonkeyPatch) -> None:
    live = object.__new__(LiveDesign)
    monkeypatch.setattr(
        live,
        "_script",
        lambda _: {
            "solution_status": {
                "data_availability": "query_failed",
                "validity": "unknown",
                "query_error": "no data",
            }
        },
    )
    with pytest.raises(AdapterError) as error:
        live.prepare_report_export("OldCachedReport")
    assert error.value.code == "report_solution_query_failed"


def test_available_is_not_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    live = object.__new__(LiveDesign)
    monkeypatch.setattr(
        live,
        "_script",
        lambda _: {
            "solution_status": {
                "data_availability": "available",
                "validity": "unknown",
                "report_refreshed": True,
            }
        },
    )
    assert live.prepare_report_export("R")["validity"] == "unknown"


def test_running_solve_export_is_only_a_cache_peek(tmp_path: Path, project_file: Path) -> None:
    ctx = AppContext(data_dir=tmp_path / "data", use_fake=True)
    try:
        ctx.allowlist_load(
            allowlist=build_allowlist_for_tests(project_file).model_dump(mode="json", by_alias=True)
        )
        ctx.report_create(category="S Parameter", quantity="S(1,1)", function="dB", name="R")
        ctx._jobs["busy"] = {"job_id": "busy", "state": "running"}
        out = ctx.report_export("R")
        assert out["solution_status"]["data_availability"] == "not_checked"
        assert "without refresh" in out["solution_status"]["reason"]
        assert out["solution_validity"] == "unknown"
    finally:
        ctx.close()


def test_wide_z_family_never_discards_pairs(tmp_path: Path) -> None:
    path = tmp_path / "wide.csv"
    text = (
        '"Freq [GHz]","re(Z(1,1)) [] - w=1mm","im(Z(1,1)) [] - w=1mm",'
        '"re(Z(1,1)) [] - w=2mm","im(Z(1,1)) [] - w=2mm"\n1,40,10,50,20\n'
    )
    path.write_text(text, encoding="utf-8")
    normalize_exported_report_csv(path, "curve", expressions=["re(Z(1,1))", "im(Z(1,1))"])
    assert path.read_text(encoding="utf-8") == text
    assert csv_export_summary(path)["format"] == "raw"
