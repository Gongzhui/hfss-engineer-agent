"""Adapter resolution and health honesty."""

from __future__ import annotations

from pathlib import Path

from hfss_mcp.app import AppContext
from hfss_mcp.config import resolve_adapter_name


def test_resolve_explicit_fake() -> None:
    assert resolve_adapter_name(explicit="fake") == "fake"


def test_resolve_explicit_pyaedt() -> None:
    assert resolve_adapter_name(explicit="pyaedt") == "pyaedt"


def test_env_override_fake(monkeypatch) -> None:
    monkeypatch.setenv("HFSS_MCP_ADAPTER", "fake")
    assert resolve_adapter_name() == "fake"


def test_health_fake_not_real(tmp_path: Path) -> None:
    ctx = AppContext(
        data_dir=tmp_path / "d",
        use_fake=True,
        inline_trials=True,
        start_supervisor=False,
    )
    try:
        h = ctx.health()
        assert h["adapter"] == "fake"
        assert h["real_hfss_ready"] is False
        assert h["demo_mode"] is True
    finally:
        ctx.close()
