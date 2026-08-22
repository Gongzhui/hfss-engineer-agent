"""In-memory session state (allowlist, view-hide bookkeeping) must survive an
MCP host idle-restart: a fresh AppContext over the same data_dir self-heals."""

from __future__ import annotations

import json
from pathlib import Path

from hfss_mcp.app import AppContext, build_allowlist_for_tests


def _make_ctx(data_dir: Path) -> AppContext:
    return AppContext(data_dir=data_dir, use_fake=True)


def test_allowlist_and_view_hidden_survive_restart(tmp_path: Path) -> None:
    project = tmp_path / "ant.aedt"
    project.write_bytes(b"FAKE_SOURCE_PROJECT\n")
    allowlist_path = tmp_path / "allowlist.json"
    allowlist_path.write_text(
        json.dumps(
            build_allowlist_for_tests(project).model_dump(mode="json", by_alias=True)
        ),
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"

    ctx1 = _make_ctx(data_dir)
    try:
        loaded = ctx1.allowlist_load(path=str(allowlist_path))
        assert loaded["ok"] is True
        hidden = ctx1.view_hide(["AirBox", "Ground"])
        assert set(hidden["hidden"]) == {"AirBox", "Ground"}
    finally:
        ctx1.close()

    # Simulate the MCP host killing and respawning the server process.
    ctx2 = _make_ctx(data_dir)
    try:
        # No allowlist_load on the "new" server: it must self-heal.
        snap = ctx2.snapshot()
        assert snap["ok"] is True
        assert ctx2._allowlist is not None
        assert ctx2._allowlist.project_name == "ant"
        cap = ctx2.view_capture()
        assert set(cap["hidden"]) == {"AirBox", "Ground"}
        # Showing an object updates the persisted state too.
        shown = ctx2.view_show(names=["AirBox"])
        assert "AirBox" not in shown["hidden"]
    finally:
        ctx2.close()

    ctx3 = _make_ctx(data_dir)
    try:
        ctx3.snapshot()
        assert ctx3.view_capture()["hidden"] == ["Ground"]
    finally:
        ctx3.close()


def test_stale_allowlist_path_does_not_mask_allowlist_not_loaded(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    (data_dir).mkdir(parents=True, exist_ok=True)
    (data_dir / "session-state.json").write_text(
        json.dumps({"allowlist_path": str(tmp_path / "gone.json"), "view_hidden": {}}),
        encoding="utf-8",
    )
    ctx = _make_ctx(data_dir)
    try:
        try:
            ctx.snapshot()
        except Exception as exc:
            assert getattr(exc, "code", "") == "allowlist_not_loaded"
        else:  # pragma: no cover
            raise AssertionError("expected allowlist_not_loaded")
    finally:
        ctx.close()
