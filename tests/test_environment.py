from pathlib import Path

from hfss_mcp.server import discover_aedt_installations


def test_discover_aedt_installations(tmp_path: Path) -> None:
    (tmp_path / "AnsysEM" / "v232").mkdir(parents=True)
    (tmp_path / "AnsysEM" / "Shared Files").mkdir()

    assert discover_aedt_installations(tmp_path) == [
        {"version_code": "232", "path": str(tmp_path / "AnsysEM" / "v232")}
    ]

