"""Shared fixtures for hfss-mcp tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from hfss_mcp.app import AppContext


@pytest.fixture
def project_file(tmp_path: Path) -> Path:
    path = tmp_path / "projects" / "DemoAntenna.aedt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"FAKE_SOURCE_PROJECT\n")
    return path


@pytest.fixture
def app_ctx(tmp_path: Path) -> AppContext:
    ctx = AppContext(
        data_dir=tmp_path / "data",
        use_fake=True,
    )
    yield ctx
    ctx.close()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "real_aedt: requires local AEDT 2023 R2 session")
