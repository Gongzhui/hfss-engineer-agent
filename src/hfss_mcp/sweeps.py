"""Parametric sweep helpers: LIN point counts matching HFSS, table expansion."""

from __future__ import annotations

from typing import Any

from hfss_mcp.errors import PolicyError
from hfss_mcp.live import PARAMETRIC_MAX_POINTS


def lin_values(start: float, stop: float, step: float) -> list[float]:
    """Mirror HFSS ``LIN start stop step``: step grid, always include stop."""
    if step <= 0:
        raise PolicyError("step must be > 0", code="parametric_sweep_invalid")
    direction = 1.0 if stop >= start else -1.0
    step_abs = abs(float(step))
    step_signed = step_abs * direction
    eps = max(step_abs * 1e-9, 1e-12)
    values: list[float] = []
    i = 0
    while True:
        x = float(start) + i * step_signed
        if direction > 0 and x > float(stop) + eps:
            break
        if direction < 0 and x < float(stop) - eps:
            break
        values.append(x)
        i += 1
        if i > PARAMETRIC_MAX_POINTS + 8:
            break
    if not values:
        values = [float(start)]
    if abs(values[-1] - float(stop)) > eps:
        values.append(float(stop))
    return values


def expand_table_rows(
    rows: list[dict[str, Any]],
    *,
    allowed: set[str],
    units: dict[str, str],
    default_unit: str | None = None,
) -> tuple[list[str], list[dict[str, float]], dict[str, str]]:
    """Return (variable names in order, numeric rows, unit per variable)."""
    if len(rows) < 1:
        raise PolicyError(
            "table needs at least one row",
            code="parametric_sweep_invalid",
        )
    order: list[str] = []
    unit_map: dict[str, str] = {}
    numeric_rows: list[dict[str, float]] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise PolicyError(
                f"table row {index} must be an object",
                code="parametric_sweep_invalid",
            )
        row_unit = raw.get("unit")
        cleaned: dict[str, float] = {}
        for key, value in raw.items():
            name = str(key).strip()
            if not name or name == "unit":
                continue
            if name not in allowed:
                raise PolicyError(
                    f"variable {name!r} is not on the allowlist",
                    code="variable_not_allowed",
                    details={"name": name, "allowed": sorted(allowed)},
                )
            if name not in order:
                order.append(name)
                unit_map[name] = str(
                    row_unit or units.get(name) or default_unit or "mm"
                )
            try:
                cleaned[name] = float(value)
            except (TypeError, ValueError) as exc:
                raise PolicyError(
                    f"table row {index} value for {name!r} is not a number",
                    code="parametric_sweep_invalid",
                ) from exc
        if not cleaned:
            raise PolicyError(
                f"table row {index} has no variables",
                code="parametric_sweep_invalid",
            )
        missing = [name for name in order if name not in cleaned]
        if missing:
            raise PolicyError(
                f"table row {index} missing variables: {missing}",
                code="parametric_sweep_invalid",
                details={"missing": missing},
            )
        # Keep only known order keys (ignore extras already filtered).
        numeric_rows.append({name: cleaned[name] for name in order})
    if len(order) < 1:
        raise PolicyError("table needs at least one variable", code="parametric_sweep_invalid")
    return order, numeric_rows, unit_map


def linc_values(start: float, stop: float, count: int) -> list[float]:
    """Mirror HFSS ``LINC start stop count``: count points including both ends."""
    if count < 2:
        raise PolicyError(
            "linear_count needs count >= 2",
            code="parametric_sweep_invalid",
        )
    if count == 2:
        return [float(start), float(stop)]
    width = float(stop) - float(start)
    return [float(start) + width * i / (count - 1) for i in range(count)]


def cartesian_from_axes(axes: dict[str, list[float]]) -> list[dict[str, float]]:
    names = list(axes.keys())
    if not names:
        return []
    rows: list[dict[str, float]] = [{}]
    for name in names:
        nxt: list[dict[str, float]] = []
        for base in rows:
            for value in axes[name]:
                item = dict(base)
                item[name] = float(value)
                nxt.append(item)
        rows = nxt
    return rows
