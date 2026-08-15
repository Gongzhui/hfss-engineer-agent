"""ReportSetup CSV is the S11 source of truth, not Touchstone."""

from __future__ import annotations

from pathlib import Path

from hfss_mcp.metrics import normalize_exported_report_csv, parse_hfss_report_table


def test_normalize_modal_s_matches_hfss_report_export(tmp_path: Path) -> None:
    src = tmp_path / "s11_raw.csv"
    src.write_text(
        '"Freq [GHz]","dB(S(1,1)) []"\n'
        "2.4,-18.4971953863042\n"
        "6.6,-5.63270572405106\n",
        encoding="utf-8",
    )
    out = normalize_exported_report_csv(src, "modal_s")
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "freq_ghz,s11_db"
    assert lines[1].startswith("2.4,-18.497")
    assert lines[2].startswith("6.6,-5.632")


def test_normalize_modal_s_family_keeps_all_traces(tmp_path: Path) -> None:
    src = tmp_path / "family_raw.csv"
    src.write_text(
        '"Freq [GHz]","dB(S(1,1)) [] - patch_r=\'8mm\'","dB(S(1,1)) [] - patch_r=\'9mm\'"\n'
        "3.0,-12.0,-8.0\n"
        "6.6,-5.6,-4.1\n",
        encoding="utf-8",
    )
    out = normalize_exported_report_csv(src, "modal_s")
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "freq_ghz,variation,s11_db"
    assert "patch_r='8mm'" in lines[1]
    assert "patch_r='9mm'" in lines[2]
    assert len(lines) == 5


def test_parse_hfss_report_table_skips_header(tmp_path: Path) -> None:
    path = tmp_path / "raw.csv"
    path.write_text(
        '"Freq [GHz]","dB(S(1,1)) []"\n1,-12.4037003277195\n',
        encoding="utf-8",
    )
    headers, rows = parse_hfss_report_table(path)
    assert "dB(S(1,1))" in headers[1]
    assert rows[0][1] < -10
