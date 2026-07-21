"""Manifest canonical hash and policy rejection tests."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from hfss_mcp.app import build_manifest_for_tests
from hfss_mcp.domain import ParameterValue, ParameterVector
from hfss_mcp.errors import ManifestError, PolicyError
from hfss_mcp.manifest import TuneManifest, load_manifest
from hfss_mcp.policy import (
    assert_manifest_identity,
    assert_setup_authorized,
    validate_parameter_vector,
    validate_trial_request,
)


def _base_manifest_dict(project: Path) -> dict:
    m = build_manifest_for_tests(project, sweep="Sweep1")
    return m.model_dump(mode="json", by_alias=True)


def test_canonical_hash_stability(tmp_path: Path) -> None:
    project = tmp_path / "p.aedt"
    project.write_text("x", encoding="utf-8")
    data = _base_manifest_dict(project)
    m1 = load_manifest(data)
    m2 = load_manifest(copy.deepcopy(data))
    assert m1.manifest_id() == m2.manifest_id()
    assert len(m1.manifest_id()) == 64

    reordered = {
        "stop_conditions": data["stop_conditions"],
        "schema_version": data["schema_version"],
        "parameters": data["parameters"],
        "project_path": data["project_path"],
        "project_name": data["project_name"],
        "design_name": data["design_name"],
        "allowed_setups": data["allowed_setups"],
        "allowed_metrics": data["allowed_metrics"],
        "concurrency": data["concurrency"],
        "checkpoint": data["checkpoint"],
    }
    m3 = load_manifest(reordered)
    assert m3.manifest_id() == m1.manifest_id()

    with_notes = copy.deepcopy(data)
    with_notes["notes"] = "documentation only"
    m4 = load_manifest(with_notes)
    assert m4.manifest_id() == m1.manifest_id()


def test_reject_relative_path(tmp_path: Path) -> None:
    data = _base_manifest_dict(tmp_path / "p.aedt")
    data["project_path"] = "relative/project.aedt"
    with pytest.raises(ManifestError):
        load_manifest(data)


def test_reject_non_aedt_extension(tmp_path: Path) -> None:
    path = tmp_path / "model.hfss"
    data = _base_manifest_dict(tmp_path / "p.aedt")
    data["project_path"] = str(path.resolve())
    with pytest.raises(ManifestError):
        load_manifest(data)


def test_unknown_parameter(tmp_path: Path) -> None:
    project = tmp_path / "p.aedt"
    project.write_text("x", encoding="utf-8")
    manifest = load_manifest(_base_manifest_dict(project))
    vector = ParameterVector(
        values=[
            ParameterValue(name="patch_w", value=5.0, unit="mm"),
            ParameterValue(name="patch_l", value=5.0, unit="mm"),
            ParameterValue(name="evil", value=1.0, unit="mm"),
        ]
    )
    with pytest.raises(PolicyError) as exc:
        validate_parameter_vector(manifest, vector)
    assert exc.value.code == "unknown_parameter"


def test_missing_parameter(tmp_path: Path) -> None:
    project = tmp_path / "p.aedt"
    project.write_text("x", encoding="utf-8")
    manifest = load_manifest(_base_manifest_dict(project))
    vector = ParameterVector(
        values=[ParameterValue(name="patch_w", value=5.0, unit="mm")]
    )
    with pytest.raises(PolicyError) as exc:
        validate_parameter_vector(manifest, vector)
    assert exc.value.code == "missing_parameter"


def test_unit_mismatch(tmp_path: Path) -> None:
    project = tmp_path / "p.aedt"
    project.write_text("x", encoding="utf-8")
    manifest = load_manifest(_base_manifest_dict(project))
    vector = ParameterVector(
        values=[
            ParameterValue(name="patch_w", value=5.0, unit="cm"),
            ParameterValue(name="patch_l", value=5.0, unit="mm"),
        ]
    )
    with pytest.raises(PolicyError) as exc:
        validate_parameter_vector(manifest, vector)
    assert exc.value.code == "unit_mismatch"


def test_out_of_range(tmp_path: Path) -> None:
    project = tmp_path / "p.aedt"
    project.write_text("x", encoding="utf-8")
    manifest = load_manifest(_base_manifest_dict(project))
    vector = ParameterVector(
        values=[
            ParameterValue(name="patch_w", value=99.0, unit="mm"),
            ParameterValue(name="patch_l", value=5.0, unit="mm"),
        ]
    )
    with pytest.raises(PolicyError) as exc:
        validate_parameter_vector(manifest, vector)
    assert exc.value.code == "out_of_range"


def test_nan_rejected_at_vector_model() -> None:
    with pytest.raises(ValueError):
        ParameterValue(name="patch_w", value=float("nan"), unit="mm")


def test_inf_rejected_at_vector_model() -> None:
    with pytest.raises(ValueError):
        ParameterValue(name="patch_w", value=float("inf"), unit="mm")


def test_nan_policy_path(tmp_path: Path) -> None:
    project = tmp_path / "p.aedt"
    project.write_text("x", encoding="utf-8")
    manifest = load_manifest(_base_manifest_dict(project))
    bad = ParameterValue.model_construct(name="patch_w", value=float("nan"), unit="mm")
    good = ParameterValue(name="patch_l", value=5.0, unit="mm")
    vector = ParameterVector.model_construct(values=[bad, good])
    with pytest.raises(PolicyError) as exc:
        validate_parameter_vector(manifest, vector)
    assert exc.value.code == "non_finite_value"


def test_unauthorized_setup(tmp_path: Path) -> None:
    project = tmp_path / "p.aedt"
    project.write_text("x", encoding="utf-8")
    manifest = load_manifest(_base_manifest_dict(project))
    with pytest.raises(PolicyError) as exc:
        assert_setup_authorized(manifest, "Setup9", None)
    assert exc.value.code == "unauthorized_setup"


def test_manifest_identity_mismatch(tmp_path: Path) -> None:
    project = tmp_path / "p.aedt"
    project.write_text("x", encoding="utf-8")
    manifest = load_manifest(_base_manifest_dict(project))
    with pytest.raises(PolicyError) as exc:
        assert_manifest_identity(manifest, "0" * 64)
    assert exc.value.code == "manifest_identity_mismatch"


def test_validate_trial_happy_path(tmp_path: Path) -> None:
    project = tmp_path / "p.aedt"
    project.write_text("x", encoding="utf-8")
    manifest = load_manifest(_base_manifest_dict(project))
    vector = ParameterVector(
        values=[
            ParameterValue(name="patch_w", value=5.0, unit="mm"),
            ParameterValue(name="patch_l", value=6.0, unit="mm"),
        ]
    )
    out = validate_trial_request(
        manifest,
        manifest_id=manifest.manifest_id(),
        setup="Setup1",
        sweep="Sweep1",
        parameters=vector,
    )
    assert out.names() == {"patch_w", "patch_l"}


def test_aedtz_allowed(tmp_path: Path) -> None:
    project = tmp_path / "pack.aedtz"
    data = _base_manifest_dict(tmp_path / "p.aedt")
    data["project_path"] = str(project.resolve())
    m = load_manifest(data)
    assert isinstance(m, TuneManifest)


def test_bare_string_metrics_rejected(tmp_path: Path) -> None:
    project = tmp_path / "p.aedt"
    project.write_text("x", encoding="utf-8")
    data = _base_manifest_dict(project)
    data["allowed_metrics"] = ["S11_dB"]
    with pytest.raises(ManifestError):
        load_manifest(data)
