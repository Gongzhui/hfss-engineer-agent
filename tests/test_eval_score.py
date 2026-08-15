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
    m = score.metrics(rows)
    assert m["impedance_bw_ghz"] > 10.0
    assert m["design_band_frac_le_m10"] > 0.9
    assert m["notch"] is not None
    assert m["notch"]["clear"] is True


def test_sandbox_start_has_weaker_low_band() -> None:
    score = _load_score()
    rows = score.load_s11(
        REPO / "cases" / "uwb_circular_notch" / "results" / "s11_sandbox.csv"
    )
    m = score.metrics(rows)
    assert m["design_band_frac_le_m10"] < 0.85
    assert m["impedance_bw_ghz"] < 10.0


def test_score_exam_uses_keys_not_s11_min_as_verdict() -> None:
    score = _load_score()
    tmp = REPO / "eval" / "exams" / "uwb_circular_notch" / "runs" / "_pytest"
    tmp.mkdir(parents=True, exist_ok=True)
    src = REPO / "cases" / "uwb_circular_notch" / "results" / "s11_sandbox.csv"
    (tmp / "s11.csv").write_bytes(src.read_bytes())
    try:
        payload = score.score_exam("uwb_circular_notch", tmp)
        assert "must not decide pass/fail" in payload["pass_fail_note"]
        end_frac = payload["end"]["design_band_frac_le_m10"]
        start_frac = payload["start"]["design_band_frac_le_m10"]
        assert end_frac == start_frac
        assert "pass" not in payload
    finally:
        (tmp / "s11.csv").unlink(missing_ok=True)
        tmp.rmdir()


def _wlan58_tmp(rows: str) -> Path:
    tmp = REPO / "eval" / "exams" / "uwb_circular_notch_wlan58" / "runs" / "_pytest"
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "s11.csv").write_text(rows, encoding="utf-8")
    return tmp


def test_wlan58_start_and_nominal_fail_occupied_band() -> None:
    score = _load_score()
    tmp = REPO / "eval" / "exams" / "uwb_circular_notch_wlan58" / "runs" / "_pytest"
    tmp.mkdir(parents=True, exist_ok=True)
    src = REPO / "cases" / "uwb_circular_notch" / "results" / "s11_sandbox.csv"
    (tmp / "s11.csv").write_bytes(src.read_bytes())
    try:
        payload = score.score_exam("uwb_circular_notch_wlan58", tmp)
        assert payload["pass"] is False
        assert payload["verdict"]["start"]["pass"] is False
        assert payload["verdict"]["nominal_reference"]["pass"] is False
    finally:
        (tmp / "s11.csv").unlink(missing_ok=True)
        tmp.rmdir()


def test_wlan58_previous_9ghz_notch_fails() -> None:
    score = _load_score()
    src = (
        REPO
        / "eval"
        / "exams"
        / "uwb_circular_notch"
        / "runs"
        / "20260813-203216"
        / "s11.csv"
    )
    if not src.is_file():
        return
    tmp = _wlan58_tmp(src.read_text(encoding="utf-8"))
    try:
        payload = score.score_exam("uwb_circular_notch_wlan58", tmp)
        assert payload["pass"] is False
        assert payload["verdict"]["end"]["checks"]["occupied_stopped"] is False
    finally:
        (tmp / "s11.csv").unlink(missing_ok=True)
        tmp.rmdir()


def test_wlan58_synthetic_5p8_notch_passes() -> None:
    score = _load_score()
    lines = ["freq_ghz,s11_db"]
    for i in range(141):
        f = round(1.0 + 0.1 * i, 1)
        if 5.6 <= f <= 5.9:
            db = -4.0 if f != 5.8 else -2.5
        elif 3.0 <= f <= 13.0:
            db = -12.0
        else:
            db = -8.0
        lines.append(f"{f},{db}")
    tmp = _wlan58_tmp("\n".join(lines) + "\n")
    try:
        payload = score.score_exam("uwb_circular_notch_wlan58", tmp)
        assert payload["pass"] is True
        end = payload["verdict"]["end"]
        assert end["notch"]["center_ghz"] == 5.8
        assert 0.3 <= end["notch"]["width_ghz"] <= 0.8
        assert end["envelope"]["relative_bw"] >= 1.10
    finally:
        (tmp / "s11.csv").unlink(missing_ok=True)
        tmp.rmdir()


def test_wlan58_deadline_is_protocol_not_rf_pass() -> None:
    score = _load_score()
    tmp = _wlan58_tmp("freq_ghz,s11_db\n1,-12\n")
    log = tmp / "hfss-tuning-log.md"
    log.write_text(
        "- started: 2026-08-13 22:40 +08:00\n- stopped: 2026-08-13 23:50 +08:00\n",
        encoding="utf-8",
    )
    try:
        payload = score.score_exam("uwb_circular_notch_wlan58", tmp)
        assert payload["protocol"]["on_time"] is True
        log.write_text(
            "- started: 2026-08-13 22:40 +08:00\n- stopped: 2026-08-14 00:12 +08:00\n",
            encoding="utf-8",
        )
        payload = score.score_exam("uwb_circular_notch_wlan58", tmp)
        assert payload["protocol"]["on_time"] is False
    finally:
        (tmp / "s11.csv").unlink(missing_ok=True)
        log.unlink(missing_ok=True)
        tmp.rmdir()
