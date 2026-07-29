"""Benchmark case format (``case.json``) — load, validate, derive paths, perturb.

A case is a directory ``benchmark/cases/<case_id>/`` whose only hand-written
file is ``case.json``. Adding a new case never requires code changes:
write ``case.json``, then run ``build_case.py`` / ``verify_case.py`` / ``run_case.py``.

Perturbation contract (deterministic, shared by build and verify):
for each whitelisted variable **in case.json order**,
``pct ~ U(min_pct, max_pct)``, ``sign ~ {-1, +1}`` drawn from
``random.Random(seed)``, ``value = round(nominal * (1 + sign*pct/100), 4)``.
The perturbed value must stay inside the variable's [min, max] range.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

BENCHMARK_ROOT = Path(__file__).resolve().parent
CASES_ROOT = BENCHMARK_ROOT / "cases"

_NUM_UNIT_RE = re.compile(r"^\s*([-+0-9.eE]+)\s*([a-zA-Z]*)\s*$")
# NOTE: AEDT ≥2023 saves extra oa()/sa()/ta() tuning metadata after the value,
# so the value group must not require a closing paren right after it.
_VARPROP_RE = re.compile(r"VariableProp\('([^']+)', '[^']*', '[^']*', '([^']*)'")


class WhitelistVar(BaseModel):
    """One tunable variable: name, unit, allowed tuning range."""

    name: str
    unit: str
    min: float
    max: float

    model_config = {"extra": "forbid"}

    @field_validator("name", "unit")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("variable name/unit must be non-empty")
        return v.strip()

    @model_validator(mode="after")
    def _range_ok(self) -> WhitelistVar:
        if not self.min < self.max:
            raise ValueError(f"variable {self.name!r}: min must be < max")
        return self


class SourceSpec(BaseModel):
    """Where the raw (leaky) project lives and which design is tuned."""

    project_path: str
    design_name: str
    setup: str
    sweep: str
    port: str = "1"
    sibling_designs: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class PerturbationSpec(BaseModel):
    """Deterministic perturbation applied to whitelisted variables only."""

    seed: int = 42
    min_pct: float = 10.0
    max_pct: float = 30.0

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _pct_ok(self) -> PerturbationSpec:
        if not 0.0 < self.min_pct <= self.max_pct:
            raise ValueError("perturbation requires 0 < min_pct <= max_pct")
        return self


class CaseMetrics(BaseModel):
    """Target metrics; every threshold is a '<=' bound (S11 dB: lower is better)."""

    band_ghz: tuple[float, float]
    target_ghz: float
    primary: str = "S11_at_target_dB"
    thresholds: dict[str, float] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _band_ok(self) -> CaseMetrics:
        if not self.band_ghz[0] < self.band_ghz[1]:
            raise ValueError("metrics.band_ghz must be [f_min, f_max] with f_min < f_max")
        lo, hi = self.band_ghz
        if not lo <= self.target_ghz <= hi:
            raise ValueError("metrics.target_ghz must lie inside band_ghz")
        return self


class BudgetSpec(BaseModel):
    max_trials: int = Field(default=6, ge=1)
    max_runtime_seconds: float = Field(default=3600.0, gt=0)

    model_config = {"extra": "forbid"}


class Case(BaseModel):
    case_id: str
    version: int = 1
    description: str = ""
    source: SourceSpec
    variables: list[WhitelistVar] = Field(min_length=1)
    perturbation: PerturbationSpec = Field(default_factory=PerturbationSpec)
    metrics: CaseMetrics
    budget: BudgetSpec = Field(default_factory=BudgetSpec)

    model_config = {"extra": "forbid"}

    @field_validator("case_id")
    @classmethod
    def _id_ok(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9_]+", v):
            raise ValueError("case_id must match [a-z0-9_]+")
        return v

    @model_validator(mode="after")
    def _vars_unique(self) -> Case:
        names = [v.name for v in self.variables]
        if len(set(names)) != len(names):
            raise ValueError("whitelist variable names must be unique")
        return self

    # --- derived paths -------------------------------------------------
    @property
    def case_dir(self) -> Path:
        return CASES_ROOT / self.case_id

    @property
    def case_json_path(self) -> Path:
        return self.case_dir / "case.json"

    @property
    def answer_dir(self) -> Path:
        return self.case_dir / "answer"

    @property
    def sandbox_dir(self) -> Path:
        return self.case_dir / "sandbox"

    @property
    def build_dir(self) -> Path:
        return self.case_dir / "build"

    @property
    def runs_dir(self) -> Path:
        return self.case_dir / "runs"

    @property
    def manifest_path(self) -> Path:
        return self.case_dir / "manifest.json"

    @property
    def sandbox_project(self) -> Path:
        return self.sandbox_dir / f"{self.case_id}_sandbox.aedt"

    @property
    def sandbox_project_name(self) -> str:
        return self.sandbox_project.stem


def load_case(case_id: str) -> Case:
    """Load and validate ``benchmark/cases/<case_id>/case.json``."""
    path = CASES_ROOT / case_id / "case.json"
    if not path.is_file():
        raise FileNotFoundError(f"case.json not found: {path}")
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    case = Case.model_validate(raw)
    if case.case_id != case_id:
        raise ValueError(f"case_id mismatch: file says {case.case_id!r}, dir says {case_id!r}")
    return case


def parse_value_unit(text: str) -> tuple[float, str]:
    """'15.65mm' -> (15.65, 'mm'). Raises ValueError on non-literal input."""
    m = _NUM_UNIT_RE.match(text)
    if not m:
        raise ValueError(f"not a literal value-with-unit: {text!r}")
    return float(m.group(1)), m.group(2)


def compute_perturbation(case: Case, nominal: dict[str, float]) -> dict[str, float]:
    """Deterministic perturbed values for whitelisted vars (see module docstring)."""
    rng = random.Random(case.perturbation.seed)
    lo, hi = case.perturbation.min_pct, case.perturbation.max_pct
    out: dict[str, float] = {}
    for var in case.variables:
        pct = rng.uniform(lo, hi)
        sign = rng.choice([-1.0, 1.0])
        value = round(nominal[var.name] * (1.0 + sign * pct / 100.0), 4)
        if not var.min <= value <= var.max:
            raise ValueError(
                f"perturbed {var.name}={value}{var.unit} outside [{var.min}, {var.max}]"
            )
        out[var.name] = value
    return out


def read_design_variables(aedt_path: Path, design_name: str) -> dict[str, tuple[str, str]]:
    """Parse literal design variables of one design straight from .aedt text.

    Returns ``{name: (value, unit)}`` for variables whose expression is a plain
    number+unit literal; formula variables (e.g. '2*fy+vd') are skipped.
    """
    text = aedt_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    # locate the HFSSModel block whose Name matches
    start = None
    depth = 0
    for i, line in enumerate(lines):
        if "$begin 'HFSSModel'" in line:
            depth = 1
            # Name='...' appears a couple of lines below $begin
            for j in range(i + 1, min(i + 8, len(lines))):
                if f"Name='{design_name}'" in lines[j]:
                    start = i
                if "$begin" in lines[j]:
                    break
            if start is not None:
                break
    if start is None:
        raise ValueError(f"design {design_name!r} not found in {aedt_path}")
    out: dict[str, tuple[str, str]] = {}
    for line in lines[start + 1 :]:
        # count occurrences: a line may hold both tokens (e.g. "$begin_cdata$ $end_cdata$")
        depth += line.count("$begin")
        depth -= line.count("$end")
        if depth == 0:
            break
        m = _VARPROP_RE.search(line)
        if m:
            name, expr = m.group(1), m.group(2)
            try:
                value, unit = parse_value_unit(expr)
            except ValueError:
                continue  # formula variable — not a literal
            out[name] = (format(value, ".10g"), unit)
    return out


def nominal_map(case: Case) -> dict[str, float]:
    """Nominal values of whitelisted vars, parsed from the source project text."""
    src = Path(case.source.project_path)
    variables = read_design_variables(src, case.source.design_name)
    out: dict[str, float] = {}
    for var in case.variables:
        if var.name not in variables:
            raise ValueError(
                f"whitelisted variable {var.name!r} not a literal in source design"
            )
        value, unit = variables[var.name]
        if unit != var.unit:
            raise ValueError(
                f"{var.name}: unit mismatch source={unit!r} case={var.unit!r}"
            )
        out[var.name] = float(value)
    return out
