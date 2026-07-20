"""Shared fixtures for hfss-mcp tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from hfss_mcp.adapter.fake import FakeAdapter
from hfss_mcp.app import AppContext, build_manifest_for_tests
from hfss_mcp.domain import ParameterValue
from hfss_mcp.manifest import TuneManifest


@pytest.fixture
def project_file(tmp_path: Path) -> Path:
    path = tmp_path / "projects" / "DemoAntenna.aedt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"FAKE_SOURCE_PROJECT\n")
    return path


@pytest.fixture
def sample_manifest(project_file: Path) -> TuneManifest:
    return build_manifest_for_tests(project_file)


@pytest.fixture
def fake_adapter(project_file: Path) -> FakeAdapter:
    return FakeAdapter(
        project_path=project_file,
        project_name=project_file.stem,
        design_name="HFSSDesign1",
        variables={
            "patch_w": ParameterValue(name="patch_w", value=10.0, unit="mm"),
            "patch_l": ParameterValue(name="patch_l", value=12.0, unit="mm"),
        },
        setups=["Setup1"],
        metrics={"S11_dB": -12.0, "Gain_dBi": 6.0},
        solve_duration_s=0.02,
    )


@pytest.fixture
def app_ctx(tmp_path: Path, fake_adapter: FakeAdapter) -> AppContext:
    ctx = AppContext(
        data_dir=tmp_path / "data",
        adapter=fake_adapter,
        use_fake=True,
        inline_trials=True,
    )
    yield ctx
    ctx.close()
