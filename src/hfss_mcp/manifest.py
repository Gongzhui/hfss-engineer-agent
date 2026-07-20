"""Versioned tune-only run manifest with stable canonical identity."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from hfss_mcp.errors import ManifestError
from hfss_mcp.ids import canonical_json_bytes, sha256_hex

MANIFEST_SCHEMA_VERSION = "1.0"

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
    mode: CheckpointMode = "before_first_mutation"
    directory: str | None = None

    model_config = {"extra": "forbid"}


class StopConditions(BaseModel):
    max_trials: int = Field(ge=1)
    max_runtime_seconds: float = Field(gt=0)
    # Optional metric thresholds reserved for later optimizer loops
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
    allowed_metrics: list[str] = Field(min_length=1)
    stop_conditions: StopConditions
    concurrency: ConcurrencyPolicy = Field(default_factory=ConcurrencyPolicy)
    checkpoint: CheckpointPolicy = Field(default_factory=CheckpointPolicy)
    notes: str | None = None

    model_config = {"extra": "forbid", "populate_by_name": True}

    @field_validator("schema_version")
    @classmethod
    def _schema_ok(cls, value: str) -> str:
        if value != MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {value!r}; expected {MANIFEST_SCHEMA_VERSION!r}"
            )
        return value

    @field_validator("project_path")
    @classmethod
    def _absolute_project(cls, value: str) -> str:
        path = Path(value)
        if not path.is_absolute():
            raise ValueError("project_path must be an absolute path")
        # Reject path traversal segments after normalization attempt
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

    @field_validator("allowed_metrics")
    @classmethod
    def _metrics_nonempty_names(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("allowed_metrics entries must be non-empty")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("allowed_metrics must be unique")
        return cleaned

    @model_validator(mode="after")
    def _unique_parameters(self) -> TuneManifest:
        names = [p.name for p in self.parameters]
        if len(set(names)) != len(names):
            raise ValueError("parameter names must be unique")
        return self

    def parameter_map(self) -> dict[str, ParameterSpec]:
        return {p.name: p for p in self.parameters}

    def allowed_setup_keys(self) -> set[tuple[str, str | None]]:
        return {(item.setup, item.sweep) for item in self.allowed_setups}

    def to_canonical_dict(self) -> dict[str, Any]:
        """Dict used for stable hashing (aliases normalized to public names)."""
        data = self.model_dump(mode="json", by_alias=True)
        # Drop notes from identity so documentation edits do not change ID? Keep notes
        # out of identity for stability of engineering contract.
        data.pop("notes", None)
        return data

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_canonical_dict())

    def manifest_id(self) -> str:
        return sha256_hex(self.canonical_bytes())


def load_manifest(data: dict[str, Any] | TuneManifest) -> TuneManifest:
    """Parse and validate a manifest dict or model."""
    if isinstance(data, TuneManifest):
        return data
    try:
        return TuneManifest.model_validate(data)
    except Exception as exc:  # pydantic ValidationError and ValueError
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
