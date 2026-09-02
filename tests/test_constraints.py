"""Allowlist constraint parser and enforcement."""

from __future__ import annotations

import pytest

from hfss_mcp.allowlist import load_allowlist_dict
from hfss_mcp.constraints import assert_constraints, assert_constraints_on_rows, eval_constraint
from hfss_mcp.errors import ManifestError, PolicyError


def test_eval_simple_inequality() -> None:
    assert eval_constraint("wp + g3 <= l1 - 0.05", {"wp": 0.4, "g3": 0.3, "l1": 0.8}) is True
    assert eval_constraint("wp + g3 <= l1 - 0.05", {"wp": 0.4, "g3": 0.4, "l1": 0.8}) is False


def test_assert_constraints_reports_values() -> None:
    with pytest.raises(PolicyError) as ei:
        assert_constraints(["a < b"], {"a": 3.0, "b": 1.0}, where="variables_set")
    assert ei.value.code == "constraint_violated"
    assert ei.value.details["constraint"] == "a < b"


def test_row_constraints_skip_unrelated_missing_names() -> None:
    assert_constraints_on_rows(
        ["wp + g3 <= l1 - 0.05", "patch_w < 100"],
        [{"patch_w": 10.0}],
        where="parametric_create",
    )


def test_infeasible_rows_list_index() -> None:
    with pytest.raises(PolicyError) as ei:
        assert_constraints_on_rows(
            ["l1 > l2"],
            [{"l1": 1.0, "l2": 0.5}, {"l1": 0.2, "l2": 0.9}],
            where="parametric_create",
        )
    assert ei.value.code == "parametric_row_infeasible"
    assert ei.value.details["count"] == 1
    assert ei.value.details["rows"][0]["index"] == 1


def test_allowlist_rejects_unknown_constraint_name() -> None:
    with pytest.raises(ManifestError):
        load_allowlist_dict(
            {
                "project_name": "x",
                "design_name": "HFSSDesign1",
                "parameters": [{"name": "l1", "unit": "mm", "min": 0.1, "max": 2.0}],
                "constraints": ["l1 < foo"],
            }
        )


def test_allowlist_accepts_constraints() -> None:
    loaded = load_allowlist_dict(
        {
            "project_name": "x",
            "design_name": "HFSSDesign1",
            "parameters": [
                {"name": "l1", "unit": "mm", "min": 0.1, "max": 2.0},
                {"name": "l2", "unit": "mm", "min": 0.1, "max": 2.0},
            ],
            "constraints": ["l1 > l2"],
        }
    )
    assert loaded.constraints == ["l1 > l2"]
