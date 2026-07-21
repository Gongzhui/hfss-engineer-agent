"""MCP entry point: narrow typed tools only — no arbitrary code execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from hfss_mcp import __version__
from hfss_mcp.app import AppContext, error_envelope
from hfss_mcp.environment import discover_aedt_installations_legacy

PUBLIC_TOOL_NAMES: tuple[str, ...] = (
    "health",
    "environment_status",
    "session_list",
    "manifest_validate",
    "design_snapshot",
    "trial_start",
    "trial_status",
    "trial_result",
    "trial_cancel",
    "checkpoint_list",
    "checkpoint_restore",
    "run_start",
    "run_status",
    "run_result",
    "run_cancel",
    "run_resume",
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
    }
)

mcp = FastMCP("hfss-mcp")
_app: AppContext | None = None


def get_app() -> AppContext:
    global _app
    if _app is None:
        # Production default: pyaedt when AEDT present (see config.resolve_adapter_name)
        _app = AppContext(start_supervisor=True)
    return _app


def set_app(app: AppContext | None) -> None:
    global _app
    _app = app


def discover_aedt_installations(program_files: Path | None = None) -> list[dict[str, str]]:
    return discover_aedt_installations_legacy(program_files)


@mcp.tool()
def health() -> dict[str, Any]:
    """Bridge health: adapter mode, AEDT readiness, connection model (no AEDT launch)."""
    try:
        h = get_app().health()
        h["tools"] = list(PUBLIC_TOOL_NAMES)
        h["package_version"] = __version__
        return h
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def environment_status() -> dict[str, Any]:
    """Discover AEDT installs and GUI sessions without launching a new Desktop."""
    try:
        return get_app().environment_status()
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def session_list() -> dict[str, Any]:
    """List running AEDT sessions and open projects/designs (COM/gRPC discovery).

    Default session_mode=auto ensures a graphical COM Desktop with the project
    open (or attaches when already COM-reachable), then runs live trials there.
    """
    try:
        return get_app().session_list()
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def manifest_validate(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate tune-only manifest (structured metrics), compute ID, persist for workers."""
    try:
        return get_app().register_manifest(manifest)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def design_snapshot(manifest_id: str) -> dict[str, Any]:
    """Snapshot via workspace copy; checks project_name and design_name identity."""
    try:
        return get_app().design_snapshot(manifest_id)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def trial_start(
    manifest_id: str,
    idempotency_key: str,
    setup: str,
    parameters: list[dict[str, Any]],
    sweep: str | None = None,
    run_id: str | None = None,
    trial_id: str | None = None,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    """Enqueue durable trial; returns job_id quickly (worker process executes)."""
    try:
        return get_app().trial_start(
            manifest_id=manifest_id,
            run_id=run_id,
            trial_id=trial_id,
            idempotency_key=idempotency_key,
            setup=setup,
            sweep=sweep,
            parameters={"values": parameters},
            expected_revision=expected_revision,
        )
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def trial_status(job_id: str) -> dict[str, Any]:
    try:
        return get_app().trial_status(job_id)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def trial_result(job_id: str) -> dict[str, Any]:
    try:
        return get_app().trial_result(job_id)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def trial_cancel(job_id: str) -> dict[str, Any]:
    """Request cancel; supervisor terminates only owned worker/AEDT processes."""
    try:
        return get_app().trial_cancel(job_id)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def checkpoint_list(
    run_id: str | None = None,
    manifest_id: str | None = None,
) -> dict[str, Any]:
    try:
        return get_app().checkpoint_list(run_id=run_id, manifest_id=manifest_id)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def checkpoint_restore(checkpoint_id: str, run_id: str) -> dict[str, Any]:
    """Restore working copy from checkpoint (restricted to run workspace)."""
    try:
        return get_app().checkpoint_restore(checkpoint_id=checkpoint_id, run_id=run_id)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def run_start(
    manifest_id: str,
    idempotency_key: str,
    strategy: str = "seeded_random",
    seed: int = 0,
    setup: str | None = None,
    sweep: str | None = None,
) -> dict[str, Any]:
    """Start unattended multi-trial optimization run (seeded random v0)."""
    try:
        return get_app().run_start(
            manifest_id=manifest_id,
            idempotency_key=idempotency_key,
            strategy=strategy,
            seed=seed,
            setup=setup,
            sweep=sweep,
        )
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def run_status(run_id: str) -> dict[str, Any]:
    try:
        return get_app().run_status(run_id)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def run_result(run_id: str) -> dict[str, Any]:
    try:
        return get_app().run_result(run_id)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def run_cancel(run_id: str) -> dict[str, Any]:
    try:
        return get_app().run_cancel(run_id)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def run_resume(run_id: str) -> dict[str, Any]:
    """Resume an interrupted optimization run without redoing completed trials."""
    try:
        return get_app().run_resume(run_id)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


def list_registered_tool_names() -> list[str]:
    manager = getattr(mcp, "_tool_manager", None)
    if manager is not None:
        tools = getattr(manager, "_tools", None)
        if isinstance(tools, dict):
            return sorted(tools.keys())
    return sorted(PUBLIC_TOOL_NAMES)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
