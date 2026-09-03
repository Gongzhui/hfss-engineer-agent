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
    "session_attach",
    "allowlist_load",
    "snapshot",
    "variables_set",
    "analyze_start",
    "analyze_status",
    "analyze_cancel",
    "report_types",
    "report_catalog",
    "report_list",
    "report_get",
    "report_create",
    "report_export",
    "view_hide",
    "view_show",
    "view_capture",
    "variable_map",
    "project_save",
    "optimetrics_types",
    "optimetrics_list",
    "parametric_create",
    "parametric_start",
    "parametric_export_table",
    "solved_points_list",
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
    """List COM-visible Desktops, open projects, the GUI active project, and MCP bind."""
    try:
        return get_app().session_list()
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def session_attach(
    project_name: str | None = None,
    design_name: str | None = None,
) -> dict[str, Any]:
    """Bind MCP to an already-open GUI project. Never reopens a closed file."""
    try:
        return get_app().session_attach(
            project_name=project_name,
            design_name=design_name,
        )
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
    """JSON snapshot of the GUI active design (follows the open project). No screenshot."""
    try:
        return get_app().snapshot()
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def variables_set(parameters: list[dict[str, Any]]) -> dict[str, Any]:
    """Set allowlisted variables. `name` or `variable`. No solve, no save."""
    try:
        return get_app().variables_set(parameters)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def analyze_start(setup: str | None = None) -> dict[str, Any]:
    """Accept an Analyze job. ok is not solved — poll analyze_status until done."""
    try:
        return get_app().analyze_start(setup=setup)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def analyze_status(job_id: str) -> dict[str, Any]:
    """Job state plus Message Manager lines (what a human sees while it solves)."""
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
    """Surfaces: curve via report_catalog, or field_face. Keep this list short."""
    try:
        return get_app().report_types()
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def report_catalog(
    category: str | None = None,
    quantity: str | None = None,
    setup: str | None = None,
    sweep: str | None = None,
) -> dict[str, Any]:
    """Progressive Category → Quantity → Function. Returns only the next level."""
    try:
        return get_app().report_catalog(
            category=category,
            quantity=quantity,
            setup=setup,
            sweep=sweep,
        )
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def report_list() -> dict[str, Any]:
    """List reports currently under Results (what a human can see)."""
    try:
        return get_app().report_list()
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def report_get(name: str) -> dict[str, Any]:
    """Read full settings of an existing Results report (incl. user-created)."""
    try:
        return get_app().report_get(name)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def report_create(
    report_type: str | None = None,
    category: str | None = None,
    quantity: str | list[str] | None = None,
    function: str | list[str] | None = None,
    name: str | None = None,
    setup: str | None = None,
    sweep: str | None = None,
    face: str | None = None,
    frequency: str | None = None,
    families: list[str] | None = None,
    parametric: str | None = None,
) -> dict[str, Any]:
    """Create a Results plot. Curves: category + quantity + function (both multi-ok).

    quantity/function may be a string or list; Y = cartesian Function × Quantity.
    Call report_catalog first. field_face still uses report_type + face + frequency.
    """
    try:
        return get_app().report_create(
            report_type,
            category=category,
            quantity=quantity,
            function=function,
            name=name,
            setup=setup,
            sweep=sweep,
            face=face,
            frequency=frequency,
            families=families,
            parametric=parametric,
        )
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def report_export(
    report_id: str,
    path: str | None = None,
    summarize: dict[str, Any] | None = None,
    png: bool = False,
) -> dict[str, Any]:
    """ExportToFile a Results report. CSV includes traces/labeled; may be stale.

    Family S11 uses GUI Export Data (one column per swept variable).
    Optional path writes the CSV there. summarize={target_ghz, threshold_db}
    adds per-trace band/FBW/edge flags. png=true renders a plot beside the CSV.
    """
    try:
        return get_app().report_export(
            report_id, path=path, summarize=summarize, png=png
        )
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def view_hide(names: list[str]) -> dict[str, Any]:
    """Exclude 3D modeler objects from subsequent view_capture renders. Bookkeeping only — the GUI is not touched (2023 R2 has no GUI-hide API)."""
    try:
        return get_app().view_hide(names)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def view_show(names: list[str] | None = None, all_objects: bool = False) -> dict[str, Any]:
    """Remove objects from the view_hide exclusion set. all_objects=true clears it."""
    try:
        return get_app().view_show(names, all_objects=all_objects)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def view_capture(
    orientation: str = "isometric",
    fit: list[str] | None = None,
    isolate: list[str] | None = None,
) -> dict[str, Any]:
    """Screenshot the live 3D modeler.

    Renders only the requested objects: fit=[names] renders exactly those and
    frames them (export-time Selections + FitToSelections, true exclusion);
    without fit, everything except the persistent view_hide set is rendered and
    framed. isolate is the same as fit (kept for older callers). orientation
    must be one of isometric/top/bottom/front/back/left/right. Response:
    selection = what was rendered, hidden = persistent view_hide set.
    """
    try:
        return get_app().view_capture(
            orientation=orientation, fit=fit, isolate=isolate
        )
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


@mcp.tool()
def optimetrics_types() -> dict[str, Any]:
    """Finite Optimetrics catalog. Currently only parametric is allowed."""
    try:
        return get_app().optimetrics_types()
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def optimetrics_list() -> dict[str, Any]:
    """List setups under Optimetrics (what a human can see)."""
    try:
        return get_app().optimetrics_list()
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def parametric_create(
    name: str | None = None,
    setup: str | None = None,
    sweeps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create or edit an Optimetrics Parametric node. `variable` or `name`.

    Cartesian: linear_step / linear_count / values per axis.
    Explicit table: one entry {variation: "table", rows: [{l1: ..., l2: ...}, ...]}.
    Table rows are zipped (not a product). Max 256 points.
    """
    try:
        return get_app().parametric_create(name=name, setup=setup, sweeps=sweeps)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def parametric_start(name: str) -> dict[str, Any]:
    """Accept Optimetrics SolveSetup (async). ok is not solved — poll analyze_status."""
    try:
        return get_app().parametric_start(name)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def parametric_export_table(name: str) -> dict[str, Any]:
    """Export the parametric sweep table (ExportParametricSetupTable).

    Adds unswept allowlist values as context columns when this process created the setup.
    """
    try:
        return get_app().parametric_export_table(name)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def solved_points_list(
    source: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """List persisted solved (or failed) design points for this project/design."""
    try:
        return get_app().solved_points_list(source=source, limit=limit)
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
    # Crash observability: the MCP host only keeps an in-memory stderr tail,
    # so a hard crash (e.g. native COM fault) leaves no evidence. Persist a
    # startup line per process and a faulthandler dump under the data dir.
    try:
        import faulthandler
        import os
        from datetime import datetime, timezone

        from hfss_mcp.config import default_data_dir

        log_dir = default_data_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        crash = open(log_dir / "server-crash.log", "a", encoding="utf-8")
        faulthandler.enable(crash)
        with open(log_dir / "server-lifecycle.log", "a", encoding="utf-8") as fh:
            fh.write(
                f"{datetime.now(timezone.utc).isoformat()} start pid={os.getpid()}\n"
            )
    except Exception:
        pass
    _prewarm_imports()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
