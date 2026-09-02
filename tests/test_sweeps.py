"""LIN point counts and table expansion."""

from __future__ import annotations

import pytest

from hfss_mcp.errors import PolicyError
from hfss_mcp.sweeps import cartesian_from_axes, expand_table_rows, lin_values, linc_values


def test_lin_values_includes_stop_when_off_grid() -> None:
    # HFSS LIN 10 11 0.3 → 10, 10.3, 10.6, 10.9, 11 (stop appended)
    values = lin_values(10.0, 11.0, 0.3)
    assert values[0] == 10.0
    assert values[-1] == 11.0
    assert len(values) == 5
    assert int(round(abs(11.0 - 10.0) / 0.3)) + 1 == 4


def test_lin_values_on_grid_unchanged() -> None:
    assert lin_values(10.0, 11.0, 0.5) == [10.0, 10.5, 11.0]


def test_lin_values_step_larger_than_span() -> None:
    assert lin_values(10.0, 11.0, 5.0) == [10.0, 11.0]


def test_linc_values_includes_ends() -> None:
    values = linc_values(10.0, 12.0, 5)
    assert values[0] == 10.0
    assert values[-1] == 12.0
    assert len(values) == 5


def test_expand_table_rows_order_and_units() -> None:
    order, rows, units = expand_table_rows(
        [{"l1": 0.8, "l2": 0.9}, {"l1": 1.0, "l2": 1.1, "unit": "mm"}],
        allowed={"l1", "l2", "w"},
        units={"l1": "mm", "l2": "mm"},
    )
    assert order == ["l1", "l2"]
    assert rows == [{"l1": 0.8, "l2": 0.9}, {"l1": 1.0, "l2": 1.1}]
    assert units["l1"] == "mm"


def test_expand_table_rejects_unknown_variable() -> None:
    with pytest.raises(PolicyError) as ei:
        expand_table_rows(
            [{"secret": 1.0}],
            allowed={"l1"},
            units={"l1": "mm"},
        )
    assert ei.value.code == "variable_not_allowed"


def test_cartesian_product() -> None:
    rows = cartesian_from_axes({"a": [1.0, 2.0], "b": [3.0, 4.0]})
    assert rows == [
        {"a": 1.0, "b": 3.0},
        {"a": 1.0, "b": 4.0},
        {"a": 2.0, "b": 3.0},
        {"a": 2.0, "b": 4.0},
    ]
