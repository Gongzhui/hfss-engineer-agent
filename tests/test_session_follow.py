"""GUI follow: sniff open projects, attach, never reopen a closed file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hfss_mcp.app import AppContext, build_allowlist_for_tests
from hfss_mcp.errors import AdapterError, PolicyError
from hfss_mcp.server import PUBLIC_TOOL_NAMES


class _DummyLive:
    def __init__(self, name: str, design: str = "HFSSDesign1") -> None:
        self.project_name = name
        self.design_name = design
        self.project_path = str(Path(rf"C:\x\{name}.aedt"))
        self.process_id = 4242

    def snapshot(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "design_name": self.design_name,
            "project_path": self.project_path,
            "process_id": self.process_id,
            "variables": {},
            "objects": ["Box1"],
            "revision": "dummy",
        }


class _DummyDiscovery:
    def to_public_dict(self) -> dict[str, Any]:
        return {"ok": True, "sessions": []}


def _rot(*names: str, active: str | None = None) -> list[dict[str, Any]]:
    chosen = active or (names[0] if names else None)
    return [
        {
            "process_id": 4242,
            "projects": [
                {
                    "project_name": name,
                    "designs": ["HFSSDesign1"],
                    "project_file": str(Path(rf"C:\x\{name}.aedt")),
                    "is_active_project": name == chosen,
                }
                for name in names
            ],
        }
    ]


def _patch_gui(monkeypatch: pytest.MonkeyPatch, rot: list[dict[str, Any]]) -> list[str]:
    attached: list[str] = []

    def fake_rot(**_kwargs: Any) -> list[dict[str, Any]]:
        return rot

    def fake_attach(**kwargs: Any) -> _DummyLive:
        name = str(kwargs.get("project_name") or "")
        attached.append(name)
        return _DummyLive(name)

    monkeypatch.setattr("hfss_mcp.app.list_rot_sessions", fake_rot)
    monkeypatch.setattr("hfss_mcp.app.attach_live", fake_attach)
    monkeypatch.setattr(
        "hfss_mcp.app.discover_running_sessions",
        lambda **_kwargs: _DummyDiscovery(),
    )
    return attached


def test_session_attach_is_public() -> None:
    assert "session_attach" in PUBLIC_TOOL_NAMES


def test_snapshot_follows_gui_without_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_gui(monkeypatch, _rot("Project6"))
    ctx = AppContext(data_dir=tmp_path / "data", use_fake=False)
    try:
        listed = ctx.session_list()
        assert listed["open_projects"] == ["Project6"]
        assert listed["active"]["project_name"] == "Project6"
        assert listed["allowlist_loaded"] is False
        snap = ctx.snapshot()
        assert snap["ok"] is True
        assert snap["bound"]["project_name"] == "Project6"
        assert snap["allowlist_loaded"] is False
        attached = ctx.session_attach(project_name="Project6")
        assert attached["bound"]["project_name"] == "Project6"
    finally:
        ctx.close()


def test_closed_allowlist_is_not_restored_or_reopened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = tmp_path / "me_dipole_77.aedt"
    old.write_bytes(b"FAKE\n")
    allowlist_path = tmp_path / "allowlist.json"
    allowlist_path.write_text(
        json.dumps(
            build_allowlist_for_tests(old).model_dump(mode="json", by_alias=True)
        ),
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "session-state.json").write_text(
        json.dumps({"allowlist_path": str(allowlist_path), "view_hidden": {}}),
        encoding="utf-8",
    )
    _patch_gui(monkeypatch, _rot("Project6"))
    ctx = AppContext(data_dir=data_dir, use_fake=False)
    try:
        listed = ctx.session_list()
        assert listed["allowlist_loaded"] is False
        snap = ctx.snapshot()
        assert snap["bound"]["project_name"] == "Project6"
        with pytest.raises(PolicyError) as ei:
            ctx.variables_set([{"name": "patch_w", "value": 11.0, "unit": "mm"}])
        assert ei.value.code == "allowlist_not_loaded"
        with pytest.raises(PolicyError) as load_err:
            ctx.allowlist_load(path=str(allowlist_path))
        assert load_err.value.code == "allowlist_project_not_open"
        with pytest.raises(AdapterError) as attach_err:
            ctx.session_attach(project_name="me_dipole_77")
        assert attach_err.value.code == "project_not_open"
    finally:
        ctx.close()


def test_session_attach_drops_mismatched_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_gui(monkeypatch, _rot("me_dipole_77", "Project6", active="Project6"))
    ctx = AppContext(data_dir=tmp_path / "data", use_fake=False)
    try:
        loaded = ctx.allowlist_load(
            allowlist=build_allowlist_for_tests(
                Path(r"C:\x\me_dipole_77.aedt")
            ).model_dump(mode="json", by_alias=True)
        )
        assert loaded["ok"] is True
        assert loaded["bound"]["project_name"] == "me_dipole_77"
        switched = ctx.session_attach(project_name="Project6")
        assert switched["bound"]["project_name"] == "Project6"
        assert switched["allowlist_dropped"] == "me_dipole_77"
        assert switched["allowlist_loaded"] is False
        snap = ctx.snapshot()
        assert snap["bound"]["project_name"] == "Project6"
        with pytest.raises(PolicyError) as ei:
            ctx.variables_set([{"name": "patch_w", "value": 11.0, "unit": "mm"}])
        assert ei.value.code == "allowlist_not_loaded"
    finally:
        ctx.close()


def test_snapshot_follows_active_when_bound_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attached = _patch_gui(monkeypatch, _rot("Project6"))
    ctx = AppContext(data_dir=tmp_path / "data", use_fake=False)
    try:
        ctx.snapshot()
        assert attached == ["Project6"]
        ctx._live = _DummyLive("me_dipole_77")
        snap = ctx.snapshot()
        assert snap["bound"]["project_name"] == "Project6"
        assert "me_dipole_77" not in attached[-1:]
    finally:
        ctx.close()
