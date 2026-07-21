"""Server-side policy: authorize candidates against an immutable manifest."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from hfss_mcp.domain import ParameterValue, ParameterVector
from hfss_mcp.errors import ManifestError, PolicyError
from hfss_mcp.manifest import TuneManifest, load_manifest


def assert_safe_project_path(path: str | Path) -> Path:
    """Require absolute .aedt/.aedtz path without '..' traversal."""
    p = Path(path)
    if not p.is_absolute():
        raise PolicyError(
            "project path must be absolute",
            code="unsafe_project_path",
            details={"path": str(path)},
        )
    if ".." in p.parts:
        raise PolicyError(
            "project path must not contain '..' segments",
            code="unsafe_project_path",
            details={"path": str(path)},
        )
    suffix = p.suffix.lower()
    if suffix not in {".aedt", ".aedtz"}:
        raise PolicyError(
            "project path must be a .aedt or .aedtz file",
            code="invalid_project_extension",
            details={"path": str(path), "suffix": suffix},
        )
    return p.resolve(strict=False)


def validate_manifest_dict(data: dict[str, Any]) -> TuneManifest:
    """Load manifest and re-check path safety at the policy layer."""
    manifest = load_manifest(data)
    assert_safe_project_path(manifest.project_path)
    return manifest


def assert_manifest_identity(manifest: TuneManifest, expected_manifest_id: str) -> None:
    actual = manifest.manifest_id()
    if actual != expected_manifest_id:
        raise PolicyError(
            "manifest identity mismatch",
            code="manifest_identity_mismatch",
            details={"expected": expected_manifest_id, "actual": actual},
        )


def assert_setup_authorized(
    manifest: TuneManifest,
    setup: str,
    sweep: str | None,
) -> None:
    key = (setup, sweep)
    if key not in manifest.allowed_setup_keys():
        # Also allow exact setup with sweep=None only if listed that way
        raise PolicyError(
            "setup/sweep is not authorized by the manifest",
            code="unauthorized_setup",
            details={
                "setup": setup,
                "sweep": sweep,
                "allowed": [
                    {"setup": s.setup, "sweep": s.sweep} for s in manifest.allowed_setups
                ],
            },
        )


def assert_metrics_authorized(manifest: TuneManifest, metrics: list[str]) -> None:
    allowed = set(manifest.metric_map().keys())
    unknown = [m for m in metrics if m not in allowed]
    if unknown:
        raise PolicyError(
            "one or more metrics are not authorized",
            code="unauthorized_metric",
            details={"unknown": unknown, "allowed": sorted(allowed)},
        )


def _reject_non_finite(name: str, value: float) -> None:
    if math.isnan(value):
        raise PolicyError(
            f"parameter {name!r} value is NaN",
            code="non_finite_value",
            details={"name": name, "value": "NaN"},
        )
    if math.isinf(value):
        raise PolicyError(
            f"parameter {name!r} value is Infinity",
            code="non_finite_value",
            details={"name": name, "value": "Infinity" if value > 0 else "-Infinity"},
        )


def validate_parameter_vector(
    manifest: TuneManifest,
    vector: ParameterVector | dict[str, Any],
) -> ParameterVector:
    """Validate a complete candidate vector against the allowlist.

    Rejects: unknown vars, missing vars, unit mismatch, NaN/Inf, out-of-range.
    """
    if isinstance(vector, dict):
        try:
            vector = ParameterVector.model_validate(vector)
        except Exception as exc:
            # Surface NaN etc. from pydantic as policy errors when possible
            raise PolicyError(
                f"invalid parameter vector: {exc}",
                code="invalid_parameter_vector",
                details={"reason": str(exc)},
            ) from exc

    specs = manifest.parameter_map()
    required = set(specs.keys())
    provided = vector.names()

    unknown = sorted(provided - required)
    missing = sorted(required - provided)
    if unknown:
        raise PolicyError(
            "unknown parameters are not authorized",
            code="unknown_parameter",
            details={"unknown": unknown, "allowed": sorted(required)},
        )
    if missing:
        raise PolicyError(
            "parameter vector is incomplete; all allowlisted parameters are required",
            code="missing_parameter",
            details={"missing": missing, "required": sorted(required)},
        )

    for item in vector.values:
        _reject_non_finite(item.name, item.value)
        spec = specs[item.name]
        if item.unit != spec.unit:
            raise PolicyError(
                f"unit mismatch for parameter {item.name!r}",
                code="unit_mismatch",
                details={
                    "name": item.name,
                    "provided_unit": item.unit,
                    "expected_unit": spec.unit,
                },
            )
        if item.value < spec.min_value or item.value > spec.max_value:
            raise PolicyError(
                f"parameter {item.name!r} is out of allowed range",
                code="out_of_range",
                details={
                    "name": item.name,
                    "value": item.value,
                    "min": spec.min_value,
                    "max": spec.max_value,
                    "unit": spec.unit,
                },
            )
    return vector


def validate_trial_request(
    manifest: TuneManifest,
    *,
    manifest_id: str,
    setup: str,
    sweep: str | None,
    parameters: ParameterVector | dict[str, Any],
) -> ParameterVector:
    """Full pre-mutation authorization for a trial."""
    assert_manifest_identity(manifest, manifest_id)
    assert_safe_project_path(manifest.project_path)
    assert_setup_authorized(manifest, setup, sweep)
    return validate_parameter_vector(manifest, parameters)


def parameter_value_dict(values: dict[str, ParameterValue]) -> dict[str, dict[str, Any]]:
    return {k: v.model_dump(mode="json") for k, v in values.items()}


def explain_manifest(manifest: TuneManifest) -> dict[str, Any]:
    """Structured summary for the validate tool."""
    return {
        "ok": True,
        "manifest_id": manifest.manifest_id(),
        "schema_version": manifest.schema_version,
        "project_path": manifest.project_path,
        "project_name": manifest.project_name,
        "design_name": manifest.design_name,
        "parameter_count": len(manifest.parameters),
        "parameters": [
            {
                "name": p.name,
                "unit": p.unit,
                "min": p.min_value,
                "max": p.max_value,
            }
            for p in manifest.parameters
        ],
        "allowed_setups": [
            {"setup": s.setup, "sweep": s.sweep} for s in manifest.allowed_setups
        ],
        "allowed_metrics": [m.model_dump(mode="json") for m in manifest.allowed_metrics],
        "stop_conditions": manifest.stop_conditions.model_dump(mode="json"),
        "concurrency": manifest.concurrency.model_dump(mode="json"),
        "checkpoint": manifest.checkpoint.model_dump(mode="json"),
    }


def policy_error_result(exc: PolicyError | ManifestError) -> dict[str, Any]:
    return exc.to_dict()
