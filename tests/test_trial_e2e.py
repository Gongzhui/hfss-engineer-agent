"""FakeAdapter end-to-end via the engineer-session AppContext."""

from __future__ import annotations

from pathlib import Path

import pytest

from hfss_mcp.app import AppContext, build_allowlist_for_tests
from hfss_mcp.errors import PolicyError
from hfss_mcp.ids import file_sha256


def test_fake_adapter_e2e_set_and_analyze(tmp_path: Path, project_file: Path) -> None:
    original_hash = file_sha256(project_file)
    ctx = AppContext(data_dir=tmp_path / "data", use_fake=True)
    try:
        loaded = ctx.allowlist_load(
            allowlist=build_allowlist_for_tests(project_file).model_dump(mode="json", by_alias=True)
        )
        assert loaded["ok"] is True
        snap = ctx.snapshot()
        assert snap["ok"] is True
        changed = ctx.variables_set([{"name": "patch_w", "value": 15.0, "unit": "mm"}])
        assert changed["readback"]["patch_w"]["value"] == 15.0
        assert changed["saved"] is False
        started = ctx.analyze_start(setup="Setup1")
        assert started["job"]["state"] == "completed"
        assert file_sha256(project_file) == original_hash
        assert project_file.read_bytes() == b"FAKE_SOURCE_PROJECT\n"
    finally:
        ctx.close()


def test_allowlist_reload_drops_stale_session(tmp_path: Path, project_file: Path) -> None:
    other = tmp_path / "projects" / "wlan58_witness.aedt"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_bytes(b"FAKE_OTHER\n")
    ctx = AppContext(data_dir=tmp_path / "data", use_fake=True)
    try:
        ctx.allowlist_load(
            allowlist=build_allowlist_for_tests(other).model_dump(mode="json", by_alias=True)
        )
        first = ctx.snapshot()
        assert first["snapshot"]["project_name"] == "wlan58_witness"
        ctx.allowlist_load(
            allowlist=build_allowlist_for_tests(project_file).model_dump(
                mode="json", by_alias=True
            )
        )
        assert ctx._fake is None
        second = ctx.snapshot()
        assert second["snapshot"]["project_name"] == project_file.stem
    finally:
        ctx.close()


def test_policy_blocks_out_of_bounds(app_ctx: AppContext, project_file: Path) -> None:
    app_ctx.allowlist_load(
        allowlist=build_allowlist_for_tests(project_file).model_dump(mode="json", by_alias=True)
    )
    with pytest.raises(PolicyError) as exc:
        app_ctx.variables_set([{"name": "patch_w", "value": 999.0, "unit": "mm"}])
    assert exc.value.code == "out_of_bounds"
