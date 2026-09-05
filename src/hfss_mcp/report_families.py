"""Report selections are per-variable value sets, not zipped Optimetrics rows."""

from __future__ import annotations

import math
import re

from hfss_mcp.errors import PolicyError

FamilySelection = list[str] | dict[str, list[str | float]]
_VALUE = re.compile(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-z_%µμ]*)")


def family_values(selection: FamilySelection | None, units: dict[str, str]) -> dict[str, list[str]]:
    """Normalize finite numeric choices; bare numbers use the allowlist unit."""
    if selection is None:
        return {}
    raw = {name: ["All"] for name in selection} if isinstance(selection, list) else selection
    out: dict[str, list[str]] = {}
    for name, values in raw.items():
        if name not in units:
            raise PolicyError(
                f"variable {name!r} is not on the allowlist", code="variable_not_allowed"
            )
        if not isinstance(values, list) or not values:
            raise PolicyError(f"{name}: select at least one value", code="report_family_values")
        normalized: list[str] = []
        for value in values:
            text = str(value).strip()
            if text.lower() in {"all", "nominal"}:
                if len(values) != 1:
                    raise PolicyError(
                        "All/Nominal cannot be mixed with other values", code="report_family_values"
                    )
                text = text.title()
            else:
                match = _VALUE.fullmatch(text)
                if not match or not math.isfinite(float(match[1])):
                    raise PolicyError(
                        f"invalid family value {value!r}", code="report_family_values"
                    )
                text = f"{float(match[1]):.15g}{match[2] or units[name]}"
            if text not in normalized:
                normalized.append(text)
        out[name] = normalized
    return out
