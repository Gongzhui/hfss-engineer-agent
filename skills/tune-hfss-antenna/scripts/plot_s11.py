#!/usr/bin/env python3
"""Plot S11 from a Results CSV (or leftover Touchstone) into SVG. stdlib only."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


def _freq_to_ghz(value: float, unit: str | None) -> float:
    u = (unit or "GHz").strip().lower()
    if u in {"ghz", "g"}:
        return float(value)
    if u in {"mhz", "m"}:
        return float(value) / 1e3
    if u in {"khz", "k"}:
        return float(value) / 1e6
    if u in {"hz", ""}:
        return float(value) / 1e9
    return float(value)


def parse_s11_csv(path: Path) -> tuple[list[float], list[float]]:
    series = parse_s11_series(path)
    if not series:
        raise SystemExit(f"no S11 points in CSV {path}")
    return series[0][1], series[0][2]


def parse_s11_series(path: Path) -> list[tuple[str, list[float], list[float]]]:
    """One or more traces. Family CSVs use freq_ghz,variation,s11_db."""
    text = path.read_text(encoding="utf-8", errors="replace")
    rows = list(csv.reader(text.splitlines()))
    if not rows:
        raise SystemExit(f"no S11 points in CSV {path}")
    header = [str(c).strip() for c in rows[0]]
    lowered = [h.lower() for h in header]
    if lowered[:3] == ["freq_ghz", "variation", "s11_db"]:
        grouped: dict[str, tuple[list[float], list[float]]] = {}
        for raw in rows[1:]:
            if len(raw) < 3:
                continue
            try:
                freq = float(raw[0])
                db = float(raw[2])
            except ValueError:
                continue
            label = str(raw[1]).strip() or "trace"
            bucket = grouped.setdefault(label, ([], []))
            bucket[0].append(freq)
            bucket[1].append(db)
        if not grouped:
            raise SystemExit(f"no S11 points in CSV {path}")
        return [(label, freqs, dbs) for label, (freqs, dbs) in grouped.items()]
    freqs: list[float] = []
    dbs: list[float] = []
    headers: list[str] = []
    for raw in rows:
        if not raw or all(not str(cell).strip() for cell in raw):
            continue
        cells = [str(cell).strip() for cell in raw]
        numeric: list[float] = []
        ok = True
        for cell in cells:
            try:
                numeric.append(float(cell))
            except ValueError:
                ok = False
                break
        if ok and len(numeric) >= 2:
            freqs.append(numeric[0])
            dbs.append(numeric[1])
            continue
        if not headers:
            headers = cells
    if not freqs:
        raise SystemExit(f"no S11 points in CSV {path}")
    if headers:
        joined = " ".join(headers).lower()
        if "mhz" in joined:
            freqs = [f / 1e3 for f in freqs]
        elif "khz" in joined:
            freqs = [f / 1e6 for f in freqs]
        elif "[hz]" in joined:
            freqs = [f / 1e9 for f in freqs]
    return [(path.name, freqs, dbs)]


def parse_s11_file(path: Path) -> tuple[list[float], list[float]]:
    suffix = path.suffix.lower()
    if suffix in {".s1p", ".s2p", ".s3p", ".s4p", ".snp"}:
        return parse_touchstone_s11_db(path)
    return parse_s11_csv(path)


def parse_touchstone_s11_db(path: Path) -> tuple[list[float], list[float]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    freq_unit = "GHz"
    data_format = "MA"
    freqs: list[float] = []
    s11_db: list[float] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        if line.startswith("#"):
            tokens = line[1:].split()
            if tokens:
                freq_unit = tokens[0]
            if len(tokens) >= 3:
                data_format = tokens[2].upper()
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            f = float(parts[0])
            a = float(parts[1])
            b = float(parts[2])
        except ValueError:
            continue
        f_ghz = _freq_to_ghz(f, freq_unit)
        if data_format in {"DB", "DBANGLE"}:
            db = a
        elif data_format in {"RI"}:
            mag = max(math.hypot(a, b), 1e-30)
            db = 20.0 * math.log10(mag)
        else:
            mag = max(a, 1e-30)
            db = 20.0 * math.log10(mag)
        freqs.append(f_ghz)
        s11_db.append(db)
    if not freqs:
        raise SystemExit(f"no S-parameter points in {path}")
    return freqs, s11_db


def _polyline(
    freqs: list[float],
    dbs: list[float],
    fmin: float,
    fmax: float,
    dbmin: float,
    dbmax: float,
    x0: float,
    y0: float,
    w: float,
    h: float,
) -> str:
    pts: list[str] = []
    span_f = max(fmax - fmin, 1e-9)
    span_db = max(dbmax - dbmin, 1e-9)
    for f, db in zip(freqs, dbs, strict=False):
        x = x0 + (f - fmin) / span_f * w
        y = y0 + (dbmax - db) / span_db * h
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def strongest_s11_peak(
    freqs: list[float], dbs: list[float]
) -> tuple[float, float] | None:
    """Interior local maximum of S11 (bump toward 0 dB)."""
    peaks: list[tuple[float, float]] = []
    for i in range(1, len(dbs) - 1):
        if dbs[i] >= dbs[i - 1] and dbs[i] >= dbs[i + 1] and (
            dbs[i] > dbs[i - 1] or dbs[i] > dbs[i + 1]
        ):
            peaks.append((freqs[i], dbs[i]))
    if not peaks:
        return None
    return max(peaks, key=lambda item: item[1])


def write_svg(
    series: list[tuple[str, list[float], list[float], str]],
    out: Path,
    mark_ghz: float | None,
    *,
    mark_peaks: bool = False,
    thr_db: float = -10.0,
) -> None:
    all_f = [f for _, fs, _, _ in series for f in fs]
    all_db = [v for _, _, vs, _ in series for v in vs]
    fmin, fmax = min(all_f), max(all_f)
    dbmin, dbmax = min(all_db) - 1.0, max(all_db) + 1.0
    if dbmax - dbmin < 2:
        dbmax = dbmin + 2
    x0, y0, w, h = 56.0, 24.0, 520.0, 280.0
    colors = [
        "#1d4ed8",
        "#b45309",
        "#15803d",
        "#7c3aed",
        "#be123c",
        "#0f766e",
        "#a16207",
        "#334155",
    ]
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">',
        '<rect width="640" height="360" fill="#fff"/>',
        f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" fill="none" stroke="#111"/>',
        f'<text x="320" y="16" text-anchor="middle" font-size="12" font-family="sans-serif">S11 (dB)</text>',
        f'<text x="{x0 + w / 2:.1f}" y="348" text-anchor="middle" font-size="11" font-family="sans-serif">GHz</text>',
        f'<text x="12" y="{y0 + 12:.1f}" font-size="10" font-family="sans-serif">{dbmax:.1f}</text>',
        f'<text x="12" y="{y0 + h:.1f}" font-size="10" font-family="sans-serif">{dbmin:.1f}</text>',
        f'<text x="{x0:.1f}" y="338" font-size="10" font-family="sans-serif">{fmin:.2f}</text>',
        f'<text x="{x0 + w - 28:.1f}" y="338" font-size="10" font-family="sans-serif">{fmax:.2f}</text>',
    ]
    if mark_ghz is not None and fmin <= mark_ghz <= fmax:
        x = x0 + (mark_ghz - fmin) / max(fmax - fmin, 1e-9) * w
        parts.append(
            f'<line x1="{x:.1f}" y1="{y0}" x2="{x:.1f}" y2="{y0 + h}" '
            f'stroke="#dc2626" stroke-dasharray="4 3"/>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{y0 - 4:.1f}" text-anchor="middle" font-size="10" '
            f'font-family="sans-serif" fill="#dc2626">{mark_ghz:g} GHz</text>'
        )
    if dbmin < thr_db < dbmax:
        y_thr = y0 + (dbmax - thr_db) / max(dbmax - dbmin, 1e-9) * h
        parts.append(
            f'<line x1="{x0}" y1="{y_thr:.1f}" x2="{x0 + w}" y2="{y_thr:.1f}" '
            f'stroke="#64748b" stroke-dasharray="5 4"/>'
        )
    peak_xy: list[tuple[str, float, float]] = []
    span_f = max(fmax - fmin, 1e-9)
    span_db = max(dbmax - dbmin, 1e-9)
    for i, (label, freqs, dbs, _) in enumerate(series):
        color = colors[i % len(colors)]
        pts = _polyline(freqs, dbs, fmin, fmax, dbmin, dbmax, x0, y0, w, h)
        parts.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="1.6" points="{pts}"/>'
        )
        parts.append(
            f'<text x="{x0 + 8:.1f}" y="{y0 + 16 + i * 14:.1f}" font-size="11" '
            f'font-family="sans-serif" fill="{color}">{label}</text>'
        )
        if mark_peaks:
            peak = strongest_s11_peak(freqs, dbs)
            if peak is not None:
                pf, pdb = peak
                px = x0 + (pf - fmin) / span_f * w
                py = y0 + (dbmax - pdb) / span_db * h
                peak_xy.append((color, px, py))
    for color, px, py in peak_xy:
        parts.append(
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.2" fill="{color}" '
            f'stroke="#fff" stroke-width="0.8"/>'
        )
    parts.append("</svg>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot S11 from a Results CSV to SVG")
    parser.add_argument("curve", type=Path, help="primary freq_ghz,s11_db CSV (or leftover .s1p)")
    parser.add_argument("--overlay", type=Path, action="append", default=[], help="extra traces")
    parser.add_argument("--mark-ghz", type=float, default=None, help="vertical marker")
    parser.add_argument(
        "--mark-peaks",
        action="store_true",
        help="mark the strongest interior S11 bump on each trace",
    )
    parser.add_argument("--out", type=Path, default=None, help="output .svg")
    args = parser.parse_args()
    series: list[tuple[str, list[float], list[float], str]] = []
    paths = [args.curve, *args.overlay]
    for path in paths:
        for label, freqs, dbs in parse_s11_series(path):
            series.append((label, freqs, dbs, str(path)))
            min_i = min(range(len(dbs)), key=lambda i: dbs[i])
            print(f"{label}: min {dbs[min_i]:.3f} dB @ {freqs[min_i]:.3f} GHz")
            peak = strongest_s11_peak(freqs, dbs)
            if peak is None:
                print(f"{label}: no interior peak")
            else:
                print(f"{label}: peak {peak[1]:.3f} dB @ {peak[0]:.3f} GHz")
    out = args.out or args.curve.with_suffix(".svg")
    write_svg(series, out, args.mark_ghz, mark_peaks=args.mark_peaks)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
