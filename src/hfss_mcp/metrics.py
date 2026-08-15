"""Parse HFSS ReportSetup CSV (and leftover Touchstone) into agent-facing arrays."""

from __future__ import annotations

import csv
import math
import re
from pathlib import Path

from hfss_mcp.errors import AdapterError

_UNIT_IN_HEADER = re.compile(r"\[([^\]]+)\]")


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


def parse_hfss_report_table(path: Path) -> tuple[list[str], list[list[float]]]:
    """Parse ReportSetup ExportToFile CSV into (headers, numeric rows)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    rows_in = list(csv.reader(text.splitlines()))
    headers: list[str] = []
    data: list[list[float]] = []
    for raw in rows_in:
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
        if ok and numeric:
            data.append(numeric)
            continue
        if not headers:
            headers = cells
    if not data:
        raise AdapterError(
            f"no numeric traces in HFSS report CSV {path}",
            code="empty_report_csv",
        )
    return headers, data


def _header_unit(header: str, default: str) -> str:
    match = _UNIT_IN_HEADER.search(header or "")
    return match.group(1) if match else default


def _col_index(headers: list[str], *needles: str) -> int | None:
    lowered = [h.lower() for h in headers]
    for needle in needles:
        key = needle.lower()
        for i, header in enumerate(lowered):
            if key in header:
                return i
    return None


def _s11_trace_columns(headers: list[str]) -> list[tuple[int, str]]:
    cols: list[tuple[int, str]] = []
    for i, header in enumerate(headers):
        lowered = header.lower()
        if "db(s(1,1))" not in lowered and "db(s11)" not in lowered and lowered != "s11_db":
            continue
        label = "nominal"
        if " - " in header:
            label = header.split(" - ", 1)[1].strip()
        cols.append((i, label or "nominal"))
    return cols


def normalize_exported_report_csv(path: Path, report_type: str | None = None) -> Path:
    """Rewrite a ReportSetup CSV into the Skill's stable columns when possible."""
    path = Path(path)
    first_line = next(
        (
            line
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        ),
        "",
    )
    head = [cell.strip().strip('"') for cell in first_line.split(",")]
    lowered_head = [h.lower() for h in head]
    if head[:3] == ["freq_ghz", "variation", "s11_db"]:
        return path
    if head[:2] == ["freq_ghz", "s11_db"] and "variation" not in lowered_head:
        return path
    headers, rows = parse_hfss_report_table(path)
    joined = " ".join(headers).lower()
    kind = report_type
    if kind is None:
        if "dB(S(1,1))".lower() in joined or "dB(S11)".lower() in joined:
            kind = "modal_s"
        elif "re(z" in joined or "im(z" in joined:
            kind = "terminal_z"
        elif "theta" in joined or "gain" in joined:
            kind = "farfield_2d"
    if kind == "modal_s":
        freq_i = _col_index(headers, "freq")
        if freq_i is None:
            freq_i = 0
        traces = _s11_trace_columns(headers)
        if not traces:
            db_i = 1 if len(rows[0]) > 1 else 0
            traces = [(db_i, "nominal")]
        unit = _header_unit(headers[freq_i] if headers else "", "GHz")
        if len(traces) == 1:
            db_i, _label = traces[0]
            lines = ["freq_ghz,s11_db"]
            for row in rows:
                if max(freq_i, db_i) >= len(row):
                    continue
                lines.append(f"{_freq_to_ghz(row[freq_i], unit):.6g},{row[db_i]:.6g}")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return path
        lines = ["freq_ghz,variation,s11_db"]
        for row in rows:
            if freq_i >= len(row):
                continue
            freq = _freq_to_ghz(row[freq_i], unit)
            for db_i, label in traces:
                if db_i >= len(row):
                    continue
                safe = label.replace(",", " ")
                lines.append(f"{freq:.6g},{safe},{row[db_i]:.6g}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
    if kind == "terminal_z":
        freq_i = _col_index(headers, "freq")
        if freq_i is None:
            freq_i = 0
        re_i = _col_index(headers, "re(z")
        if re_i is None:
            re_i = 1
        im_i = _col_index(headers, "im(z")
        if im_i is None:
            im_i = 2 if len(rows[0]) > 2 else 1
        unit = _header_unit(headers[freq_i] if headers else "", "GHz")
        lines = ["freq_ghz,re,im"]
        for row in rows:
            if max(freq_i, re_i, im_i) >= len(row):
                continue
            lines.append(
                f"{_freq_to_ghz(row[freq_i], unit):.6g},{row[re_i]:.6g},{row[im_i]:.6g}"
            )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
    if kind == "farfield_2d":
        theta_i = _col_index(headers, "theta")
        gain_i = _col_index(headers, "dB(GainTotal)", "gain")
        if theta_i is not None and gain_i is not None:
            lines = ["theta_deg,db_gain_total"]
            for row in rows:
                if max(theta_i, gain_i) >= len(row):
                    continue
                lines.append(f"{row[theta_i]:.6g},{row[gain_i]:.6g}")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
    return path


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
