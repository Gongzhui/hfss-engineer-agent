"""Score an exam run from outside the exam workspace. Not an MCP tool."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DESIGN_LO = 3.07
DESIGN_HI = 12.67
THR = -10.0


def load_s11(path: Path) -> list[tuple[float, float]]:
    rows: list[tuple[float, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        if not line.strip():
            continue
        freq_s, db_s = line.split(",")[:2]
        rows.append((float(freq_s), float(db_s)))
    rows.sort()
    return rows


def minus10_bands(rows: list[tuple[float, float]], thr: float = THR) -> list[tuple[float, float]]:
    bands: list[tuple[float, float]] = []
    start: float | None = None
    prev = 0.0
    for freq, db in rows:
        below = db <= thr
        if below and start is None:
            start = freq
        if (not below) and start is not None:
            bands.append((start, prev))
            start = None
        prev = freq
    if start is not None and rows:
        bands.append((start, rows[-1][0]))
    return bands


def _gaps(
    bands: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    interior = [(a, b) for a, b in bands if b >= 2.0 and a <= 14.0]
    out: list[tuple[float, float]] = []
    for (_a0, b0), (a1, _b1) in zip(interior, interior[1:], strict=False):
        gap_lo, gap_hi = b0, a1
        if gap_hi - gap_lo >= 0.2:
            out.append((gap_lo, gap_hi))
    return out


def _gap_peak(
    rows: list[tuple[float, float]],
    gap_lo: float,
    gap_hi: float,
) -> tuple[float | None, float | None]:
    window = [(f, s) for f, s in rows if gap_lo <= f <= gap_hi]
    if not window:
        return None, None
    freq, peak = max(window, key=lambda item: item[1])
    return freq, peak


def _notch(
    bands: list[tuple[float, float]],
    rows: list[tuple[float, float]],
    *,
    target_ghz: float = 6.0,
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_dist = 1e9
    for gap_lo, gap_hi in _gaps(bands):
        peak_f, peak = _gap_peak(rows, gap_lo, gap_hi)
        mid = 0.5 * (gap_lo + gap_hi)
        dist = abs((peak_f if peak_f is not None else mid) - target_ghz)
        cand = {
            "ghz": [round(gap_lo, 3), round(gap_hi, 3)],
            "width_ghz": round(gap_hi - gap_lo, 3),
            "center_ghz": None if peak_f is None else round(peak_f, 3),
            "peak_s11_db": None if peak is None else round(peak, 2),
            "clear": peak is not None and peak > THR,
        }
        if dist < best_dist:
            best_dist = dist
            best = cand
    return best


def metrics(
    rows: list[tuple[float, float]],
    *,
    lo: float = DESIGN_LO,
    hi: float = DESIGN_HI,
    notch_target_ghz: float = 6.0,
) -> dict[str, Any]:
    bands = minus10_bands(rows)
    total = sum(b - a for a, b in bands)
    inband = [(f, s) for f, s in rows if lo <= f <= hi]
    frac = (sum(1 for _, s in inband if s <= THR) / len(inband)) if inband else 0.0
    best = min(rows, key=lambda item: item[1]) if rows else (None, None)
    first = bands[0][0] if bands else None
    last = bands[-1][1] if bands else None
    rel = None
    if first is not None and last is not None and (first + last) != 0:
        rel = (last - first) / ((last + first) / 2.0)
    notch = _notch(bands, rows, target_ghz=notch_target_ghz)
    return {
        "bands_ghz": [[round(a, 3), round(b, 3)] for a, b in bands],
        "impedance_bw_ghz": round(total, 3),
        "design_band_frac_le_m10": round(frac, 3),
        "span_ghz": None if first is None else round(last - first, 3),
        "relative_bw": None if rel is None else round(rel, 3),
        "notch": notch,
        "s11_min_informational": (
            None if best[0] is None else [round(best[0], 3), round(best[1], 3)]
        ),
    }


def resolve_s11(run_dir: Path) -> Path:
    final = run_dir / "s11.csv"
    if final.is_file():
        return final
    rounds = sorted(run_dir.glob("round-*-s11.csv"))
    if not rounds:
        raise FileNotFoundError(f"no s11.csv or round-*-s11.csv in {run_dir}")
    return rounds[-1]


def score_exam(exam_id: str, run_dir: Path) -> dict[str, Any]:
    key_path = REPO / "eval" / "keys" / f"{exam_id}.json"
    key = json.loads(key_path.read_text(encoding="utf-8"))
    lo, hi = key.get("design_band_ghz") or [DESIGN_LO, DESIGN_HI]
    end_rows = load_s11(resolve_s11(run_dir))
    start_path = run_dir / "round-000-s11.csv"
    if not start_path.is_file():
        start_path = REPO / key["start_s11"]
    start_rows = load_s11(start_path)
    nom_rows = load_s11(REPO / key["nominal_s11"])
    return {
        "exam_id": exam_id,
        "run": str(run_dir),
        "start": metrics(start_rows, lo=lo, hi=hi),
        "end": metrics(end_rows, lo=lo, hi=hi),
        "nominal_reference": metrics(nom_rows, lo=lo, hi=hi),
        "pass_fail_note": (
            "Impedance bandwidth is S11<=-10 dB coverage. "
            "s11_min is informational and must not decide pass/fail."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Score an hfss-mcp exam run (hidden keys).")
    parser.add_argument("--exam", required=True)
    parser.add_argument("--run", required=True, help="Path to eval/exams/<id>/runs/<run-id>")
    args = parser.parse_args()
    run_dir = Path(args.run)
    if not run_dir.is_absolute():
        run_dir = (Path.cwd() / run_dir).resolve()
    payload = score_exam(args.exam, run_dir)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
