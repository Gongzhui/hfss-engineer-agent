"""Hidden grader for eval/score_run.py. Does not import hfss_mcp."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load_score():
    path = REPO / "eval" / "score_run.py"
    spec = importlib.util.spec_from_file_location("score_run", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_nominal_has_wide_impedance_bw_and_a_notch() -> None:
    score = _load_score()
    rows = score.load_s11(REPO / "cases" / "uwb_circular_notch" / "results" / "s11.csv")
    m = score.metrics(rows, notch_target_ghz=6.6)
    assert m["impedance_bw_ghz"] > 10.0
    assert m["design_band_frac_le_m10"] > 0.9
    assert m["notch"] is not None
    assert m["notch"]["clear"] is True
    assert m["notch"]["center_ghz"] == 6.6
    assert m["notch"]["width_ghz"] == 0.4


def test_sandbox_start_has_weaker_low_band() -> None:
    score = _load_score()
    rows = score.load_s11(
        REPO / "cases" / "uwb_circular_notch" / "results" / "s11_sandbox.csv"
    )
    m = score.metrics(rows, notch_target_ghz=6.6)
    assert m["design_band_frac_le_m10"] < 0.85
    assert m["impedance_bw_ghz"] < 10.0
    assert m["notch"] is not None
    assert m["notch"]["center_ghz"] != 6.6
    assert m["notch"]["width_ghz"] > 0.5


def test_nominal_passes_exam_spec() -> None:
    score = _load_score()
    tmp = REPO / "eval" / "exams" / "uwb_circular_notch" / "runs" / "_pytest_nom"
    tmp.mkdir(parents=True, exist_ok=True)
    src = REPO / "cases" / "uwb_circular_notch" / "results" / "s11.csv"
    (tmp / "s11.csv").write_bytes(src.read_bytes())
    try:
        payload = score.score_exam("uwb_circular_notch", tmp)
        assert payload["pass"] is True
        end = payload["verdict"]["end"]
        assert end["notch"]["center_ghz"] == 6.6
        assert end["notch"]["width_ghz"] == 0.4
        assert end["envelope"]["relative_bw"] == 1.37
        assert end["notch"]["peak_s11_db"] > -7.0
        assert all(end["checks"].values())
        assert payload["verdict"]["start"]["pass"] is False
        assert payload["verdict"]["nominal_reference"]["pass"] is True
        assert "must not decide pass/fail" in payload["pass_fail_note"]
    finally:
        (tmp / "s11.csv").unlink(missing_ok=True)
        tmp.rmdir()


def test_sandbox_fails_exam_spec() -> None:
    score = _load_score()
    tmp = REPO / "eval" / "exams" / "uwb_circular_notch" / "runs" / "_pytest"
    tmp.mkdir(parents=True, exist_ok=True)
    src = REPO / "cases" / "uwb_circular_notch" / "results" / "s11_sandbox.csv"
    (tmp / "s11.csv").write_bytes(src.read_bytes())
    try:
        payload = score.score_exam("uwb_circular_notch", tmp)
        assert payload["pass"] is False
        checks = payload["verdict"]["end"]["checks"]
        assert checks["notch_center_ok"] is False
        assert checks["notch_width_ok"] is False
        assert checks["occupied_stopped"] is False
        assert checks["rel_bw_ok"] is False
        end_frac = payload["end"]["design_band_frac_le_m10"]
        start_frac = payload["start"]["design_band_frac_le_m10"]
        assert end_frac == start_frac
        assert "must not decide pass/fail" in payload["pass_fail_note"]
        assert payload["protocol"]["on_time"] is False
    finally:
        (tmp / "s11.csv").unlink(missing_ok=True)
        tmp.rmdir()


def test_time_limit_is_protocol_not_rf_pass() -> None:
    score = _load_score()
    tmp = REPO / "eval" / "exams" / "uwb_circular_notch" / "runs" / "_pytest_clock"
    tmp.mkdir(parents=True, exist_ok=True)
    src = REPO / "cases" / "uwb_circular_notch" / "results" / "s11.csv"
    (tmp / "s11.csv").write_bytes(src.read_bytes())
    log = tmp / "hfss-tuning-log.md"
    log.write_text(
        "\n".join(
            [
                "- started: 2026-08-15 21:00 +08:00",
                "- stopped: 2026-08-16 02:00 +08:00",
                "- job_id: job_a",
                "- solve_time: 1h 10m",
                "- job_id: job_b",
                "- solve_time: 50m",
                "",
            ]
        ),
        encoding="utf-8",
    )
    try:
        payload = score.score_exam("uwb_circular_notch", tmp)
        assert payload["pass"] is True
        assert payload["protocol"]["time_budget"] == "solve"
        assert payload["protocol"]["solve_total_s"] == 7200
        assert payload["protocol"]["on_time"] is True
        log.write_text(
            "\n".join(
                [
                    "- started: 2026-08-15 21:00 +08:00",
                    "- stopped: 2026-08-15 22:00 +08:00",
                    "- job_id: job_a",
                    "- solve_time: 2h",
                    "- job_id: job_b",
                    "- solve_time: 1h 5m",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        payload = score.score_exam("uwb_circular_notch", tmp)
        assert payload["pass"] is True
        assert payload["protocol"]["on_time"] is False
    finally:
        (tmp / "s11.csv").unlink(missing_ok=True)
        log.unlink(missing_ok=True)
        tmp.rmdir()


def test_shallow_notch_at_66_fails_peak_floor() -> None:
    score = _load_score()
    tmp = REPO / "eval" / "exams" / "uwb_circular_notch" / "runs" / "_pytest_peak"
    tmp.mkdir(parents=True, exist_ok=True)
    lines = ["freq_ghz,s11_db"]
    for i in range(141):
        freq = round(1.0 + i * 0.1, 1)
        if abs(freq - 6.6) < 1e-9:
            db = -9.96
        elif abs(freq - 6.5) < 1e-9:
            db = -10.21
        elif abs(freq - 6.7) < 1e-9:
            db = -10.85
        elif 2.2 <= freq <= 6.5 or freq >= 6.7:
            db = -12.0
        elif freq <= 1.8:
            db = -12.0
        else:
            db = -8.0
        lines.append(f"{freq},{db}")
    (tmp / "s11.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        payload = score.score_exam("uwb_circular_notch", tmp)
        end = payload["verdict"]["end"]
        assert end["notch"]["center_ghz"] == 6.6
        assert end["notch"]["width_ghz"] == 0.2
        assert end["checks"]["notch_width_ok"] is True
        assert end["checks"]["rel_bw_ok"] is True
        assert end["checks"]["notch_clear_ok"] is False
        assert end["checks"]["occupied_stopped"] is False
        assert payload["pass"] is False
    finally:
        (tmp / "s11.csv").unlink(missing_ok=True)
        tmp.rmdir()


def test_parse_duration_units() -> None:
    score = _load_score()
    assert score.parse_duration("12m30s") == 750
    assert score.parse_duration("1h 2m") == 3720
    assert score.parse_duration("01:12:30") == 4350
    assert score.parse_duration("45s") == 45
    assert score.parse_duration("2小时15分") == 8100
    assert score.parse_duration("6m32s (2026-08-17T13:45:58Z → 13:52:30Z)") == 392
    assert score.parse_duration("") is None
    assert score.parse_duration("not-a-time") is None


def test_me_dipole_nominal_passes_match_spec() -> None:
    score = _load_score()
    tmp = REPO / "eval" / "exams" / "me_dipole_77" / "runs" / "_pytest_nom"
    tmp.mkdir(parents=True, exist_ok=True)
    src = REPO / "cases" / "me_dipole_77" / "results" / "s11.csv"
    (tmp / "s11.csv").write_bytes(src.read_bytes())
    try:
        payload = score.score_exam("me_dipole_77", tmp)
        assert payload["pass"] is True
        end = payload["verdict"]["end"]
        assert end["checks"]["center_matched"] is True
        assert end["checks"]["rel_bw_ok"] is True
        assert end["relative_bw"] >= 0.30
        assert end["s11_at_nearest_db"] <= -10.0
        assert payload["verdict"]["start"]["pass"] is False
        assert payload["verdict"]["nominal_reference"]["pass"] is True
        assert "relative bandwidth" in payload["pass_fail_note"]
    finally:
        (tmp / "s11.csv").unlink(missing_ok=True)
        tmp.rmdir()


def test_me_dipole_sandbox_fails_match_spec() -> None:
    score = _load_score()
    tmp = REPO / "eval" / "exams" / "me_dipole_77" / "runs" / "_pytest"
    tmp.mkdir(parents=True, exist_ok=True)
    src = REPO / "cases" / "me_dipole_77" / "results" / "s11_sandbox.csv"
    (tmp / "s11.csv").write_bytes(src.read_bytes())
    try:
        payload = score.score_exam("me_dipole_77", tmp)
        assert payload["pass"] is False
        checks = payload["verdict"]["end"]["checks"]
        assert checks["center_matched"] is False
        assert checks["rel_bw_ok"] is False
        assert payload["end"]["s11_min_informational"][1] > -10.0
        assert payload["protocol"]["on_time"] is False
    finally:
        (tmp / "s11.csv").unlink(missing_ok=True)
        tmp.rmdir()

