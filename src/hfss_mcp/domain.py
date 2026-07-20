"""Shared domain models for snapshots, candidates, jobs, and metrics."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


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


TERMINAL_JOB_STATES = frozenset(
    {
        JobState.COMPLETED,
        JobState.FAILED,
        JobState.CANCELLED,
        JobState.INTERRUPTED,
    }
)


class ParameterValue(BaseModel):
    name: str
    value: float
    unit: str

    model_config = {"extra": "forbid"}

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


class ParameterVector(BaseModel):
    """Complete parameter vector for a trial (no partial/hidden state)."""

    values: list[ParameterValue] = Field(min_length=1)

    model_config = {"extra": "forbid"}

    def as_map(self) -> dict[str, ParameterValue]:
        return {item.name: item for item in self.values}

    def names(self) -> set[str]:
        return {item.name for item in self.values}

    @model_validator(mode="after")
    def _unique(self) -> ParameterVector:
        names = [v.name for v in self.values]
        if len(set(names)) != len(names):
            raise ValueError("parameter vector names must be unique")
        return self


class DesignSnapshot(BaseModel):
    project_path: str
    project_name: str
    design_name: str
    revision: str
    variables: dict[str, ParameterValue] = Field(default_factory=dict)
    setups: list[str] = Field(default_factory=list)
    captured_at: str = Field(default_factory=utc_now_iso)

    model_config = {"extra": "forbid"}


class ParameterDiffItem(BaseModel):
    name: str
    before_value: float | None
    after_value: float | None
    unit: str
    changed: bool


class ApplyResult(BaseModel):
    ok: bool
    revision_before: str
    revision_after: str
    diff: list[ParameterDiffItem]
    readback: dict[str, ParameterValue]


class SolveState(StrEnum):
    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class SolveHandle(BaseModel):
    handle_id: str
    setup: str
    sweep: str | None = None
    started_at: str = Field(default_factory=utc_now_iso)


class SolveStatus(BaseModel):
    handle_id: str
    state: SolveState
    progress: float | None = None
    message: str | None = None
    cancel_supported: bool = True
    cancel_limitation: str | None = None


class CancelResult(BaseModel):
    handle_id: str
    state: SolveState
    cancelled: bool
    message: str
    honest_limitation: str | None = None


class CheckpointRecord(BaseModel):
    checkpoint_id: str
    original_project_path: str
    checkpoint_path: str
    sha256: str
    created_at: str = Field(default_factory=utc_now_iso)
    manifest_id: str
    run_id: str
    trial_id: str | None = None
    notes: str | None = None

    model_config = {"extra": "forbid"}


class TrialRequest(BaseModel):
    """Inputs required to start one tune trial."""

    manifest_id: str
    run_id: str
    trial_id: str
    idempotency_key: str
    setup: str
    sweep: str | None = None
    parameters: ParameterVector
    expected_revision: str | None = None

    model_config = {"extra": "forbid"}


class TrialResult(BaseModel):
    trial_id: str
    run_id: str
    manifest_id: str
    job_id: str
    state: JobState
    parameters: ParameterVector
    metrics: dict[str, float] = Field(default_factory=dict)
    apply_diff: list[ParameterDiffItem] = Field(default_factory=list)
    checkpoint: CheckpointRecord | None = None
    revision_before: str | None = None
    revision_after: str | None = None
    error: dict[str, Any] | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None

    model_config = {"extra": "forbid"}


class JobRecord(BaseModel):
    job_id: str
    idempotency_key: str
    kind: str = "trial"
    state: JobState
    run_id: str
    trial_id: str
    manifest_id: str
    input_payload: dict[str, Any]
    result_payload: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    artifact_paths: dict[str, str] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}
