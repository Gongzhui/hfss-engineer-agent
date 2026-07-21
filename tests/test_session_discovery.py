"""Session discovery unit tests (no AEDT required for pure helpers)."""

from __future__ import annotations

from pathlib import Path

from hfss_mcp.session_discovery import (
    OpenProjectInfo,
    RunningSessionInfo,
    SessionDiscoveryResult,
    find_open_project,
)


def test_find_open_project_by_path() -> None:
    path = r"C:\Users\me\proj\Antenna.aedt"
    disc = SessionDiscoveryResult(
        sessions=[
            RunningSessionInfo(
                process_id=1234,
                transport="com",
                projects=[
                    OpenProjectInfo(
                        project_name="Antenna",
                        project_path=path,
                        is_active=True,
                        designs=[],
                    )
                ],
            )
        ],
        any_gui_session=True,
    )
    match = find_open_project(disc, path)
    assert match is not None
    sess, proj = match
    assert sess.process_id == 1234
    assert proj.project_name == "Antenna"


def test_find_open_project_by_stem() -> None:
    disc = SessionDiscoveryResult(
        sessions=[
            RunningSessionInfo(
                process_id=9,
                transport="com",
                projects=[
                    OpenProjectInfo(
                        project_name="Demo",
                        project_path=None,
                        is_active=True,
                        designs=[],
                    )
                ],
            )
        ]
    )
    match = find_open_project(disc, Path(r"D:\work\Demo.aedt"))
    assert match is not None
    assert match[0].process_id == 9
