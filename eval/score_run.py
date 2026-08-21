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


def nearest_s11(rows: list[tuple[float, float]], f0: float) -> tuple[float, float] | None:
    if not rows:
        return None
    return min(rows, key=lambda item: (abs(item[0] - f0), item[0]))


def band_containing(
    bands: list[tuple[float, float]], freq: float
) -> tuple[float, float] | None:
    for lo, hi in bands:
        if lo <= freq <= hi:
            return (lo, hi)
    return None


def grade_match_spec(
    rows: list[tuple[float, float]],
    spec: dict[str, Any],
    *,
    thr: float = THR,
) -> dict[str, Any]:
    """Pass if the -10 dB band that covers center_ghz has relative BW above the floor."""
    target = float(spec["center_ghz"])
    rel_min = float(spec["rel_bw_min"])
    center_max = float(spec.get("s11_at_center_max_db", thr))
    bands = minus10_bands(rows, thr)
    near = nearest_s11(rows, target)
    near_f, near_db = (None, None) if near is None else near
    band = None if near_f is None else band_containing(bands, near_f)
    rel = None
    if band is not None and (band[0] + band[1]) != 0:
        rel = 2.0 * (band[1] - band[0]) / (band[0] + band[1])
    checks = {
        "center_matched": (
            near_db is not None
            and near_db <= center_max
            and band is not None
        ),
        "rel_bw_ok": rel is not None and rel >= rel_min,
    }
    return {
        "center_ghz": target,
        "nearest_ghz": None if near_f is None else round(near_f, 3),
        "s11_at_nearest_db": None if near_db is None else round(near_db, 2),
        "band_ghz": None if band is None else [round(band[0], 3), round(band[1], 3)],
        "relative_bw": None if rel is None else round(rel, 3),
        "checks": checks,
        "pass": all(checks.values()),
    }


def grade_spec(
    rows: list[tuple[float, float]],
    spec: dict[str, Any],
    *,
    lo: float,
    hi: float,
) -> dict[str, Any]:
    if str(spec.get("kind") or "notch") == "match":
        return grade_match_spec(rows, spec)
    target = float(spec["notch_center_ghz"])
    m = metrics(rows, lo=lo, hi=hi, notch_target_ghz=target)
    notch = m["notch"]
    bands = minus10_bands(rows)
    envelope = None
    if notch is not None:
        envelope = envelope_rel_bw(bands, notch["ghz"][0], notch["ghz"][1])
    occ = spec.get("occupied_ghz") or [target, target]
    peak_min = float(spec.get("notch_peak_min_db", THR))
    occupied_ok = occupied_stopped(
        rows, float(occ[0]), float(occ[1]), thr=peak_min
    )
    center = None if notch is None else notch.get("center_ghz")
    width = None if notch is None else notch.get("width_ghz")
    peak = None if notch is None else notch.get("peak_s11_db")
    rel = None if envelope is None else envelope["relative_bw"]
    width_max = float(spec["notch_width_max_ghz"])
    width_min = float(spec.get("notch_width_min_ghz", 0.0))
    checks = {
        "occupied_stopped": occupied_ok,
        "notch_center_ok": (
            center is not None
            and abs(center - target) <= float(spec.get("notch_center_tol_ghz", 0.0))
        ),
        "notch_width_ok": (
            width is not None and width_min <= width <= width_max
        ),
        "notch_clear_ok": peak is not None and peak > peak_min,
        "rel_bw_ok": rel is not None and rel >= float(spec["rel_bw_min"]),
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
            date, clock = bits[0], bits[1]
            tz = bits[2] if len(bits) > 2 else "+08:00"
            if len(clock) == 5:
                clock = f"{clock}:00"
            s = f"{date}T{clock}{tz}"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BEIJING)
    return dt


def _log_field(text: str, name: str) -> str | None:
    match = re.search(rf"^-\s*{re.escape(name)}:\s*(.*)$", text, re.M | re.I)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def parse_duration(raw: str) -> float | None:
    """Parse a logged solve duration into seconds. None if blank or unreadable."""
    s = " ".join((raw or "").split("#", 1)[0].split())
    s = s.split("(", 1)[0].strip()
    if not s:
        return None
    s = re.sub(r"hours?", "h", s, flags=re.I)
    s = re.sub(r"minutes?", "m", s, flags=re.I)
    s = re.sub(r"seconds?", "s", s, flags=re.I)
    s = (
        s.replace("小时", "h")
        .replace("分钟", "m")
        .replace("秒钟", "s")
        .replace("时", "h")
        .replace("分", "m")
        .replace("秒", "s")
    )
    s = re.sub(r"\s+", "", s)
    hms = re.fullmatch(r"(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", s)
    if hms:
        return int(hms.group(1)) * 3600 + int(hms.group(2)) * 60 + float(hms.group(3))
    ms = re.fullmatch(r"(\d+):(\d{2}(?:\.\d+)?)", s)
    if ms:
        return int(ms.group(1)) * 60 + float(ms.group(2))
    parts = re.fullmatch(
        r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?",
        s,
        flags=re.I,
    )
    if parts and any(parts.group(i) for i in (1, 2, 3)):
        hours = float(parts.group(1) or 0)
        minutes = float(parts.group(2) or 0)
        secs = float(parts.group(3) or 0)
        return hours * 3600 + minutes * 60 + secs
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return float(s)
    return None


def collect_solve_seconds(text: str) -> list[float | None]:
    found: list[float | None] = []
    for match in re.finditer(r"^-\s*solve_time:\s*(.*)$", text, re.M | re.I):
        found.append(parse_duration(match.group(1)))
    return found


def count_logged_jobs(text: str) -> int:
    n = 0
    for match in re.finditer(r"^-\s*job_id:\s*(\S+)", text, re.M | re.I):
        value = match.group(1).strip().strip("`")
        if value and value not in {"-", "none", "null"}:
            n += 1
    return n


def grade_time_limit(run_dir: Path, hours: float) -> dict[str, Any]:
    log_path = run_dir / "hfss-tuning-log.md"
    text = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    started = parse_when(_log_field(text, "started") or "")
    stopped = parse_when(_log_field(text, "stopped") or "") or parse_when(
        _log_field(text, "submitted") or ""
    )
    deadline = None if started is None else started + timedelta(hours=hours)
    on_time = (
        started is not None
        and stopped is not None
        and deadline is not None
        and stopped <= deadline
    )
    return {
        "time_limit_hours": hours,
        "started": None if started is None else started.isoformat(),
        "stopped": None if stopped is None else stopped.isoformat(),
        "deadline": None if deadline is None else deadline.isoformat(),
        "on_time": on_time,
        "time_budget": "wall",
    }


def grade_solve_limit(run_dir: Path, hours: float) -> dict[str, Any]:
    log_path = run_dir / "hfss-tuning-log.md"
    text = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    started = parse_when(_log_field(text, "started") or "")
    stopped = parse_when(_log_field(text, "stopped") or "") or parse_when(
        _log_field(text, "submitted") or ""
    )
    samples = collect_solve_seconds(text)
    jobs = count_logged_jobs(text)
    parsed = [x for x in samples if x is not None]
    total = sum(parsed)
    limit_s = float(hours) * 3600.0
    on_time = (
        bool(samples)
        and len(parsed) == len(samples)
        and len(parsed) >= jobs
        and total <= limit_s + 1e-6
    )
    return {
        "time_limit_hours": hours,
        "time_budget": "solve",
        "started": None if started is None else started.isoformat(),
        "stopped": None if stopped is None else stopped.isoformat(),
        "solve_seconds": [None if x is None else round(x, 3) for x in samples],
        "solve_total_s": round(total, 3),
        "job_ids": jobs,
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
    kind = "notch" if spec is None else str(spec.get("kind") or "notch")
    if spec is None:
        target = 6.0
    elif kind == "match":
        target = float(spec["center_ghz"])
    else:
        target = float(spec["notch_center_ghz"])
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
        if kind == "match":
            payload["pass_fail_note"] = (
                "Pass if a continuous S11<=-10 dB band covers the stated "
                "center (nearest sweep point) and that band's relative "
                "bandwidth 2(fH-fL)/(fH+fL) meets rel_bw_min. s11_min is "
                "informational and must not decide pass/fail. Nominal is the "
                "known-good reference, not a number to copy. The time budget "
                "is protocol.on_time and does not decide pass."
            )
        else:
            payload["pass_fail_note"] = (
                "Pass if the stopband is at the stated center, the peak (and the "
                "occupied point) is above notch_peak_min_db, the gap is no wider "
                "than the max width, and the envelope relative bandwidth meets "
                "the floor. Passband edges stay at -10 dB. s11_min is "
                "informational and must not decide pass/fail. Nominal is the "
                "known-good reference, not a number to copy. The time budget is "
                "protocol.on_time and does not decide pass."
            )
    limit = key.get("time_limit_hours")
    if limit is not None:
        budget = str(key.get("time_budget") or "wall")
        if budget == "solve":
            payload["protocol"] = grade_solve_limit(run_dir, float(limit))
        else:
            payload["protocol"] = grade_time_limit(run_dir, float(limit))
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
