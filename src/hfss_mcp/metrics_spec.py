"""Structured, allowlisted metric specifications (no arbitrary expression exec)."""

from __future__ import annotations

import math
import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, field_validator, model_validator

# Only these expression templates are permitted (port substituted).
ALLOWED_EXPRESSION_TEMPLATES: frozenset[str] = frozenset(
    {
        "dB(S({port},{port}))",
        "dB(S({port}:1,{port}:1))",
    }
)


class MetricKind(StrEnum):
    S11_MIN_IN_BAND = "s11_min_in_band"
    S11_AT_FREQ = "s11_at_freq"
    S11_MIN_FREQ = "s11_min_freq"


class MetricSpec(BaseModel):
    """One extractable metric bound to setup/sweep and frequency context."""

    name: str
    kind: MetricKind
    setup: str
    sweep: str | None = None
    port: str = "1"
    expression_template: Literal[
        "dB(S({port},{port}))",
        "dB(S({port}:1,{port}:1))",
    ] = "dB(S({port},{port}))"
    f_min_ghz: float | None = None
    f_max_ghz: float | None = None
    f_target_ghz: float | None = None
    unit: str = "dB"

    model_config = {"extra": "forbid"}

    @field_validator("name", "setup", "port")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must be non-empty")
        return text

    @field_validator("port")
    @classmethod
    def _safe_port(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_]+", value):
            raise ValueError("port must be alphanumeric/underscore")
        return value

    @field_validator("f_min_ghz", "f_max_ghz", "f_target_ghz")
    @classmethod
    def _finite_freq(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value) or value <= 0:
            raise ValueError("frequency must be a positive finite GHz value")
        return value

    @model_validator(mode="after")
    def _kind_requirements(self) -> MetricSpec:
        if self.kind == MetricKind.S11_MIN_IN_BAND:
            if self.f_min_ghz is None or self.f_max_ghz is None:
                raise ValueError("s11_min_in_band requires f_min_ghz and f_max_ghz")
            if self.f_min_ghz > self.f_max_ghz:
                raise ValueError("f_min_ghz must be <= f_max_ghz")
            if self.unit not in {"dB", "dB(S)"}:
                raise ValueError("s11_min_in_band unit must be dB")
        elif self.kind == MetricKind.S11_AT_FREQ:
            if self.f_target_ghz is None:
                raise ValueError("s11_at_freq requires f_target_ghz")
            if self.unit not in {"dB", "dB(S)"}:
                raise ValueError("s11_at_freq unit must be dB")
        elif self.kind == MetricKind.S11_MIN_FREQ:
            if self.f_min_ghz is None or self.f_max_ghz is None:
                raise ValueError("s11_min_freq requires f_min_ghz and f_max_ghz")
            if self.unit not in {"GHz", "Hz"}:
                raise ValueError("s11_min_freq unit must be GHz or Hz")
        if self.expression_template not in ALLOWED_EXPRESSION_TEMPLATES:
            raise ValueError("expression_template is not allowlisted")
        return self

    def expression(self) -> str:
        return self.expression_template.format(port=self.port)

    def setup_sweep_name(self) -> str:
        if self.sweep:
            return f"{self.setup} : {self.sweep}"
        return self.setup


def coerce_metrics(raw: list[Any]) -> list[MetricSpec]:
    """Accept structured specs; reject bare arbitrary strings without kind."""
    if not raw:
        raise ValueError("allowed_metrics must be non-empty")
    out: list[MetricSpec] = []
    for item in raw:
        if isinstance(item, MetricSpec):
            out.append(item)
        elif isinstance(item, dict):
            out.append(MetricSpec.model_validate(item))
        elif isinstance(item, str):
            raise ValueError(
                "allowed_metrics must be structured MetricSpec objects "
                f"(got bare string {item!r})"
            )
        else:
            raise ValueError(f"invalid metric entry: {item!r}")
    names = [m.name for m in out]
    if len(set(names)) != len(names):
        raise ValueError("metric names must be unique")
    return out
