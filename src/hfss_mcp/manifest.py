"""Versioned tune-only run manifest with stable canonical identity."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from hfss_mcp.errors import ManifestError
from hfss_mcp.ids import canonical_json_bytes, sha256_hex
from hfss_mcp.metrics_spec import MetricSpec, coerce_metrics

MANIFEST_SCHEMA_VERSION = "1.1"

ConcurrencyMode = Literal["serial", "parallel"]
CheckpointMode = Literal["before_first_mutation", "every_trial", "manual"]


class ParameterSpec(BaseModel):
    """One allowlisted tunable parameter."""

    name: str
    unit: str
    min_value: float = Field(alias="min")
    max_value: float = Field(alias="max")

    model_config = {"populate_by_name": True, "extra": "forbid"}

    @field_validator("name")
    @classmethod
    def _name_nonempty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("parameter name must be non-empty")
        return text

    @field_validator("unit")
    @classmethod
    def _unit_nonempty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("parameter unit must be non-empty")
        return text

    @field_validator("min_value", "max_value")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("parameter bounds must be finite numbers")
        return value

    @model_validator(mode="after")
    def _range_ok(self) -> ParameterSpec:
        if self.min_value > self.max_value:
            raise ValueError(
                f"parameter {self.name!r}: min ({self.min_value}) > max ({self.max_value})"
            )
        return self


class SetupSweepRef(BaseModel):
    """Approved setup and optional sweep."""

    setup: str
    sweep: str | None = None

    model_config = {"extra": "forbid"}

    @field_validator("setup")
    @classmethod
    def _setup_nonempty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("setup name must be non-empty")
        return text


class ConcurrencyPolicy(BaseModel):
    mode: ConcurrencyMode = "serial"
    max_concurrent: int = Field(default=1, ge=1)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _serial_implies_one(self) -> ConcurrencyPolicy:
        if self.mode == "serial" and self.max_concurrent != 1:
            raise ValueError("serial concurrency requires max_concurrent == 1")
        return self


class CheckpointPolicy(BaseModel):
    mode: CheckpointMode = "every_trial"
    directory: str | None = None

    model_config = {"extra": "forbid"}


class StopConditions(BaseModel):
    max_trials: int = Field(ge=1)
    max_runtime_seconds: float = Field(gt=0)
    # metric_name -> target (minimize: stop when metric <= target for S11)
    metric_targets: dict[str, float] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @field_validator("max_runtime_seconds")
    @classmethod
    def _finite_runtime(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("max_runtime_seconds must be finite")
        return value


class TuneManifest(BaseModel):
    """Immutable tune-only run contract."""

    schema_version: str = MANIFEST_SCHEMA_VERSION
    project_path: str
    project_name: str
    design_name: str
    allowed_setups: list[SetupSweepRef] = Field(min_length=1)
    parameters: list[ParameterSpec] = Field(min_length=1)
    allowed_metrics: list[MetricSpec] = Field(min_length=1)
    stop_conditions: StopConditions
    concurrency: ConcurrencyPolicy = Field(default_factory=ConcurrencyPolicy)
    checkpoint: CheckpointPolicy = Field(default_factory=CheckpointPolicy)
    notes: str | None = None

    model_config = {"extra": "forbid", "populate_by_name": True}

    @field_validator("schema_version")
    @classmethod
    def _schema_ok(cls, value: str) -> str:
        if value not in {MANIFEST_SCHEMA_VERSION, "1.0"}:
            raise ValueError(
                f"unsupported schema_version {value!r}; "
                f"expected {MANIFEST_SCHEMA_VERSION!r} (or legacy 1.0)"
            )
        return value

    @field_validator("project_path")
    @classmethod
    def _absolute_project(cls, value: str) -> str:
        path = Path(value)
        if not path.is_absolute():
            raise ValueError("project_path must be an absolute path")
        resolved = path.resolve(strict=False)
        if ".." in path.parts:
            raise ValueError("project_path must not contain '..' segments")
        suffix = resolved.suffix.lower()
        if suffix not in {".aedt", ".aedtz"}:
            raise ValueError("project_path must end with .aedt or .aedtz")
        return str(resolved)

    @field_validator("project_name", "design_name")
    @classmethod
    def _identity_nonempty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("project_name and design_name must be non-empty")
        return text

    @field_validator("allowed_metrics", mode="before")
    @classmethod
    def _coerce_metrics(cls, value: Any) -> list[Any]:
        return coerce_metrics(list(value))

    @model_validator(mode="after")
    def _unique_parameters_and_metric_setups(self) -> TuneManifest:
        names = [p.name for p in self.parameters]
        if len(set(names)) != len(names):
            raise ValueError("parameter names must be unique")
        allowed = self.allowed_setup_keys()
        for metric in self.allowed_metrics:
            key = (metric.setup, metric.sweep)
            # Allow setup match with explicit sweep listed or setup-only with None
            setup_ok = any(
                s.setup == metric.setup and s.sweep == metric.sweep
                for s in self.allowed_setups
            )
            if key not in allowed and (metric.setup, None) not in allowed and not setup_ok:
                raise ValueError(
                    f"metric {metric.name!r} setup/sweep not in allowed_setups"
                )
        return self

    def parameter_map(self) -> dict[str, ParameterSpec]:
        return {p.name: p for p in self.parameters}

    def metric_map(self) -> dict[str, MetricSpec]:
        return {m.name: m for m in self.allowed_metrics}

    def allowed_setup_keys(self) -> set[tuple[str, str | None]]:
        return {(item.setup, item.sweep) for item in self.allowed_setups}

    def to_canonical_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json", by_alias=True)
        data.pop("notes", None)
        return data

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_canonical_dict())

    def manifest_id(self) -> str:
        return sha256_hex(self.canonical_bytes())


def load_manifest(data: dict[str, Any] | TuneManifest) -> TuneManifest:
    if isinstance(data, TuneManifest):
        return data
    try:
        return TuneManifest.model_validate(data)
    except Exception as exc:
        raise ManifestError(
            f"manifest validation failed: {exc}",
            code="manifest_invalid",
            details={"reason": str(exc)},
        ) from exc


def load_manifest_json_file(path: Path | str) -> TuneManifest:
    import json

    file_path = Path(path)
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(
            f"cannot read manifest file: {file_path}",
            code="manifest_io_error",
            details={"path": str(file_path), "reason": str(exc)},
        ) from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(
            f"manifest JSON is invalid: {file_path}",
            code="manifest_json_error",
            details={"path": str(file_path), "reason": str(exc)},
        ) from exc
    if not isinstance(raw, dict):
        raise ManifestError(
            "manifest root must be a JSON object",
            code="manifest_invalid",
            details={"path": str(file_path)},
        )
    return load_manifest(raw)


def default_s11_metrics(
    *,
    setup: str = "Setup1",
    sweep: str | None = "Sweep1",
    f_min_ghz: float = 1.0,
    f_max_ghz: float = 10.0,
    f_target_ghz: float = 2.4,
    port: str = "1",
) -> list[dict[str, Any]]:
    """Helper metric pack for tests and demos."""
    return [
        {
            "name": "S11_min_dB",
            "kind": "s11_min_in_band",
            "setup": setup,
            "sweep": sweep,
            "port": port,
            "f_min_ghz": f_min_ghz,
            "f_max_ghz": f_max_ghz,
            "unit": "dB",
        },
        {
            "name": "S11_min_freq_GHz",
            "kind": "s11_min_freq",
            "setup": setup,
            "sweep": sweep,
            "port": port,
            "f_min_ghz": f_min_ghz,
            "f_max_ghz": f_max_ghz,
            "unit": "GHz",
        },
        {
            "name": "S11_at_target_dB",
            "kind": "s11_at_freq",
            "setup": setup,
            "sweep": sweep,
            "port": port,
            "f_target_ghz": f_target_ghz,
            "unit": "dB",
        },
    ]
