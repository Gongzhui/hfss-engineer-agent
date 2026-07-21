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
    return build_manifest_for_tests(project_file, sweep=None)


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
        metrics={
            "S11_min_dB": -12.0,
            "S11_min_freq_GHz": 2.4,
            "S11_at_target_dB": -10.0,
        },
        solve_duration_s=0.02,
    )


@pytest.fixture
def app_ctx(tmp_path: Path) -> AppContext:
    ctx = AppContext(
        data_dir=tmp_path / "data",
        use_fake=True,
        inline_trials=True,
        start_supervisor=True,
    )
    yield ctx
    ctx.close()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "real_aedt: requires local AEDT 2023 R2 session")
