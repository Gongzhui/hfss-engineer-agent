"""ReportSetup CSV is the S11 source of truth, not Touchstone."""

from __future__ import annotations

from pathlib import Path

from hfss_mcp.metrics import (
    csv_export_summary,
    normalize_exported_report_csv,
    parse_hfss_report_table,
)


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


def test_normalize_export_data_variable_columns(tmp_path: Path) -> None:
    src = tmp_path / "R005_feed_gnd_S11.csv"
    src.write_text(
        '"g1 [mm]","l2 [mm]","lw [mm]","Freq [GHz]","dB(S(1,1)) []"\n'
        "8.5,1,1.75,1,-12.8131387606848\n"
        "8.5,1,1.75,1.1,-12.7615673971776\n"
        "8.5,1,3.5,1,-11.7571706049415\n"
        "8.5,1,3.5,1.1,-11.7\n",
        encoding="utf-8",
    )
    out = normalize_exported_report_csv(src, "modal_s")
    text = out.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "freq_ghz,variation,s11_db"
    assert "g1='8.5mm' l2='1mm' lw='1.75mm'" in text
    assert "g1='8.5mm' l2='1mm' lw='3.5mm'" in text
    assert "trace_000" not in text
    summary = csv_export_summary(out)
    assert summary["format"] == "family"
    assert summary["traces"] == 2
    assert summary["labeled"] is True


def test_normalize_export_data_single_combo_stays_single(tmp_path: Path) -> None:
    src = tmp_path / "pinned.csv"
    src.write_text(
        '"lw [mm]","Freq [GHz]","dB(S(1,1)) []"\n'
        "5.25,2.4,-18.5\n"
        "5.25,6.6,-5.6\n",
        encoding="utf-8",
    )
    out = normalize_exported_report_csv(src, "modal_s")
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "freq_ghz,s11_db"
    assert "variation" not in lines[0]


def test_normalize_stacked_unlabeled_s11_splits_wraparounds(tmp_path: Path) -> None:
    src = tmp_path / "stacked.csv"
    src.write_text(
        '"Freq [GHz]","dB(S(1,1)) []"\n'
        "1.0,-10.0\n"
        "2.0,-11.0\n"
        "3.0,-12.0\n"
        "1.0,-8.0\n"
        "2.0,-9.0\n"
        "3.0,-7.0\n",
        encoding="utf-8",
    )
    out = normalize_exported_report_csv(src, "modal_s")
    text = out.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "freq_ghz,variation,s11_db"
    assert "trace_000" in text
    assert "trace_001" in text
    assert len(lines) == 7
    summary = csv_export_summary(out)
    assert summary["format"] == "family"
    assert summary["traces"] == 2
def test_normalize_stacked_s11_uses_plot_legend_names(tmp_path: Path) -> None:
    src = tmp_path / "stacked.csv"
    src.write_text(
        '"Freq [GHz]","dB(S(1,1)) []"\n'
        "1.0,-10.0\n"
        "2.0,-11.0\n"
        "3.0,-12.0\n"
        "1.0,-8.0\n"
        "2.0,-9.0\n"
        "3.0,-7.0\n",
        encoding="utf-8",
    )
    out = normalize_exported_report_csv(
        src,
        "modal_s",
        trace_names=[
            "dB(S(1,1)) [] - slot_length='14mm' sw='0.5mm'",
            "dB(S(1,1)) [] - slot_length='22mm' sw='0.5mm'",
        ],
    )
    text = out.read_text(encoding="utf-8")
    assert "slot_length='14mm' sw='0.5mm'" in text
    assert "slot_length='22mm' sw='0.5mm'" in text
    assert "trace_000" not in text
    summary = csv_export_summary(out)
    assert summary["labeled"] is True
    assert summary["traces"] == 2


def test_relabel_placeholder_variations_from_legend(tmp_path: Path) -> None:
    src = tmp_path / "placeholders.csv"
    src.write_text(
        "freq_ghz,variation,s11_db\n"
        "1.0,trace_000,-10.0\n"
        "2.0,trace_000,-11.0\n"
        "1.0,trace_001,-8.0\n",
        encoding="utf-8",
    )
    out = normalize_exported_report_csv(
        src,
        "modal_s",
        trace_names=[
            "dB(S(1,1)) : patch_r='12mm' slot_length='22mm'",
            "dB(S(1,1)) : patch_r='12mm' slot_length='24mm'",
        ],
    )
    text = out.read_text(encoding="utf-8")
    assert "patch_r='12mm' slot_length='22mm'" in text
    assert "trace_000" not in text


def test_csv_export_summary_single_trace(tmp_path: Path) -> None:
    src = tmp_path / "s11.csv"
    src.write_text("freq_ghz,s11_db\n2.4,-18.5\n", encoding="utf-8")
    summary = csv_export_summary(src)
    assert summary["format"] == "single"
    assert summary["traces"] == 1
    assert summary["labeled"] is True


def test_parse_hfss_report_table_skips_header(tmp_path: Path) -> None:
    path = tmp_path / "raw.csv"
    path.write_text(
        '"Freq [GHz]","dB(S(1,1)) []"\n1,-12.4037003277195\n',
        encoding="utf-8",
    )
    headers, rows = parse_hfss_report_table(path)
    assert "dB(S(1,1))" in headers[1]
    assert rows[0][1] < -10
