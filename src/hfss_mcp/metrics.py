"""Parse network exports (Touchstone) into CSV-friendly arrays."""

from __future__ import annotations

import math
from pathlib import Path

from hfss_mcp.errors import AdapterError


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


def _parse_touchstone_rows(
    path: Path,
) -> tuple[str, str, list[float], list[float], list[float]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    freq_unit = "GHz"
    data_format = "MA"
    param = "S"
    freqs: list[float] = []
    col_a: list[float] = []
    col_b: list[float] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        if line.startswith("#"):
            tokens = line[1:].split()
            if tokens:
                freq_unit = tokens[0]
            if len(tokens) >= 2:
                param = tokens[1].upper()
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
        freqs.append(_freq_to_ghz(f, freq_unit))
        col_a.append(a)
        col_b.append(b)
    if not freqs:
        raise AdapterError(
            f"no network-parameter points in {path}",
            code="empty_touchstone",
        )
    return param, data_format, freqs, col_a, col_b


def parse_touchstone_s11_db(path: Path) -> tuple[list[float], list[float]]:
    """Parse Touchstone (.s1p/.sNp) into (freq_ghz, s11_db) arrays."""
    _param, data_format, freqs, col_a, col_b = _parse_touchstone_rows(path)
    s11_db: list[float] = []
    for a, b in zip(col_a, col_b, strict=False):
        if data_format in {"DB", "DBANGLE"}:
            db = a
        elif data_format in {"RI"}:
            mag = max(math.hypot(a, b), 1e-30)
            db = 20.0 * math.log10(mag)
        else:
            mag = max(a, 1e-30)
            db = 20.0 * math.log10(mag)
        s11_db.append(db)
    return freqs, s11_db


def parse_touchstone_z11(path: Path) -> tuple[list[float], list[float], list[float]]:
    """Parse Z-parameter Touchstone into (freq_ghz, real, imag)."""
    _param, data_format, freqs, col_a, col_b = _parse_touchstone_rows(path)
    reals: list[float] = []
    imags: list[float] = []
    for a, b in zip(col_a, col_b, strict=False):
        if data_format in {"RI"}:
            reals.append(a)
            imags.append(b)
        elif data_format in {"DB", "DBANGLE"}:
            mag = 10.0 ** (a / 20.0)
            ang = math.radians(b)
            reals.append(mag * math.cos(ang))
            imags.append(mag * math.sin(ang))
        else:
            ang = math.radians(b)
            reals.append(a * math.cos(ang))
            imags.append(a * math.sin(ang))
    return freqs, reals, imags
