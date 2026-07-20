"""MCP entry point and environment health probe."""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("hfss-mcp")


def discover_aedt_installations(program_files: Path | None = None) -> list[dict[str, str]]:
    """Return installed AEDT version directories without starting AEDT."""
    root = program_files or Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    ansys_em = root / "AnsysEM"
    if not ansys_em.is_dir():
        return []

    installations = []
    for path in sorted(ansys_em.glob("v*")):
        if path.is_dir() and path.name[1:].isdigit():
            installations.append({"version_code": path.name[1:], "path": str(path)})
    return installations


@mcp.tool()
def health() -> dict[str, object]:
    """Report the bridge environment without opening or modifying an AEDT project."""
    installations = discover_aedt_installations()
    return {
        "status": "ok" if installations else "aedt_not_found",
        "aedt_installations": installations,
        "mode": "read_only_environment_probe",
    }


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
