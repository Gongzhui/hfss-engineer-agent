"""Setup CRUD is not part of the V1 MCP surface."""

from __future__ import annotations

from hfss_mcp.server import PUBLIC_TOOL_NAMES


def test_setup_crud_removed_from_mcp() -> None:
    for name in (
        "setup_schema",
        "setup_create",
        "trial_start",
        "run_start",
    ):
        assert name not in PUBLIC_TOOL_NAMES
