"""Setup CRUD via FakeAdapter + AppContext (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hfss_mcp.app import AppContext
from hfss_mcp.setup_ops import SetupConfig, merge_setup_properties, setup_schema_public


def test_merge_setup_properties_aliases_and_raw() -> None:
    props = merge_setup_properties(
        aliases={"frequency": "10GHz", "max_passes": 15},
        properties={"MaxDeltaS": 0.01, "frequency": "12GHz"},
    )
    # raw/properties applied after aliases; alias key frequency maps then overwritten
    assert props["Frequency"] == "12GHz"
    assert props["MaximumPasses"] == 15
    assert props["MaxDeltaS"] == 0.01


def test_setup_schema_public() -> None:
    schema = setup_schema_public()
    assert "HFSSDriven" in schema["setup_types"]
    assert "frequency" in schema["property_aliases"]


def test_setup_config_requires_points_for_linear_count() -> None:
    with pytest.raises(Exception):  # noqa: B017
        SetupConfig.model_validate(
            {
                "name": "S1",
                "sweep": {"start": 1.0, "stop": 2.0, "range_type": "LinearCount"},
            }
        )


def test_app_setup_crud_fake(tmp_path: Path) -> None:
    project = tmp_path / "Demo.aedt"
    project.write_text("x", encoding="utf-8")
    ctx = AppContext(
        data_dir=tmp_path / "data",
        use_fake=True,
        inline_trials=True,
        start_supervisor=False,
    )
    try:
        reg = ctx.register_manifest(
            {
                "schema_version": "1.1",
                "project_path": str(project),
                "project_name": "Demo",
                "design_name": "HFSSDesign1",
                "allowed_setups": [{"setup": "Setup1"}],
                "parameters": [{"name": "a", "unit": "mm", "min": 1.0, "max": 10.0}],
                "allowed_metrics": [
                    {
                        "name": "s11_min",
                        "kind": "s11_min_in_band",
                        "setup": "Setup1",
                        "f_min_ghz": 1.0,
                        "f_max_ghz": 5.0,
                        "port": "1",
                    }
                ],
                "stop_conditions": {
                    "max_trials": 1,
                    "max_runtime_seconds": 60.0,
                    "metric_targets": {},
                },
            }
        )
        mid = reg["manifest_id"]

        listed = ctx.setup_list(manifest_id=mid)
        assert listed["ok"] is True
        assert listed["count"] >= 1
        names = {s["name"] for s in listed["setups"]}
        assert "Setup1" in names

        created = ctx.setup_create(
            manifest_id=mid,
            config={
                "name": "Setup2",
                "setup_type": "HFSSDriven",
                "frequency": "2.4GHz",
                "max_passes": 12,
                "max_delta_s": 0.02,
                "properties": {"PercentRefinement": 30},
                "sweep": {
                    "name": "Sweep1",
                    "unit": "GHz",
                    "start": 1.0,
                    "stop": 5.0,
                    "points": 21,
                    "sweep_type": "Discrete",
                },
            },
        )
        assert created["ok"] is True
        assert created["created"]["name"] == "Setup2"
        assert created["created"]["props"]["Frequency"] == "2.4GHz"
        assert created["created"]["props"]["MaximumPasses"] == 12
        assert created["created"]["props"]["PercentRefinement"] == 30
        assert any(s["name"] == "Sweep1" for s in created["created"]["sweeps"])

        got = ctx.setup_get(manifest_id=mid, name="Setup2")
        assert got["setup"]["props"]["MaxDeltaS"] == 0.02

        updated = ctx.setup_update(
            manifest_id=mid,
            config={
                "name": "Setup2",
                "max_passes": 20,
                "properties": {"CustomFlag": True},
            },
        )
        assert updated["updated"]["props"]["MaximumPasses"] == 20
        assert updated["updated"]["props"]["CustomFlag"] is True

        sw = ctx.setup_sweep_create(
            manifest_id=mid,
            setup_name="Setup2",
            sweep={
                "name": "Sweep2",
                "start": 0.5,
                "stop": 3.0,
                "points": 11,
                "unit": "GHz",
            },
        )
        assert sw["sweep"] == "Sweep2"

        swu = ctx.setup_sweep_update(
            manifest_id=mid,
            setup_name="Setup2",
            sweep_name="Sweep2",
            properties={"points": 31, "save_fields": False},
        )
        assert swu["props"]["RangeCount"] == 31 or swu["props"].get("points") == 31

        swd = ctx.setup_sweep_delete(
            manifest_id=mid, setup_name="Setup2", sweep_name="Sweep2"
        )
        assert swd["deleted"] == "Sweep2"
        assert "Sweep2" not in swd["remaining"]

        deleted = ctx.setup_delete(manifest_id=mid, name="Setup2")
        assert deleted["deleted"] == "Setup2"
        assert "Setup2" not in deleted["remaining"]

        schema = ctx.setup_schema()
        assert schema["ok"] is True
        assert "property_aliases" in schema
    finally:
        ctx.close()


def test_setup_tools_registered() -> None:
    from hfss_mcp.server import PUBLIC_TOOL_NAMES

    for name in (
        "setup_schema",
        "setup_list",
        "setup_get",
        "setup_create",
        "setup_update",
        "setup_delete",
        "setup_sweep_create",
        "setup_sweep_update",
        "setup_sweep_delete",
    ):
        assert name in PUBLIC_TOOL_NAMES
