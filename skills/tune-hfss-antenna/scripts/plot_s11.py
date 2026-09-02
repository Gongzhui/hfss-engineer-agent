#!/usr/bin/env python3
"""Plot S11 from a Results CSV (or leftover Touchstone).

Default output is PNG so Host Agents can `read` the figure. SVG remains available
via --format svg (stdlib-only path, no matplotlib required).
"""

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
    freq_i = next((i for i, name in enumerate(lowered) if "freq" in name), None)
    s11_cols = [
        i
        for i, name in enumerate(lowered)
        if "db(s(1,1))" in name or "db(s11)" in name or name == "s11_db"
    ]
    if freq_i is not None and len(s11_cols) == 1:
        db_i = s11_cols[0]
        var_is = [
            i
            for i in range(len(header))
            if i not in {freq_i, db_i} and "db(" not in lowered[i]
        ]
        if var_is:
            freq_unit = "GHz"
            for token in header[freq_i].replace("[", " ").replace("]", " ").split():
                if token.lower() in {"ghz", "mhz", "khz", "hz"}:
                    freq_unit = token
                    break
            grouped = {}
            for raw in rows[1:]:
                if max(freq_i, db_i, max(var_is)) >= len(raw):
                    continue
                try:
                    freq = _freq_to_ghz(float(raw[freq_i]), freq_unit)
                    db = float(raw[db_i])
                except ValueError:
                    continue
                parts = []
                for index in var_is:
                    name = header[index].split("[", 1)[0].strip().strip('"') or f"v{index}"
                    unit = ""
                    if "[" in header[index] and "]" in header[index]:
                        unit = header[index].split("[", 1)[1].split("]", 1)[0].strip()
                        if unit == "[]":
                            unit = ""
                    parts.append(f"{name}='{raw[index].strip()}{unit}'")
                label = " ".join(parts) or "trace"
                bucket = grouped.setdefault(label, ([], []))
                bucket[0].append(freq)
                bucket[1].append(db)
            if grouped:
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
    for i, (label, freqs, dbs, _) in enumerate(series):
        color = colors[i % len(colors)]
        pts = _polyline(freqs, dbs, fmin, fmax, dbmin, dbmax, x0, y0, w, h)
        parts.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="1.6" points="{pts}"/>'
        )
        short = label if len(label) <= 48 else label[:45] + "..."
        parts.append(
            f'<text x="{x0 + 8:.1f}" y="{y0 + 16 + i * 14:.1f}" font-size="11" '
            f'font-family="sans-serif" fill="{color}">{short}</text>'
        )
    parts.append("</svg>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts), encoding="utf-8")


def write_png(
    series: list[tuple[str, list[float], list[float], str]],
    out: Path,
    mark_ghz: float | None,
) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit(
            "PNG output needs matplotlib. Run with: "
            "uv run --with matplotlib python .../plot_s11.py ... "
            "or pass --format svg"
        ) from exc

    out.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    for label, freqs, dbs, _ in series:
        short = label if len(label) <= 60 else label[:57] + "..."
        ax.plot(freqs, dbs, lw=1.4, label=short)
    if mark_ghz is not None:
        ax.axvline(mark_ghz, color="#dc2626", ls="--", lw=1.0, label=f"{mark_ghz:g} GHz")
    ax.axhline(-10.0, color="#6b7280", ls=":", lw=0.9)
    ax.set_xlabel("GHz")
    ax.set_ylabel("S11 (dB)")
    ax.grid(True, alpha=0.3)
    if len(series) <= 16:
        ax.legend(fontsize=7, loc="best")
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot S11 from a Results CSV (PNG by default; SVG optional)"
    )
    parser.add_argument("curve", type=Path, help="primary freq_ghz,s11_db CSV (or leftover .s1p)")
    parser.add_argument("--overlay", type=Path, action="append", default=[], help="extra traces")
    parser.add_argument("--mark-ghz", type=float, default=None, help="vertical marker")
    parser.add_argument("--out", type=Path, default=None, help="output path")
    parser.add_argument(
        "--format",
        choices=("png", "svg"),
        default="png",
        help="output format (default: png, readable by Host Agent vision)",
    )
    args = parser.parse_args()
    series: list[tuple[str, list[float], list[float], str]] = []
    paths = [args.curve, *args.overlay]
    for path in paths:
        parsed = (
            [(path.name, *parse_touchstone_s11_db(path))]
            if path.suffix.lower() in {".s1p", ".s2p", ".s3p", ".s4p", ".snp"}
            else parse_s11_series(path)
        )
        for label, freqs, dbs in parsed:
            series.append((label, freqs, dbs, str(path)))
            min_i = min(range(len(dbs)), key=lambda i: dbs[i])
            print(f"{label}: min {dbs[min_i]:.3f} dB @ {freqs[min_i]:.3f} GHz")
    fmt = args.format
    if args.out is not None and args.out.suffix.lower() in {".svg", ".png"}:
        fmt = args.out.suffix.lower().lstrip(".")
    out = args.out or args.curve.with_suffix(f".{fmt}")
    if fmt == "svg":
        write_svg(series, out, args.mark_ghz)
    else:
        write_png(series, out, args.mark_ghz)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
