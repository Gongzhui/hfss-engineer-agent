"""Score an exam run from outside the exam workspace. Not an MCP tool."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DESIGN_LO = 3.07
DESIGN_HI = 12.67
THR = -10.0
BEIJING = timezone(timedelta(hours=8))


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


def envelope_rel_bw(
    bands: list[tuple[float, float]],
    gap_lo: float,
    gap_hi: float,
) -> dict[str, Any] | None:
    f_low = next((a for a, b in bands if abs(b - gap_lo) < 1e-9), None)
    f_high = next((b for a, b in bands if abs(a - gap_hi) < 1e-9), None)
    if f_low is None or f_high is None or (f_low + f_high) == 0:
        return None
    rel = 2.0 * (f_high - f_low) / (f_high + f_low)
    return {
        "f_low_ghz": round(f_low, 3),
        "f_high_ghz": round(f_high, 3),
        "relative_bw": round(rel, 3),
    }


def occupied_stopped(
    rows: list[tuple[float, float]],
    lo: float,
    hi: float,
    *,
    thr: float = THR,
) -> bool:
    pts = [(f, s) for f, s in rows if lo <= f <= hi]
    return bool(pts) and all(s > thr for _, s in pts)


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


def grade_spec(
    rows: list[tuple[float, float]],
    spec: dict[str, Any],
    *,
    lo: float,
    hi: float,
) -> dict[str, Any]:
    target = float(spec["notch_center_ghz"])
    m = metrics(rows, lo=lo, hi=hi, notch_target_ghz=target)
    notch = m["notch"]
    bands = minus10_bands(rows)
    envelope = None
    if notch is not None:
        envelope = envelope_rel_bw(bands, notch["ghz"][0], notch["ghz"][1])
    occ = spec.get("occupied_ghz") or [target, target]
    occupied_ok = occupied_stopped(rows, float(occ[0]), float(occ[1]))
    center = None if notch is None else notch.get("center_ghz")
    width = None if notch is None else notch.get("width_ghz")
    peak = None if notch is None else notch.get("peak_s11_db")
    f_low = None if envelope is None else envelope["f_low_ghz"]
    f_high = None if envelope is None else envelope["f_high_ghz"]
    rel = None if envelope is None else envelope["relative_bw"]
    checks = {
        "occupied_stopped": occupied_ok,
        "notch_center_ok": (
            center is not None and abs(center - target) <= float(spec["notch_center_tol_ghz"])
        ),
        "notch_width_ok": (
            width is not None
            and float(spec["notch_width_min_ghz"]) <= width <= float(spec["notch_width_max_ghz"])
        ),
        "notch_clear_ok": peak is not None and peak > float(spec.get("notch_peak_min_db", THR)),
        "rel_bw_ok": rel is not None and rel >= float(spec["rel_bw_min"]),
        "f_low_ok": f_low is not None and f_low <= float(spec["f_low_max_ghz"]),
        "f_high_ok": f_high is not None and f_high >= float(spec["f_high_min_ghz"]),
    }
    return {
        "notch": notch,
        "envelope": envelope,
        "occupied_ghz": [float(occ[0]), float(occ[1])],
        "checks": checks,
        "pass": all(checks.values()),
    }


def parse_when(raw: str) -> datetime | None:
    s = " ".join(raw.strip().split())
    if not s:
        return None
    s = s.replace("北京时间", "").strip()
    if re.match(r"\d{4}-\d{2}-\d{2} ", s) and "T" not in s:
        bits = s.split()
        if len(bits) >= 2:
            date, time = bits[0], bits[1]
            tz = bits[2] if len(bits) > 2 else "+08:00"
            if len(time) == 5:
                time = f"{time}:00"
            s = f"{date}T{time}{tz}"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BEIJING)
    return dt


def grade_deadline(run_dir: Path, deadline_iso: str) -> dict[str, Any]:
    deadline = parse_when(deadline_iso)
    log_path = run_dir / "hfss-tuning-log.md"
    started = None
    stopped = None
    clocks: list[datetime] = []
    if log_path.is_file():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            m = re.match(
                r"-\s*(started|stopped|clock|deadline)\s*:\s*(.*)$",
                line.strip(),
                re.I,
            )
            if not m:
                continue
            key, rest = m.group(1).lower(), m.group(2).strip()
            when = parse_when(rest)
            if when is None:
                continue
            if key == "started":
                started = when
            elif key == "stopped":
                stopped = when
            elif key == "clock":
                clocks.append(when)
    last = stopped or (clocks[-1] if clocks else None)
    if last is None:
        stamp = run_dir / "s11.csv"
        if not stamp.is_file():
            rounds = sorted(run_dir.glob("round-*-s11.csv"))
            stamp = rounds[-1] if rounds else log_path
        if stamp.is_file():
            last = datetime.fromtimestamp(stamp.stat().st_mtime, tz=BEIJING)
    on_time = None if deadline is None or last is None else last <= deadline
    return {
        "deadline": deadline_iso,
        "started": None if started is None else started.isoformat(),
        "stopped": None if stopped is None else stopped.isoformat(),
        "last_clock": None if last is None else last.isoformat(),
        "on_time": on_time,
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
    spec = key.get("spec")
    target = 6.0 if spec is None else float(spec["notch_center_ghz"])
    end_rows = load_s11(resolve_s11(run_dir))
    start_path = run_dir / "round-000-s11.csv"
    if not start_path.is_file():
        start_path = REPO / key["start_s11"]
    start_rows = load_s11(start_path)
    nom_rows = load_s11(REPO / key["nominal_s11"])
    payload: dict[str, Any] = {
        "exam_id": exam_id,
        "run": str(run_dir),
        "start": metrics(start_rows, lo=lo, hi=hi, notch_target_ghz=target),
        "end": metrics(end_rows, lo=lo, hi=hi, notch_target_ghz=target),
        "nominal_reference": metrics(nom_rows, lo=lo, hi=hi, notch_target_ghz=target),
        "pass_fail_note": (
            "Impedance bandwidth is S11<=-10 dB coverage. "
            "s11_min is informational and must not decide pass/fail."
        ),
    }
    if spec is not None:
        payload["spec"] = spec
        payload["verdict"] = {
            "start": grade_spec(start_rows, spec, lo=lo, hi=hi),
            "end": grade_spec(end_rows, spec, lo=lo, hi=hi),
            "nominal_reference": grade_spec(nom_rows, spec, lo=lo, hi=hi),
        }
        payload["pass"] = payload["verdict"]["end"]["pass"]
        payload["pass_fail_note"] = (
            "Pass if the occupied band is inside a clear stopband at the "
            "stated center, width, and envelope relative bandwidth. "
            "s11_min is informational and must not decide pass/fail. "
            "Nominal is a reference curve, not the pass key. "
            "Wall-clock overtime is protocol.on_time, not RF pass."
        )
    deadline = key.get("deadline")
    if deadline:
        payload["protocol"] = grade_deadline(run_dir, str(deadline))
    return payload


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
