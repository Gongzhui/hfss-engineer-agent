"""Real AEDT 2023 R2: attach to a user-style GUI session (COM ROT)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from hfss_mcp.app import AppContext
from hfss_mcp.live import list_rot_sessions

pytestmark = pytest.mark.real_aedt

AEDT_EXE = Path(r"C:\Program Files\AnsysEM\v232\Win64\ansysedt.exe")
GOLDEN = Path(__file__).resolve().parents[1] / "examples" / "golden_patch.aedt"
GOLDEN_MANIFEST = Path(__file__).resolve().parents[1] / "examples" / "golden_manifest.json"


def _aedt_available() -> bool:
    return AEDT_EXE.is_file()


def _ensure_user_style_desktop() -> None:
    sessions = list_rot_sessions(version="2023.2")
    if sessions:
        return
    subprocess.Popen(
        [str(AEDT_EXE)],
        cwd=str(AEDT_EXE.parent),
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    deadline = time.time() + 90
    while time.time() < deadline:
        if list_rot_sessions(version="2023.2"):
            time.sleep(6)
            return
        time.sleep(1)
    pytest.fail("AEDT GUI did not become COM-visible")


def test_live_com_attach_snapshot_and_set(tmp_path: Path) -> None:
    if not _aedt_available():
        pytest.skip("AEDT 2023 R2 not installed")
    if not GOLDEN.is_file():
        pytest.skip("golden_patch.aedt missing")
    _ensure_user_style_desktop()
    sessions = list_rot_sessions(version="2023.2")
    assert sessions, "expected a COM-visible Desktop"
    pid_before = {s["process_id"] for s in sessions}

    ctx = AppContext(data_dir=tmp_path / "hfss_mcp_data", use_fake=False)
    try:
        loaded = ctx.allowlist_load(path=str(GOLDEN_MANIFEST))
        assert loaded["ok"] is True
        snap = ctx.snapshot()
        assert snap["ok"] is True
        assert snap["snapshot"]["design_name"]
        assert snap["snapshot"]["process_id"] in pid_before
        assert "gap" in snap["snapshot"]["variables"]
        original = snap["snapshot"]["variables"]["gap"]["value"]
        target = 1.3 if abs(original - 1.3) > 1e-6 else 1.4
        changed = ctx.variables_set([{"name": "gap", "value": target, "unit": "mm"}])
        assert changed["ok"] is True
        assert changed["saved"] is False
        assert abs(changed["readback"]["gap"]["value"] - target) < 1e-6
        again = ctx.snapshot()
        assert abs(again["snapshot"]["variables"]["gap"]["value"] - target) < 1e-6
        pictured = ctx.view_capture()
        assert Path(pictured["path"]).is_file()
        mapped = ctx.variable_map(names=["gap"])
        assert mapped["ok"] is True
        still = {s["process_id"] for s in list_rot_sessions(version="2023.2")}
        assert pid_before & still, "attach must not quit the user's Desktop"
    finally:
        ctx.close()
    still_after = {s["process_id"] for s in list_rot_sessions(version="2023.2")}
    assert pid_before & still_after, "closing AppContext must not quit AEDT"
