"""Deprecated mouse-injection bridge — use :mod:`hfss_mcp.com_session` instead.

Historical note: AEDT GUIs opened from the Start Menu often do not register in
the COM ROT. The supported approach (ported from ``hfss-cli``) is:

1. Ensure a **COM-registered graphical Desktop** (Dispatch / open project).
2. Operate via ``oDesktop.RunScript`` or PyAEDT attach to that PID.

This module re-exports the COM helpers for any leftover imports.
"""

from __future__ import annotations

from hfss_mcp.com_session import (  # noqa: F401
    desktop_prog_id,
    ensure_graphical_project,
    execute_run_script,
    find_com_project,
    get_desktop,
    iter_rot_desktops,
    list_com_projects,
    open_project_on_desktop,
)

__all__ = [
    "desktop_prog_id",
    "ensure_graphical_project",
    "execute_run_script",
    "find_com_project",
    "get_desktop",
    "iter_rot_desktops",
    "list_com_projects",
    "open_project_on_desktop",
]
