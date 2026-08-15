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
