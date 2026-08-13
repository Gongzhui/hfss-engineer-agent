"""MCP entry point: narrow typed tools only — no arbitrary code execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from hfss_mcp.app import AppContext, error_envelope
from hfss_mcp.environment import discover_aedt_installations_legacy

PUBLIC_TOOL_NAMES: tuple[str, ...] = (
    "health",
    "session_list",
    "allowlist_load",
    "snapshot",
    "variables_set",
    "analyze_start",
    "analyze_status",
    "analyze_cancel",
    "report_types",
    "report_list",
    "report_create",
    "report_export",
    "view_capture",
    "variable_map",
    "project_save",
)

FORBIDDEN_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "run_python_code",
        "run_python_script",
        "exec",
        "execute",
        "invoke",
        "aedt_call",
        "aedt_batch_call",
        "generic_invoke",
        "run_script",
        "eval",
        "trial_start",
        "run_start",
    }
)

mcp = FastMCP("hfss-mcp")
_app: AppContext | None = None


def get_app() -> AppContext:
    global _app
    if _app is None:
        _app = AppContext()
    return _app


def set_app(app: AppContext | None) -> None:
    global _app
    _app = app


def discover_aedt_installations(program_files: Path | None = None) -> list[dict[str, str]]:
    return discover_aedt_installations_legacy(program_files)


@mcp.tool()
def health() -> dict[str, Any]:
    """Bridge health and COM-visible AEDT sessions. Does not launch AEDT."""
    try:
        return get_app().health()
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def session_list() -> dict[str, Any]:
    """List COM-visible Electronics Desktop sessions and open projects."""
    try:
        return get_app().session_list()
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def allowlist_load(
    path: str | None = None,
    allowlist: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load writable variable bounds. Accepts slim JSON, old manifest 1.1, or case.json."""
    try:
        return get_app().allowlist_load(path=path, allowlist=allowlist)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def snapshot() -> dict[str, Any]:
    """JSON snapshot of the attached live design: variables, setups, identity. No screenshot."""
    try:
        return get_app().snapshot()
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def variables_set(parameters: list[dict[str, Any]]) -> dict[str, Any]:
    """Set one or more allowlisted variables. Partial update. Does not solve or save."""
    try:
        return get_app().variables_set(parameters)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def analyze_start(setup: str | None = None) -> dict[str, Any]:
    """Start Analyze on the live design (async job). Does not extract metrics."""
    try:
        return get_app().analyze_start(setup=setup)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def analyze_status(job_id: str) -> dict[str, Any]:
    try:
        return get_app().analyze_status(job_id)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def analyze_cancel(job_id: str) -> dict[str, Any]:
    """Best-effort cancel. Will not kill the user's AEDT process."""
    try:
        return get_app().analyze_cancel(job_id)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def report_types() -> dict[str, Any]:
    """Finite HFSS report-type catalog (details live in the Skill)."""
    try:
        return get_app().report_types()
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def report_list() -> dict[str, Any]:
    try:
        return get_app().report_list()
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def report_create(
    report_type: str,
    name: str | None = None,
    setup: str | None = None,
    sweep: str | None = None,
    face: str | None = None,
    frequency: str | None = None,
) -> dict[str, Any]:
    """Create a report handle. Export separately (CSV for curves, image for fields)."""
    try:
        return get_app().report_create(
            report_type,
            name=name,
            setup=setup,
            sweep=sweep,
            face=face,
            frequency=frequency,
        )
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def report_export(report_id: str) -> dict[str, Any]:
    """Export a created report. Curves → CSV path; field_face needs face+frequency."""
    try:
        return get_app().report_export(report_id)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def view_capture(
    orientation: str = "isometric",
    isolate: list[str] | None = None,
) -> dict[str, Any]:
    """Screenshot the live 3D modeler view. Optional isolate object names."""
    try:
        return get_app().view_capture(orientation=orientation, isolate=isolate)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def variable_map(names: list[str] | None = None) -> dict[str, Any]:
    """Find-references: which objects/expressions use which variables."""
    try:
        return get_app().variable_map(names=names)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def project_save(mode: str = "save_as", path: str | None = None) -> dict[str, Any]:
    """Save or Save As. Never automatic. Prefer save_as to a new versioned file."""
    try:
        return get_app().project_save(mode=mode, path=path)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


def list_registered_tool_names() -> list[str]:
    manager = getattr(mcp, "_tool_manager", None)
    if manager is not None:
        tools = getattr(manager, "_tools", None)
        if isinstance(tools, dict):
            return sorted(tools.keys())
    return sorted(PUBLIC_TOOL_NAMES)


def _prewarm_imports() -> None:
    import importlib

    for name in ("numpy", "win32com.client", "pythoncom"):
        try:
            importlib.import_module(name)
        except Exception:
            pass


def main() -> None:
    _prewarm_imports()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
