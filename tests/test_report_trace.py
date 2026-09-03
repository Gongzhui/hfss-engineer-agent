"""Category / Quantity / Function helpers and export shapes."""

from __future__ import annotations

from pathlib import Path

from hfss_mcp.metrics import normalize_exported_report_csv
from hfss_mcp.report_trace import (
    compose_y_expressions,
    parse_name_list,
    split_expression,
)


def test_parse_name_list_keeps_s_commas() -> None:
    assert parse_name_list("S(1,1);S(2,2)") == ["S(1,1)", "S(2,2)"]
    assert parse_name_list("S(1,1),S(2,1)") == ["S(1,1)", "S(2,1)"]
    assert parse_name_list(["cang_deg", "dB"]) == ["cang_deg", "dB"]


def test_compose_y_cartesian() -> None:
    assert compose_y_expressions(["S(1,1)", "S(2,2)"], ["cang_deg"]) == [
        "cang_deg(S(1,1))",
        "cang_deg(S(2,2))",
    ]
    assert compose_y_expressions(["Z(1,1)"], ["re", "im"]) == [
        "re(Z(1,1))",
        "im(Z(1,1))",
    ]
    assert compose_y_expressions(["S(1,1)"], ["<none>"]) == ["S(1,1)"]


def test_normalize_phase_not_forced_to_s11_db(tmp_path: Path) -> None:
    src = tmp_path / "phase_raw.csv"
    src.write_text(
        '"Freq [GHz]","cang_deg(S(1,1)) []"\n'
        "2.4,-120.5\n"
        "6.6,-90.1\n",
        encoding="utf-8",
    )
    out = normalize_exported_report_csv(
        src, "curve", expressions=["cang_deg(S(1,1))"]
    )
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "freq_ghz,value"
    assert "s11_db" not in lines[0]
    assert lines[1].startswith("2.4,-120.5")


def test_split_expression() -> None:
    assert split_expression("dB(S(1,1))") == ("dB", "S(1,1)")
    assert split_expression("cang_deg_val(S(1,1)) []") == ("cang_deg_val", "S(1,1)")
    assert split_expression("S(1,1)") == (None, "S(1,1)")


def test_normalize_db_plus_phase_not_fake_family(tmp_path: Path) -> None:
    """User plot with dB + phase must not treat phase as a swept variable."""
    src = tmp_path / "user_plot.csv"
    src.write_text(
        '"Freq [GHz]","dB(S(1,1)) []","cang_deg_val(S(1,1)) []"\n'
        "60,-6.2,-106.97\n"
        "60.4,-6.25,-109.68\n"
        "60.8,-6.29,-112.39\n",
        encoding="utf-8",
    )
    out = normalize_exported_report_csv(src, None)
    text = out.read_text(encoding="utf-8")
    header = text.splitlines()[0]
    assert "s11_db" not in header
    assert "variation" not in header
    assert "dB(S(1,1))" in header
    assert "cang_deg_val(S(1,1))" in header
    assert text.count("\n") == 4  # header + 3 rows, not exploded family


def test_normalize_multi_y_wide(tmp_path: Path) -> None:
    src = tmp_path / "multi.csv"
    src.write_text(
        '"Freq [GHz]","cang_deg(S(1,1)) []","cang_deg(S(2,2)) []"\n'
        "2.4,-120.0,-30.0\n"
        "6.6,-90.0,0.0\n",
        encoding="utf-8",
    )
    out = normalize_exported_report_csv(
        src,
        "curve",
        expressions=["cang_deg(S(1,1))", "cang_deg(S(2,2))"],
    )
    header = out.read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("freq_ghz,")
    assert "cang_deg(S(1,1))" in header
    assert "cang_deg(S(2,2))" in header
    assert "s11_db" not in header
