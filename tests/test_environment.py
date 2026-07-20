"""AEDT environment discovery tests."""

from __future__ import annotations

from pathlib import Path

from hfss_mcp.environment import (
    discover_aedt_installations,
    inspect_environment,
    version_label_from_code,
)
from hfss_mcp.server import discover_aedt_installations as legacy_discover


def test_discover_aedt_installations_legacy_shape(tmp_path: Path) -> None:
    (tmp_path / "AnsysEM" / "v232").mkdir(parents=True)
    (tmp_path / "AnsysEM" / "Shared Files").mkdir()

    assert legacy_discover(tmp_path) == [
        {"version_code": "232", "path": str((tmp_path / "AnsysEM" / "v232").resolve())}
    ]


def test_discover_with_exe_and_status(tmp_path: Path) -> None:
    root = tmp_path / "AnsysEM" / "v232"
    win64 = root / "Win64"
    win64.mkdir(parents=True)
    exe = win64 / "ansysedt.exe"
    exe.write_bytes(b"MZ")

    installs = discover_aedt_installations(tmp_path, process_running=False)
    assert len(installs) == 1
    inst = installs[0]
    assert inst.version_code == "232"
    assert inst.version_label == "2023.2"
    assert inst.exe_exists is True
    assert inst.status == "not_running"
    assert inst.process_running is False
    assert Path(inst.exe_path).name == "ansysedt.exe"


def test_discover_exe_missing(tmp_path: Path) -> None:
    (tmp_path / "AnsysEM" / "v232" / "Win64").mkdir(parents=True)
    installs = discover_aedt_installations(tmp_path, process_running=False)
    assert len(installs) == 1
    assert installs[0].exe_exists is False
    assert installs[0].status == "exe_missing"


def test_discover_from_env_var(tmp_path: Path) -> None:
    root = tmp_path / "custom" / "v241"
    win64 = root / "Win64"
    win64.mkdir(parents=True)
    (win64 / "ansysedt.exe").write_bytes(b"MZ")
    env = {"ANSYSEM_ROOT241": str(win64)}
    installs = discover_aedt_installations(
        tmp_path / "missing_pf",
        environ=env,
        process_running=False,
        include_env=True,
    )
    assert any(i.version_code == "241" and i.exe_exists for i in installs)


def test_inspect_environment_structured(tmp_path: Path) -> None:
    root = tmp_path / "AnsysEM" / "v232" / "Win64"
    root.mkdir(parents=True)
    (root / "ansysedt.exe").write_bytes(b"MZ")
    status = inspect_environment(tmp_path, process_running=True)
    payload = status.to_public_dict()
    assert "aedt_installations" in payload
    assert payload["any_running"] is True
    assert payload["preferred"]["version_code"] == "232"
    assert payload["probe_mode"] == "read_only_environment_probe"


def test_version_label() -> None:
    assert version_label_from_code("232") == "2023.2"
    assert version_label_from_code("241") == "2024.1"
