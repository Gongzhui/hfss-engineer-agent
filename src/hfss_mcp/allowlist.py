"""Slim tune-only allowlist: identity + variable bounds. Not an optimizer contract."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from hfss_mcp.errors import ManifestError, PolicyError
from hfss_mcp.ids import canonical_json_hash


class ParameterBound(BaseModel):
    name: str
    unit: str
    min_value: float = Field(alias="min")
    max_value: float = Field(alias="max")

    model_config = {"populate_by_name": True, "extra": "forbid"}

    @field_validator("name", "unit")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("name and unit must be non-empty")
        return text

    @field_validator("min_value", "max_value")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("bounds must be finite")
        return value

    @model_validator(mode="after")
    def _range_ok(self) -> ParameterBound:
        if self.min_value > self.max_value:
            raise ValueError(f"{self.name}: min > max")
        return self


class Allowlist(BaseModel):
    """Writable variables for one project/design. Reads may see more."""

    project_name: str
    design_name: str
    parameters: list[ParameterBound]
    project_path: str | None = None
    default_setup: str | None = None
    default_sweep: str | None = None

    model_config = {"extra": "forbid"}

    @field_validator("project_name", "design_name")
    @classmethod
    def _id_nonempty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("project_name and design_name must be non-empty")
        return text

    @model_validator(mode="after")
    def _unique_params(self) -> Allowlist:
        names = [p.name for p in self.parameters]
        if len(set(names)) != len(names):
            raise ValueError("parameter names must be unique")
        if not self.parameters:
            raise ValueError("allowlist needs at least one parameter")
        return self

    def param_map(self) -> dict[str, ParameterBound]:
        return {p.name: p for p in self.parameters}

    def names(self) -> set[str]:
        return {p.name for p in self.parameters}

    def allowlist_id(self) -> str:
        return "al_" + canonical_json_hash(self.model_dump(mode="json", by_alias=True))[:16]


def _as_parameters(raw: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "name": item.get("name"),
                "unit": item.get("unit") or "mm",
                "min": item.get("min", item.get("min_value")),
                "max": item.get("max", item.get("max_value")),
            }
        )
    return out


def load_allowlist_dict(data: dict[str, Any]) -> Allowlist:
    """Accept slim allowlist, old TuneManifest 1.1, or benchmark case.json."""
    if "variables" in data and "source" in data:
        source = data.get("source") or {}
        project_path = source.get("project_path")
        project_name = Path(str(project_path)).stem if project_path else str(
            source.get("project_name") or data.get("case_id") or ""
        )
        payload = {
            "project_name": project_name,
            "design_name": source.get("design_name") or "",
            "project_path": project_path,
            "default_setup": source.get("setup"),
            "default_sweep": source.get("sweep"),
            "parameters": _as_parameters(list(data.get("variables") or [])),
        }
    elif "parameters" in data:
        setups = data.get("allowed_setups") or []
        setup0 = setups[0] if setups and isinstance(setups[0], dict) else {}
        path = data.get("project_path")
        payload = {
            "project_name": data.get("project_name") or (Path(str(path)).stem if path else ""),
            "design_name": data.get("design_name") or "",
            "project_path": path,
            "default_setup": data.get("default_setup") or setup0.get("setup"),
            "default_sweep": data.get("default_sweep") or setup0.get("sweep"),
            "parameters": _as_parameters(list(data.get("parameters") or [])),
        }
    else:
        raise ManifestError("unrecognized allowlist JSON", code="allowlist_unrecognized")
    try:
        return Allowlist.model_validate(payload)
    except Exception as exc:
        raise ManifestError(
            str(exc),
            code="allowlist_invalid",
            details={"reason": str(exc)},
        ) from exc


def load_allowlist_file(path: Path | str) -> Allowlist:
    file_path = Path(path)
    if not file_path.is_file():
        raise ManifestError(
            f"allowlist file not found: {file_path}",
            code="allowlist_missing",
            details={"path": str(file_path)},
        )
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(
            f"allowlist is not valid JSON: {exc}",
            code="allowlist_json",
            details={"path": str(file_path)},
        ) from exc
    if not isinstance(data, dict):
        raise ManifestError("allowlist JSON must be an object", code="allowlist_json")
    return load_allowlist_dict(data)


def assert_writable(allowlist: Allowlist, name: str, value: float, unit: str) -> None:
    spec = allowlist.param_map().get(name)
    if spec is None:
        raise PolicyError(
            f"variable {name!r} is not on the allowlist",
            code="variable_not_allowed",
            details={"name": name, "allowed": sorted(allowlist.names())},
        )
    if spec.unit.replace(" ", "").lower() != unit.replace(" ", "").lower():
        raise PolicyError(
            f"unit mismatch for {name}: expected {spec.unit}, got {unit}",
            code="unit_mismatch",
            details={"name": name, "expected": spec.unit, "actual": unit},
        )
    if value < spec.min_value or value > spec.max_value:
        raise PolicyError(
            f"{name}={value} outside [{spec.min_value}, {spec.max_value}] {spec.unit}",
            code="out_of_bounds",
            details={
                "name": name,
                "value": value,
                "min": spec.min_value,
                "max": spec.max_value,
                "unit": spec.unit,
            },
        )
