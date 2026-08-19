"""Shared domain models for snapshots, parameters, and analyze jobs."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import AliasChoices, BaseModel, Field, field_validator


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class ParameterValue(BaseModel):
    name: str = Field(validation_alias=AliasChoices("name", "variable"))
    value: float
    unit: str

    model_config = {"extra": "forbid", "populate_by_name": True}

    @field_validator("name", "unit")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("name and unit must be non-empty")
        return text

    @field_validator("value")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("parameter value must be a finite number (not NaN/Infinity)")
        return value


class DesignSnapshot(BaseModel):
    project_path: str
    project_name: str
    design_name: str
    revision: str
    variables: dict[str, ParameterValue] = Field(default_factory=dict)
    setups: list[str] = Field(default_factory=list)
    captured_at: str = Field(default_factory=utc_now_iso)

    model_config = {"extra": "forbid"}
