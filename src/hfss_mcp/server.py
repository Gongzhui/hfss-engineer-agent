"""MCP entry point: narrow typed tools only — no arbitrary code execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from hfss_mcp import __version__
from hfss_mcp.app import AppContext, error_envelope
from hfss_mcp.environment import discover_aedt_installations_legacy

# ---------------------------------------------------------------------------
# Tool surface allowlist (for tests and documentation)
# ---------------------------------------------------------------------------

PUBLIC_TOOL_NAMES: tuple[str, ...] = (
    "health",
    "environment_status",
    "manifest_validate",
    "design_snapshot",
    "trial_start",
    "trial_status",
    "trial_result",
    "trial_cancel",
    "checkpoint_list",
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

# Process-wide app context (created lazily so imports stay light)
_app: AppContext | None = None


def get_app() -> AppContext:
    global _app
    if _app is None:
        _app = AppContext(use_fake=True, inline_trials=True)
    return _app


def set_app(app: AppContext | None) -> None:
    """Test hook to inject a custom application context."""
    global _app
    _app = app


def discover_aedt_installations(program_files: Path | None = None) -> list[dict[str, str]]:
    """Backward-compatible discovery used by early unit tests."""
    return discover_aedt_installations_legacy(program_files)


# ---------------------------------------------------------------------------
# Typed request models
# ---------------------------------------------------------------------------


class ManifestValidateInput(BaseModel):
    """Raw manifest document to validate and register for subsequent tools."""

    manifest: dict[str, Any]


class DesignSnapshotInput(BaseModel):
    manifest_id: str = Field(description="SHA-256 manifest ID from manifest_validate")


class ParameterValueInput(BaseModel):
    name: str
    value: float
    unit: str


class TrialStartInput(BaseModel):
    manifest_id: str
    idempotency_key: str
    setup: str
    parameters: list[ParameterValueInput]
    sweep: str | None = None
    run_id: str | None = None
    trial_id: str | None = None
    expected_revision: str | None = None


class JobIdInput(BaseModel):
    job_id: str


class CheckpointListInput(BaseModel):
    run_id: str | None = None
    manifest_id: str | None = None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def health() -> dict[str, Any]:
    """Read-only bridge health and package version (no AEDT launch)."""
    try:
        app = get_app()
        env = app.environment_status()
        return {
            "ok": True,
            "status": "ok" if env.get("aedt_installations") else "aedt_not_found",
            "version": __version__,
            "mode": "tune_only_v0",
            "tools": list(PUBLIC_TOOL_NAMES),
            "environment": env,
        }
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def environment_status() -> dict[str, Any]:
    """Discover AEDT installs and process state without starting AEDT."""
    try:
        result = get_app().environment_status()
        result["ok"] = True
        return result
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def manifest_validate(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate a tune-only manifest, compute its stable ID, and register it.

    Risk: read-only validation. Does not open AEDT or mutate projects.
    """
    try:
        return get_app().register_manifest(manifest)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def design_snapshot(manifest_id: str) -> dict[str, Any]:
    """Attach the approved project/design and return an authoritative snapshot.

    Risk: opens the approved project path from the registered manifest (read-focused).
    Does not mutate parameters.
    """
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
    """Start one allowlisted tune trial as a durable job.

    Applies the complete parameter vector (after policy checks), auto-checkpoints
    before mutation, runs the approved setup, and stores metrics.

    Risk: mutates design variables inside the approved project identity and may
    start a solve. Idempotent on ``idempotency_key``.
    """
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
    """Return durable job state for a trial (survives process restart)."""
    try:
        return get_app().trial_status(job_id)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def trial_result(job_id: str) -> dict[str, Any]:
    """Return trial result payload, metrics, artifacts, or structured error."""
    try:
        return get_app().trial_result(job_id)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def trial_cancel(job_id: str) -> dict[str, Any]:
    """Request cancellation of a queued or running trial.

    Risk: best-effort cancel. If the AEDT host cannot interrupt a solve, the
    job may remain non-cancelled with an honest limitation message.
    """
    try:
        return get_app().trial_cancel(job_id)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


@mcp.tool()
def checkpoint_list(
    run_id: str | None = None,
    manifest_id: str | None = None,
) -> dict[str, Any]:
    """List project checkpoints created for runs/trials.

    Risk: read-only. Restore is internal/scaffolded and not exposed as a public
    mutating tool in v0.
    """
    try:
        return get_app().checkpoint_list(run_id=run_id, manifest_id=manifest_id)
    except Exception as exc:  # noqa: BLE001
        return error_envelope(exc)


def list_registered_tool_names() -> list[str]:
    """Return sorted public tool names from the FastMCP registry."""
    # FastMCP stores tools in mcp._tool_manager._tools in recent versions
    manager = getattr(mcp, "_tool_manager", None)
    if manager is not None:
        tools = getattr(manager, "_tools", None)
        if isinstance(tools, dict):
            return sorted(tools.keys())
    # Fallback: declared allowlist
    return sorted(PUBLIC_TOOL_NAMES)


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
