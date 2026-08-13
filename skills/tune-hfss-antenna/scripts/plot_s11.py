#!/usr/bin/env python3
"""Plot S11 from a Touchstone .s1p/.sNp into SVG (stdlib only)."""

from __future__ import annotations

import argparse
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


def write_svg(
    series: list[tuple[str, list[float], list[float], str]],
    out: Path,
    mark_ghz: float | None,
) -> None:
    all_f = [f for _, fs, _, _ in series for f in fs]
    all_db = [v for _, _, vs, _ in series for v in vs]
    fmin, fmax = min(all_f), max(all_f)
    dbmin, dbmax = min(all_db) - 1.0, max(all_db) + 1.0
    if dbmax - dbmin < 2:
        dbmax = dbmin + 2
    x0, y0, w, h = 56.0, 24.0, 520.0, 280.0
    colors = ["#1d4ed8", "#b45309", "#15803d"]
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
    parts.append("</svg>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot S11 from Touchstone to SVG")
    parser.add_argument("touchstone", type=Path, help="primary .s1p / .sNp")
    parser.add_argument("--overlay", type=Path, action="append", default=[], help="extra traces")
    parser.add_argument("--mark-ghz", type=float, default=None, help="vertical marker")
    parser.add_argument("--out", type=Path, default=None, help="output .svg")
    args = parser.parse_args()
    series: list[tuple[str, list[float], list[float], str]] = []
    paths = [args.touchstone, *args.overlay]
    for path in paths:
        freqs, dbs = parse_touchstone_s11_db(path)
        series.append((path.name, freqs, dbs, str(path)))
        min_i = min(range(len(dbs)), key=lambda i: dbs[i])
        print(f"{path.name}: min {dbs[min_i]:.3f} dB @ {freqs[min_i]:.3f} GHz")
    out = args.out or args.touchstone.with_suffix(".svg")
    write_svg(series, out, args.mark_ghz)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
