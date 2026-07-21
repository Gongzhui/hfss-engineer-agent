"""Extract structured S11 metrics from real solution data (Touchstone or SolutionData)."""

from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Any

from hfss_mcp.errors import AdapterError
from hfss_mcp.metrics_spec import MetricKind, MetricSpec


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
    """Parse Touchstone (.s1p/.sNp) into (freq_ghz, s11_db) arrays."""
    text = path.read_text(encoding="utf-8", errors="replace")
    freq_unit = "GHz"
    data_format = "MA"  # magnitude/angle
    freqs: list[float] = []
    s11_db: list[float] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        if line.startswith("#"):
            # # GHZ S MA R 50
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
        elif data_format in {"MA", "MAG"}:
            # magnitude -> dB
            mag = max(a, 1e-30)
            db = 20.0 * math.log10(mag)
        elif data_format in {"RI"}:
            mag = max(math.hypot(a, b), 1e-30)
            db = 20.0 * math.log10(mag)
        else:
            mag = max(a, 1e-30)
            db = 20.0 * math.log10(mag)
        freqs.append(f_ghz)
        s11_db.append(db)
    if not freqs:
        raise AdapterError(
            f"no S-parameter points in touchstone {path}",
            code="empty_touchstone",
        )
    return freqs, s11_db


def extract_metric_from_arrays(
    freqs_ghz: list[float],
    vals_db: list[float],
    spec: MetricSpec,
) -> float:
    pairs = list(zip(freqs_ghz, vals_db, strict=False))
    if spec.kind == MetricKind.S11_MIN_IN_BAND:
        assert spec.f_min_ghz is not None and spec.f_max_ghz is not None
        band = [(f, v) for f, v in pairs if spec.f_min_ghz <= f <= spec.f_max_ghz]
        if not band:
            raise AdapterError(
                "no frequency points in requested band",
                code="empty_band",
                details={"f_min_ghz": spec.f_min_ghz, "f_max_ghz": spec.f_max_ghz},
            )
        return min(v for _, v in band)
    if spec.kind == MetricKind.S11_MIN_FREQ:
        assert spec.f_min_ghz is not None and spec.f_max_ghz is not None
        band = [(f, v) for f, v in pairs if spec.f_min_ghz <= f <= spec.f_max_ghz]
        if not band:
            raise AdapterError("no frequency points in requested band", code="empty_band")
        f_at, _ = min(band, key=lambda t: t[1])
        if spec.unit == "Hz":
            return f_at * 1e9
        return f_at
    if spec.kind == MetricKind.S11_AT_FREQ:
        assert spec.f_target_ghz is not None
        f_t = spec.f_target_ghz
        _f_best, v_best = min(pairs, key=lambda t: abs(t[0] - f_t))
        return v_best
    raise AdapterError(f"unsupported metric kind {spec.kind}", code="unsupported_metric")


def _export_touchstone(hfss: Any, setup: str, sweep: str | None, dest: Path) -> Path:
    """Export S-parameters via native Solutions module (PyAEDT osolution can be None)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    odesign = getattr(hfss, "odesign", None)
    if odesign is None:
        raise AdapterError("odesign unavailable", code="no_odesign")
    try:
        sol = odesign.GetModule("Solutions")
    except Exception as exc:
        raise AdapterError(
            f"Solutions module unavailable: {exc}",
            code="no_solutions_module",
        ) from exc

    solution_name = f"{setup}:{sweep}" if sweep else setup
    # ExportNetworkData signature used successfully on AEDT 2023.2 / PyAEDT 1.3
    try:
        sol.ExportNetworkData(
            "",
            [solution_name],
            3,
            str(dest),
            ["All"],
            True,
            50,
            "S",
            -1,
            0,
            15,
            True,
            False,
            False,
        )
    except Exception as exc:
        # Alternate solution name spacing
        alt = f"{setup} : {sweep}" if sweep else setup
        try:
            sol.ExportNetworkData(
                "",
                [alt],
                3,
                str(dest),
                ["All"],
                True,
                50,
                "S",
                -1,
                0,
                15,
                True,
                False,
                False,
            )
        except Exception as exc2:
            raise AdapterError(
                f"ExportNetworkData failed: {exc2}",
                code="touchstone_export_failed",
                details={"setup": setup, "sweep": sweep, "first_error": str(exc)},
            ) from exc2

    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    for candidate in dest.parent.glob("*.s*p"):
        if candidate.stat().st_size > 0:
            return candidate
    raise AdapterError(
        "touchstone file not found after export",
        code="touchstone_missing",
        details={"dest": str(dest)},
    )


def fetch_s11_curve(hfss: Any, spec: MetricSpec) -> tuple[list[float], list[float]]:
    """Return (freq_ghz, s11_db) from real solve results."""
    # Prefer Touchstone — avoids PyAEDT 1.3 solution_type bug in get_solution_data
    with tempfile.TemporaryDirectory(prefix="hfss-mcp-ts-") as tmp:
        dest = Path(tmp) / "sparams.s1p"
        try:
            ts = _export_touchstone(hfss, spec.setup, spec.sweep, dest)
            return parse_touchstone_s11_db(ts)
        except Exception as touch_exc:
            # Fallback: get_solution_data if fixed in future
            post = getattr(hfss, "post", None)
            if post is None or not hasattr(post, "get_solution_data"):
                raise AdapterError(
                    f"touchstone export failed and no solution_data: {touch_exc}",
                    code="metrics_extraction_failed",
                    details={"reason": str(touch_exc)},
                ) from touch_exc
            try:
                data = post.get_solution_data(
                    expressions=spec.expression(),
                    setup_sweep_name=spec.setup_sweep_name(),
                )
            except Exception as sol_exc:
                raise AdapterError(
                    f"metric extraction failed: touchstone={touch_exc}; solution_data={sol_exc}",
                    code="metrics_extraction_failed",
                ) from sol_exc
            return _arrays_from_solution_data(data)


def _arrays_from_solution_data(data: Any) -> tuple[list[float], list[float]]:
    if data is None or data is False:
        raise AdapterError("empty solution data", code="no_solution_data")
    freqs_raw = list(getattr(data, "primary_sweep_values", None) or [])
    units = getattr(data, "units_sweeps", {}) or {}
    freq_unit = str(units.get("Freq", "GHz"))
    values: list[float] = []
    for attr in ("data_magnitude", "data_real", "data_db"):
        getter = getattr(data, attr, None)
        if callable(getter):
            try:
                arr = getter()
                if arr is not None:
                    if arr and isinstance(arr[0], (list, tuple)):
                        values = [float(x) for x in arr[0]]
                    else:
                        values = [float(x) for x in arr]
                    break
            except Exception:
                continue
    if not freqs_raw or not values:
        raise AdapterError("incomplete solution arrays", code="incomplete_solution_data")
    n = min(len(freqs_raw), len(values))
    freqs = [_freq_to_ghz(float(freqs_raw[i]), freq_unit) for i in range(n)]
    # If magnitude not dB, convert heuristically when values look like linear mag
    vals = [float(values[i]) for i in range(n)]
    if vals and max(abs(v) for v in vals) < 5 and min(vals) >= 0:
        vals = [20.0 * math.log10(max(v, 1e-30)) for v in vals]
    return freqs, vals


def extract_metrics(hfss: Any, specs: list[MetricSpec]) -> dict[str, float]:
    # Group by setup/sweep
    cache: dict[tuple[str, str | None], tuple[list[float], list[float]]] = {}
    out: dict[str, float] = {}
    for spec in specs:
        key = (spec.setup, spec.sweep)
        if key not in cache:
            cache[key] = fetch_s11_curve(hfss, spec)
        freqs, vals = cache[key]
        out[spec.name] = extract_metric_from_arrays(freqs, vals, spec)
    return out
