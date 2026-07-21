"""HFSS solution-setup schemas and property mapping.

Supports:
- Convenience aliases (frequency, max_passes, …)
- Arbitrary native AEDT property keys via ``properties``
- Frequency sweeps (LinearCount / LinearStep / LogScale-ish)
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from hfss_mcp.errors import PolicyError

# Common HFSS Driven convenience → native props key
SETUP_PROP_ALIASES: dict[str, str] = {
    "frequency": "Frequency",
    "max_delta_s": "MaxDeltaS",
    "max_delta": "MaxDeltaS",
    "maximum_passes": "MaximumPasses",
    "max_passes": "MaximumPasses",
    "minimum_passes": "MinimumPasses",
    "min_passes": "MinimumPasses",
    "minimum_converged_passes": "MinimumConvergedPasses",
    "min_converged_passes": "MinimumConvergedPasses",
    "percent_refinement": "PercentRefinement",
    "basis_order": "BasisOrder",
    "do_lambda_refine": "DoLambdaRefine",
    "do_material_lambda": "DoMaterialLambda",
    "lambda_target": "LambdaTarget",
    "port_accuracy": "PortAccuracy",
    "use_matrix_conv": "UseMatrixConv",
    "use_iterative_solver": "UseIterativeSolver",
    "enabled": "Enabled",
    "solve_type": "SolveType",
    "is_enabled": "IsEnabled",
}

SETUP_TYPES = (
    "HFSSDriven",
    "HFSSDrivenAuto",
    "HFSSEigen",
    "HFSSTransient",
    "HFSSSBR",
)

SWEEP_TYPES = ("Discrete", "Interpolating", "Fast")
RANGE_TYPES = ("LinearCount", "LinearStep", "SinglePoint", "LogScale")


def json_safe(value: Any) -> Any:
    """Make setup props JSON-serializable."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    # SetupProps / nested AEDT objects
    try:
        if hasattr(value, "items"):
            return {str(k): json_safe(v) for k, v in value.items()}  # type: ignore[arg-type]
    except Exception:
        pass
    return str(value)


def merge_setup_properties(
    *,
    properties: dict[str, Any] | None = None,
    aliases: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge convenience aliases + raw properties (raw wins on key clash after alias map)."""
    out: dict[str, Any] = {}
    for key, val in (aliases or {}).items():
        if val is None:
            continue
        native = SETUP_PROP_ALIASES.get(key, key)
        out[native] = val
    for key, val in (properties or {}).items():
        if val is None:
            continue
        # allow either native or alias in properties dict
        native = SETUP_PROP_ALIASES.get(str(key), str(key))
        out[native] = val
    return out


class SweepConfig(BaseModel):
    """Frequency sweep configuration."""

    name: str | None = None
    unit: str = "GHz"
    start: float | str | None = None
    stop: float | str | None = None
    points: int | None = Field(default=None, ge=1)
    step: float | str | None = None
    range_type: Literal["LinearCount", "LinearStep", "SinglePoint", "LogScale"] = "LinearCount"
    sweep_type: Literal["Discrete", "Interpolating", "Fast"] = "Discrete"
    save_fields: bool = True
    save_rad_fields: bool = False
    interpolation_tol: float = 0.5
    interpolation_max_solutions: int = 250
    # Arbitrary native sweep props (merged after convenience fields)
    properties: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _range_ok(self) -> SweepConfig:
        if self.range_type == "LinearCount" and self.start is not None and self.stop is not None:
            if self.points is None and "RangeCount" not in self.properties:
                raise ValueError("LinearCount sweep requires points (or properties.RangeCount)")
        if self.range_type == "LinearStep" and self.start is not None and self.stop is not None:
            if self.step is None and "RangeStep" not in self.properties:
                raise ValueError("LinearStep sweep requires step (or properties.RangeStep)")
        return self


class SetupConfig(BaseModel):
    """Create/update setup body."""

    name: str
    setup_type: str | None = None
    # Convenience aliases (HFSS Driven common)
    frequency: str | float | None = None
    max_delta_s: float | None = None
    max_passes: int | None = None
    minimum_passes: int | None = None
    minimum_converged_passes: int | None = None
    percent_refinement: float | None = None
    basis_order: int | None = None
    do_lambda_refine: bool | None = None
    do_material_lambda: bool | None = None
    lambda_target: float | None = None
    port_accuracy: float | None = None
    use_matrix_conv: bool | None = None
    use_iterative_solver: bool | None = None
    # Full native property bag (any AEDT setup key)
    properties: dict[str, Any] = Field(default_factory=dict)
    # Optional sweeps on create
    sweeps: list[SweepConfig] = Field(default_factory=list)
    sweep: SweepConfig | None = None  # singular convenience

    model_config = {"extra": "forbid"}

    @field_validator("name")
    @classmethod
    def _name_ok(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("setup name must be non-empty")
        return text

    @field_validator("setup_type")
    @classmethod
    def _type_ok(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        return text

    def alias_fields(self) -> dict[str, Any]:
        return {
            "frequency": self.frequency,
            "max_delta_s": self.max_delta_s,
            "max_passes": self.max_passes,
            "minimum_passes": self.minimum_passes,
            "minimum_converged_passes": self.minimum_converged_passes,
            "percent_refinement": self.percent_refinement,
            "basis_order": self.basis_order,
            "do_lambda_refine": self.do_lambda_refine,
            "do_material_lambda": self.do_material_lambda,
            "lambda_target": self.lambda_target,
            "port_accuracy": self.port_accuracy,
            "use_matrix_conv": self.use_matrix_conv,
            "use_iterative_solver": self.use_iterative_solver,
        }

    def merged_properties(self) -> dict[str, Any]:
        return merge_setup_properties(
            properties=self.properties,
            aliases=self.alias_fields(),
        )

    def all_sweeps(self) -> list[SweepConfig]:
        items = list(self.sweeps)
        if self.sweep is not None:
            items.append(self.sweep)
        return items


class SetupUpdateConfig(BaseModel):
    """Partial update for an existing setup (name required)."""

    name: str
    frequency: str | float | None = None
    max_delta_s: float | None = None
    max_passes: int | None = None
    minimum_passes: int | None = None
    minimum_converged_passes: int | None = None
    percent_refinement: float | None = None
    basis_order: int | None = None
    do_lambda_refine: bool | None = None
    do_material_lambda: bool | None = None
    lambda_target: float | None = None
    port_accuracy: float | None = None
    use_matrix_conv: bool | None = None
    use_iterative_solver: bool | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    # rename setup
    new_name: str | None = None

    model_config = {"extra": "forbid"}

    def alias_fields(self) -> dict[str, Any]:
        return {
            "frequency": self.frequency,
            "max_delta_s": self.max_delta_s,
            "max_passes": self.max_passes,
            "minimum_passes": self.minimum_passes,
            "minimum_converged_passes": self.minimum_converged_passes,
            "percent_refinement": self.percent_refinement,
            "basis_order": self.basis_order,
            "do_lambda_refine": self.do_lambda_refine,
            "do_material_lambda": self.do_material_lambda,
            "lambda_target": self.lambda_target,
            "port_accuracy": self.port_accuracy,
            "use_matrix_conv": self.use_matrix_conv,
            "use_iterative_solver": self.use_iterative_solver,
        }

    def merged_properties(self) -> dict[str, Any]:
        props = merge_setup_properties(
            properties=self.properties,
            aliases=self.alias_fields(),
        )
        if self.new_name:
            props["Name"] = self.new_name
        return props


def setup_schema_public() -> dict[str, Any]:
    """Document available keys for agents."""
    return {
        "setup_types": list(SETUP_TYPES),
        "sweep_types": list(SWEEP_TYPES),
        "range_types": list(RANGE_TYPES),
        "property_aliases": dict(SETUP_PROP_ALIASES),
        "notes": [
            "Pass any native AEDT setup key under properties={...}; aliases are optional shortcuts.",
            "Common Driven keys: Frequency, MaximumPasses, MaxDeltaS, MinimumPasses, "
            "MinimumConvergedPasses, PercentRefinement, BasisOrder, DoLambdaRefine, LambdaTarget.",
            "Sweeps: use setup_sweep_create / setup_sweep_update or nested sweeps on setup_create.",
            "After changing setups used by trials, re-register manifest allowed_setups if needed.",
        ],
    }


def validate_setup_name(name: str) -> str:
    text = str(name or "").strip()
    if not text:
        raise PolicyError("setup name is required", code="setup_name_required")
    return text
