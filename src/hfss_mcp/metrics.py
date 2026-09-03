"""Parse HFSS ReportSetup CSV (and leftover Touchstone) into agent-facing arrays."""

from __future__ import annotations

import csv
import io
import math
import re
from pathlib import Path
from typing import Any

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


def _header_name_unit(header: str) -> tuple[str, str]:
    text = (header or "").strip().strip('"')
    match = _UNIT_IN_HEADER.search(text)
    if not match:
        return text, ""
    return text[: match.start()].strip(), match.group(1).strip()


def _is_freq_header(header: str) -> bool:
    return "freq" in (header or "").lower()


def _is_s11_header(header: str) -> bool:
    lowered = (header or "").lower()
    return "db(s(1,1))" in lowered or "db(s11)" in lowered or lowered == "s11_db"


def _is_expression_header(header: str) -> bool:
    """True for Y-trace headers like dB(S(1,1)) / cang_deg_val(S(1,1)), not swept vars."""
    if _is_freq_header(header):
        return False
    lowered = (header or "").lower().strip()
    if lowered in {"variation", "theta", "phi", "freq", "freq_ghz", "s11_db", "value", "re", "im"}:
        return False
    name, _unit = _header_name_unit(header)
    compact = name.lower().replace(" ", "")
    if "(" in compact and ")" in compact:
        return True
    return compact in {"s11_db", "value"}


def _variation_value_columns(
    headers: list[str], freq_i: int
) -> list[tuple[int, str, str]]:
    """Swept-variable columns from GUI Export Data (Separate Columns unchecked)."""
    cols: list[tuple[int, str, str]] = []
    for index, header in enumerate(headers):
        if index == freq_i or _is_s11_header(header) or _is_freq_header(header):
            continue
        if _is_expression_header(header):
            continue
        lowered = header.lower()
        if lowered in {"variation", "theta", "phi"}:
            continue
        name, unit = _header_name_unit(header)
        if not name:
            continue
        cols.append((index, name, unit))
    return cols


def _combo_label(columns: list[tuple[int, str, str]], row: list[float]) -> str:
    parts: list[str] = []
    for index, name, unit in columns:
        if index >= len(row):
            continue
        value = f"{row[index]:.6g}"
        suffix = unit if unit and unit != "[]" else ""
        parts.append(f"{name}='{value}{suffix}'")
    return " ".join(parts)


def _s11_trace_columns(headers: list[str]) -> list[tuple[int, str]]:
    cols: list[tuple[int, str]] = []
    for i, header in enumerate(headers):
        lowered = header.lower()
        if lowered in {"freq", "freq_ghz", "variation"}:
            continue
        if (
            "db(s(1,1))" not in lowered
            and "db(s11)" not in lowered
            and lowered != "s11_db"
        ):
            continue
        label = "nominal"
        if " - " in header:
            label = header.split(" - ", 1)[1].strip()
        cols.append((i, label or "nominal"))
    return cols


def _freq_cycle_spans(freqs: list[float]) -> list[tuple[int, int]]:
    """Split a stacked sweep where frequency restarts at the beginning of each trace."""
    if len(freqs) < 4:
        return [(0, len(freqs))]
    spans: list[tuple[int, int]] = []
    start = 0
    for i in range(1, len(freqs)):
        if freqs[i] + 1e-9 < freqs[i - 1]:
            if i - start >= 2:
                spans.append((start, i))
            start = i
    if len(freqs) - start >= 2:
        spans.append((start, len(freqs)))
    if len(spans) < 2:
        return [(0, len(freqs))]
    lengths = [end - begin for begin, end in spans]
    typical = sorted(lengths)[len(lengths) // 2]
    if typical < 2:
        return [(0, len(freqs))]
    return spans


def _legend_label(name: str) -> str:
    """Strip the quantity prefix so a trace name becomes the plot-legend combination."""
    text = str(name).strip().strip('"')
    for sep in (" - ", " : "):
        if sep in text:
            tail = text.split(sep, 1)[1].strip()
            if tail:
                text = tail
                break
    return text.replace(",", " ")


def _legend_labels(trace_names: list[str] | None) -> list[str]:
    """Keep names that identify a parameter combination (the GUI legend)."""
    labels: list[str] = []
    for raw in trace_names or []:
        label = _legend_label(raw)
        if not label:
            continue
        lowered = label.lower()
        if lowered in {"db(s(1,1))", "db(s(1,1)) []", "db(s11)", "s11", "s11_db", "nominal"}:
            continue
        labels.append(label)
    return labels


def _relabel_placeholder_variations(path: Path, trace_names: list[str] | None) -> Path:
    """Replace trace_000 placeholders with legend combinations when counts match."""
    labels = _legend_labels(trace_names)
    if not labels:
        return path
    rows = list(csv.reader(path.read_text(encoding="utf-8", errors="replace").splitlines()))
    if not rows:
        return path
    header = [cell.strip() for cell in rows[0]]
    if [h.lower() for h in header[:3]] != ["freq_ghz", "variation", "s11_db"]:
        return path
    order: list[str] = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        key = row[1]
        if key not in order:
            order.append(key)
    if not order or any(not str(item).startswith("trace_") for item in order):
        return path
    mapping = {
        old: labels[index]
        for index, old in enumerate(order)
        if index < len(labels)
    }
    if not mapping:
        return path
    lines = ["freq_ghz,variation,s11_db"]
    for row in rows[1:]:
        if len(row) < 3:
            continue
        tag = mapping.get(row[1], row[1]).replace(",", " ")
        lines.append(f"{row[0]},{tag},{row[2]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def csv_export_summary(path: Path) -> dict[str, Any]:
    """Describe a normalized report CSV so the agent does not have to guess the shape."""
    path = Path(path)
    rows = list(csv.reader(path.read_text(encoding="utf-8", errors="replace").splitlines()))
    if not rows:
        return {"traces": 0, "labeled": False, "header": []}
    header = [cell.strip() for cell in rows[0]]
    lowered = [h.lower() for h in header]
    if lowered[:3] == ["freq_ghz", "variation", "s11_db"]:
        labels = {row[1] for row in rows[1:] if len(row) >= 3}
        labeled = any(not str(item).startswith("trace_") for item in labels)
        return {
            "header": header,
            "traces": len(labels),
            "labeled": labeled,
            "format": "family",
        }
    if lowered[:2] == ["freq_ghz", "s11_db"]:
        return {"header": header, "traces": 1, "labeled": True, "format": "single"}
    if lowered[:3] == ["freq_ghz", "re", "im"]:
        return {"header": header, "traces": 1, "labeled": True, "format": "terminal_z"}
    if lowered[:3] == ["freq_ghz", "variation", "value"]:
        labels = {row[1] for row in rows[1:] if len(row) >= 3}
        return {
            "header": header,
            "traces": len(labels),
            "labeled": True,
            "format": "expression_family",
        }
    if lowered[:2] == ["freq_ghz", "value"]:
        return {"header": header, "traces": 1, "labeled": True, "format": "expression"}
    if lowered[:1] == ["freq_ghz"] and len(header) > 2:
        return {
            "header": header,
            "traces": len(header) - 1,
            "labeled": True,
            "format": "multi",
        }
    return {"header": header, "traces": None, "labeled": False, "format": "raw"}


def _band_containing(
    freqs: list[float],
    values: list[float],
    *,
    target: float,
    threshold: float,
) -> tuple[float, float] | None:
    if not freqs:
        return None
    nearest_i = min(range(len(freqs)), key=lambda i: abs(freqs[i] - target))
    if values[nearest_i] > threshold:
        return None
    lo = nearest_i
    while lo > 0 and values[lo - 1] <= threshold:
        lo -= 1
    hi = nearest_i
    while hi < len(values) - 1 and values[hi + 1] <= threshold:
        hi += 1
    return freqs[lo], freqs[hi]


def summarize_modal_s_csv(
    path: Path,
    *,
    target_ghz: float,
    threshold_db: float = -10.0,
) -> dict[str, Any]:
    """Per-trace near-target / band / FBW / sweep-edge flags for Modal S CSVs."""
    path = Path(path)
    rows = list(csv.reader(path.read_text(encoding="utf-8", errors="replace").splitlines()))
    if not rows:
        return {"traces": []}
    header = [cell.strip().lower() for cell in rows[0]]
    series: dict[str, list[tuple[float, float]]] = {}
    if header[:3] == ["freq_ghz", "variation", "s11_db"]:
        for raw in rows[1:]:
            if len(raw) < 3:
                continue
            try:
                freq = float(raw[0])
                db = float(raw[2])
            except ValueError:
                continue
            series.setdefault(str(raw[1]), []).append((freq, db))
    elif header[:2] == ["freq_ghz", "s11_db"]:
        pts: list[tuple[float, float]] = []
        for raw in rows[1:]:
            if len(raw) < 2:
                continue
            try:
                pts.append((float(raw[0]), float(raw[1])))
            except ValueError:
                continue
        series["nominal"] = pts
    else:
        return {"traces": [], "note": "unsupported csv shape for modal_s summarize"}

    out: list[dict[str, Any]] = []
    for label, pts in series.items():
        pts = sorted(pts, key=lambda item: item[0])
        freqs = [p[0] for p in pts]
        dbs = [p[1] for p in pts]
        if not freqs:
            continue
        near_i = min(range(len(freqs)), key=lambda i: abs(freqs[i] - target_ghz))
        band = _band_containing(freqs, dbs, target=target_ghz, threshold=threshold_db)
        fbw = None
        if band is not None and (band[0] + band[1]) != 0:
            fbw = 2.0 * (band[1] - band[0]) / (band[1] + band[0])
        min_i = min(range(len(dbs)), key=lambda i: dbs[i])
        truncated = False
        if band is not None:
            truncated = abs(band[0] - freqs[0]) < 1e-9 or abs(band[1] - freqs[-1]) < 1e-9
        out.append(
            {
                "variation": label,
                "near_target_db": dbs[near_i],
                "near_target_ghz": freqs[near_i],
                "band_ghz": list(band) if band else None,
                "fbw": fbw,
                "min_db": dbs[min_i],
                "min_ghz": freqs[min_i],
                "band_truncated_by_sweep": truncated,
                "touches_sweep_edge": truncated,
                "sweep_ghz": [freqs[0], freqs[-1]],
            }
        )
    return {
        "target_ghz": target_ghz,
        "threshold_db": threshold_db,
        "traces": out,
    }


def summarize_terminal_z_csv(
    path: Path,
    *,
    target_ghz: float,
) -> dict[str, Any]:
    path = Path(path)
    rows = list(csv.reader(path.read_text(encoding="utf-8", errors="replace").splitlines()))
    if not rows:
        return {"points": []}
    header = [cell.strip().lower() for cell in rows[0]]
    if header[:3] != ["freq_ghz", "re", "im"]:
        return {"points": [], "note": "unsupported csv shape for terminal_z summarize"}
    pts: list[tuple[float, float, float]] = []
    for raw in rows[1:]:
        if len(raw) < 3:
            continue
        try:
            pts.append((float(raw[0]), float(raw[1]), float(raw[2])))
        except ValueError:
            continue
    if not pts:
        return {"points": []}
    near = min(pts, key=lambda item: abs(item[0] - target_ghz))
    im_crossings = 0
    for left, right in zip(pts, pts[1:], strict=False):
        if left[2] == 0 or right[2] == 0 or (left[2] < 0) != (right[2] < 0):
            if left[2] == 0 and right[2] == 0:
                continue
            im_crossings += 1
    return {
        "target_ghz": target_ghz,
        "at_target": {"freq_ghz": near[0], "re": near[1], "im": near[2]},
        "at_sweep_edges": {
            "low": {"freq_ghz": pts[0][0], "re": pts[0][1], "im": pts[0][2]},
            "high": {"freq_ghz": pts[-1][0], "re": pts[-1][1], "im": pts[-1][2]},
        },
        "im_zero_crossings": im_crossings,
        "sweep_ghz": [pts[0][0], pts[-1][0]],
    }


def render_s11_png(path: Path, dest: Path, *, mark_ghz: float | None = None) -> Path:
    """Best-effort PNG for Host Agent vision. Requires matplotlib."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise AdapterError(
            "png export needs matplotlib in the hfss-mcp environment",
            code="png_dependency_missing",
        ) from exc

    summary_shape = csv_export_summary(path)
    rows = list(csv.reader(path.read_text(encoding="utf-8", errors="replace").splitlines()))
    series: dict[str, list[tuple[float, float]]] = {}
    fmt = summary_shape.get("format")
    if fmt == "family":
        for raw in rows[1:]:
            if len(raw) < 3:
                continue
            try:
                series.setdefault(str(raw[1]), []).append((float(raw[0]), float(raw[2])))
            except ValueError:
                continue
    elif fmt == "single":
        pts = []
        for raw in rows[1:]:
            if len(raw) < 2:
                continue
            try:
                pts.append((float(raw[0]), float(raw[1])))
            except ValueError:
                continue
        series["S11"] = pts
    else:
        raise AdapterError(
            "png export only supports modal_s CSV shapes",
            code="png_unsupported",
        )

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    for label, pts in series.items():
        pts = sorted(pts)
        short = label if len(label) <= 56 else label[:53] + "..."
        ax.plot([p[0] for p in pts], [p[1] for p in pts], lw=1.3, label=short)
    if mark_ghz is not None:
        ax.axvline(mark_ghz, color="#dc2626", ls="--", lw=1.0)
    ax.axhline(-10.0, color="#6b7280", ls=":", lw=0.9)
    ax.set_xlabel("GHz")
    ax.set_ylabel("S11 (dB)")
    ax.grid(True, alpha=0.3)
    if 0 < len(series) <= 16:
        ax.legend(fontsize=7, loc="best")
    fig.tight_layout()
    fig.savefig(dest, dpi=140)
    plt.close(fig)
    return dest


def _is_classic_s11_db_header(header: str) -> bool:
    lowered = (header or "").lower().replace(" ", "")
    return "db(s(1,1))" in lowered or "db(s11)" in lowered or lowered == "s11_db"


def _expression_columns(headers: list[str]) -> list[tuple[int, str]]:
    """Y-expression columns: anything that looks like f(...), not Freq/vars."""
    cols: list[tuple[int, str]] = []
    for i, header in enumerate(headers):
        if _is_freq_header(header):
            continue
        lowered = header.lower()
        if lowered in {"variation", "theta", "phi"}:
            continue
        name, _unit = _header_name_unit(header)
        compact = name.lower().replace(" ", "")
        if "(" in compact and ")" in compact:
            cols.append((i, name.strip() or header.strip()))
            continue
        if compact in {"s11_db", "value"}:
            cols.append((i, name.strip() or "value"))
    return cols


def _csv_safe_header(text: str) -> str:
    return re.sub(r"[,\n\r]+", " ", str(text)).strip() or "value"


def normalize_exported_report_csv(
    path: Path,
    report_type: str | None = None,
    trace_names: list[str] | None = None,
    expressions: list[str] | None = None,
) -> Path:
    """Rewrite a ReportSetup CSV into the Skill's stable columns when possible.

    Prefer the GUI Export Data table (one column per swept variable, then Freq,
    then the quantity). GetTraceNames is only a fallback for stacked dumps.
    Classic single-trace dB(S(1,1)) keeps freq_ghz[,variation],s11_db. Other
    expressions keep value / wide expression columns — never forced to s11_db.
    """
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
        return _relabel_placeholder_variations(path, trace_names)
    if head[:2] == ["freq_ghz", "s11_db"] and "variation" not in lowered_head:
        return path
    if lowered_head[:3] == ["freq_ghz", "re", "im"]:
        return path
    if lowered_head[:1] == ["freq_ghz"] and "value" in lowered_head:
        return path
    headers, rows = parse_hfss_report_table(path)
    joined = " ".join(headers).lower()
    kind = report_type
    expr_list = [str(x) for x in (expressions or []) if str(x).strip()]
    header_exprs = _expression_columns(headers)
    header_expr_names = [label for _i, label in header_exprs]

    def _expr_base(label: str) -> str:
        text = label.split(" - ", 1)[0].strip().lower().replace(" ", "")
        return re.sub(r"\[\]$", "", text).strip()

    # Prefer header shape over report_type guess: multi-Y or non-dB(S11) must not
    # go through the classic s11_db path (phase columns used to be mistaken for
    # swept variables). Same-base dB(S11) family columns stay on modal_s.
    if len(header_exprs) > 1:
        bases = {_expr_base(n) for n in header_expr_names}
        if bases <= {"db(s(1,1))", "db(s11)"}:
            kind = "modal_s"
        elif bases == {"re(z(1,1))", "im(z(1,1))"} or bases == {
            "re(zt(1,1))",
            "im(zt(1,1))",
        }:
            kind = "terminal_z"
        else:
            kind = "curve_expr"
            if not expr_list:
                expr_list = header_expr_names
    elif len(header_exprs) == 1 and not _is_classic_s11_db_header(header_expr_names[0]):
        kind = "curve_expr"
        if not expr_list:
            expr_list = header_expr_names
    elif kind in {None, "curve", "modal_s"}:
        if "dB(S(1,1))".lower() in joined or "dB(S11)".lower() in joined:
            if not expr_list or (
                len(expr_list) == 1
                and expr_list[0].lower().replace(" ", "") in {"db(s(1,1))", "db(s11)"}
            ):
                kind = "modal_s"
        elif "re(z" in joined and "im(z" in joined:
            kind = "terminal_z"
        elif "theta" in joined or "gain" in joined:
            kind = "farfield_2d"
        else:
            kind = "curve"
    # Non-classic modal expressions from explicit create args.
    if kind in {"modal_s", "curve"} and expr_list:
        classic_s11 = len(expr_list) == 1 and expr_list[0].lower().replace(" ", "") in {
            "db(s(1,1))",
            "db(s11)",
        }
        classic_z = {e.lower().replace(" ", "") for e in expr_list} == {
            "re(z(1,1))",
            "im(z(1,1))",
        } or {e.lower().replace(" ", "") for e in expr_list} == {
            "re(zt(1,1))",
            "im(zt(1,1))",
        }
        if classic_z:
            kind = "terminal_z"
        elif not classic_s11:
            kind = "curve_expr"
    if kind == "modal_s":
        freq_i = _col_index(headers, "freq")
        if freq_i is None:
            freq_i = 0
        traces = _s11_trace_columns(headers)
        if not traces:
            db_i = 1 if len(rows[0]) > 1 else 0
            traces = [(db_i, "nominal")]
        unit = _header_unit(headers[freq_i] if headers else "", "GHz")
        var_cols = _variation_value_columns(headers, freq_i)
        if var_cols and len(traces) == 1:
            db_i = traces[0][0]
            needed = max(freq_i, db_i, max(col[0] for col in var_cols))
            labeled_rows: list[tuple[float, str, float]] = []
            unique: list[str] = []
            for row in rows:
                if needed >= len(row):
                    continue
                tag = _combo_label(var_cols, row).replace(",", " ")
                if not tag:
                    continue
                labeled_rows.append(
                    (_freq_to_ghz(row[freq_i], unit), tag, float(row[db_i]))
                )
                if tag not in unique:
                    unique.append(tag)
            if len(unique) == 1:
                lines = ["freq_ghz,s11_db"]
                for freq, _tag, db in labeled_rows:
                    lines.append(f"{freq:.6g},{db:.6g}")
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return path
            if unique:
                lines = ["freq_ghz,variation,s11_db"]
                for freq, tag, db in labeled_rows:
                    lines.append(f"{freq:.6g},{tag},{db:.6g}")
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return path
        variation_i = _col_index(headers, "variation")
        if variation_i is not None and variation_i != freq_i:
            lines = ["freq_ghz,variation,s11_db"]
            db_i = traces[0][0] if traces else (2 if len(rows[0]) > 2 else 1)
            for row in rows:
                if max(freq_i, variation_i, db_i) >= len(row):
                    continue
                lines.append(
                    f"{_freq_to_ghz(row[freq_i], unit):.6g},"
                    f"{str(row[variation_i]).replace(',', ' ')},{row[db_i]:.6g}"
                )
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return path
        if len(traces) == 1:
            db_i, label = traces[0]
            pairs: list[tuple[float, float]] = []
            for row in rows:
                if max(freq_i, db_i) >= len(row):
                    continue
                pairs.append((_freq_to_ghz(row[freq_i], unit), float(row[db_i])))
            spans = _freq_cycle_spans([freq for freq, _db in pairs])
            if len(spans) == 1:
                lines = ["freq_ghz,s11_db"]
                for freq, db in pairs:
                    lines.append(f"{freq:.6g},{db:.6g}")
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return path
            lines = ["freq_ghz,variation,s11_db"]
            legend = _legend_labels(trace_names)
            for index, (begin, end) in enumerate(spans):
                if index < len(legend):
                    tag = legend[index]
                elif label != "nominal":
                    tag = f"{label} #{index:03d}"
                else:
                    tag = f"trace_{index:03d}"
                for freq, db in pairs[begin:end]:
                    lines.append(f"{freq:.6g},{tag},{db:.6g}")
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
    if kind == "curve_expr":
        freq_i = _col_index(headers, "freq")
        if freq_i is None:
            freq_i = 0
        unit = _header_unit(headers[freq_i] if headers else "", "GHz")
        y_cols = _expression_columns(headers)
        if not y_cols and expr_list:
            # Fall back to trailing columns after Freq / vars.
            for i, header in enumerate(headers):
                if i == freq_i or _is_freq_header(header):
                    continue
                y_cols.append((i, _csv_safe_header(header)))
        if not y_cols:
            return path
        var_cols = [
            col
            for col in _variation_value_columns(headers, freq_i)
            if col[0] not in {i for i, _ in y_cols}
        ]
        # Drop false-positive variation cols that are actually expressions.
        var_cols = [
            col
            for col in var_cols
            if not _is_classic_s11_db_header(col[1])
            and "(" not in col[1]
        ]
        if len(y_cols) == 1 and not var_cols:
            lines = ["freq_ghz,value"]
            yi = y_cols[0][0]
            for row in rows:
                if max(freq_i, yi) >= len(row):
                    continue
                lines.append(
                    f"{_freq_to_ghz(row[freq_i], unit):.6g},{row[yi]:.6g}"
                )
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return path
        if len(y_cols) == 1 and var_cols:
            yi = y_cols[0][0]
            lines = ["freq_ghz,variation,value"]
            for row in rows:
                if max(freq_i, yi, max(c[0] for c in var_cols)) >= len(row):
                    continue
                tag = _combo_label(var_cols, row).replace(",", " ")
                lines.append(
                    f"{_freq_to_ghz(row[freq_i], unit):.6g},{tag},{row[yi]:.6g}"
                )
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return path
        # Wide multi-Y table (quote headers so S(1,1) commas survive).
        y_headers = [str(label).strip() or "value" for _i, label in y_cols]
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        if var_cols:
            writer.writerow(["freq_ghz", "variation", *y_headers])
            for row in rows:
                needed = max(
                    freq_i, max(c[0] for c in var_cols), max(i for i, _ in y_cols)
                )
                if needed >= len(row):
                    continue
                tag = _combo_label(var_cols, row).replace(",", " ")
                writer.writerow(
                    [
                        f"{_freq_to_ghz(row[freq_i], unit):.6g}",
                        tag,
                        *[f"{row[i]:.6g}" for i, _ in y_cols],
                    ]
                )
        else:
            writer.writerow(["freq_ghz", *y_headers])
            for row in rows:
                if max(freq_i, max(i for i, _ in y_cols)) >= len(row):
                    continue
                writer.writerow(
                    [
                        f"{_freq_to_ghz(row[freq_i], unit):.6g}",
                        *[f"{row[i]:.6g}" for i, _ in y_cols],
                    ]
                )
        path.write_text(buf.getvalue(), encoding="utf-8")
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
