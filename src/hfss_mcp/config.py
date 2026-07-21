"""Runtime configuration for production vs test/demo modes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from hfss_mcp.environment import inspect_environment

AdapterName = Literal["pyaedt", "fake"]


@dataclass(frozen=True)
class RuntimeConfig:
    adapter: AdapterName
    data_dir: Path
    aedt_version: str
    non_graphical: bool
    inline_trials: bool  # only allowed for fake/tests
    max_worker_processes: int
    demo_mode: bool

    @property
    def is_production_real(self) -> bool:
        return self.adapter == "pyaedt" and not self.demo_mode


def default_data_dir() -> Path:
    env = os.environ.get("HFSS_MCP_DATA_DIR")
    if env:
        return Path(env)
    return Path.home() / ".hfss-mcp"


def resolve_adapter_name(
    *,
    explicit: AdapterName | None = None,
    environ: dict[str, str] | None = None,
) -> AdapterName:
    """Resolve adapter: env HFSS_MCP_ADAPTER, else pyaedt when AEDT installed on Windows."""
    env = environ if environ is not None else dict(os.environ)
    if explicit is not None:
        return explicit
    raw = (env.get("HFSS_MCP_ADAPTER") or "").strip().lower()
    if raw in {"pyaedt", "fake"}:
        return raw  # type: ignore[return-value]
    # Explicit demo force
    if (env.get("HFSS_MCP_DEMO") or "").strip().lower() in {"1", "true", "yes"}:
        return "fake"
    # Production default: prefer real AEDT when discoverable
    status = inspect_environment()
    if status.preferred is not None and status.preferred.exe_exists:
        return "pyaedt"
    return "fake"


def load_runtime_config(
    *,
    adapter: AdapterName | None = None,
    data_dir: Path | None = None,
    force_inline: bool | None = None,
) -> RuntimeConfig:
    env = dict(os.environ)
    name = resolve_adapter_name(explicit=adapter, environ=env)
    demo = (env.get("HFSS_MCP_DEMO") or "").strip().lower() in {"1", "true", "yes"}
    if name == "fake" and not demo and adapter is None and not env.get("HFSS_MCP_ADAPTER"):
        # Resolved to fake only because AEDT missing — still not demo
        demo = False
    inline_env = (env.get("HFSS_MCP_INLINE_TRIALS") or "").strip().lower()
    if force_inline is not None:
        inline = force_inline
    elif inline_env in {"1", "true", "yes"}:
        inline = True
    elif inline_env in {"0", "false", "no"}:
        inline = False
    else:
        # Fake may use inline for unit tests; pyaedt never blocks MCP on inline by default
        inline = name == "fake"

    # Safety: never inline real AEDT in the MCP process
    if name == "pyaedt":
        inline = False

    version = (env.get("HFSS_MCP_AEDT_VERSION") or "2023.2").strip()
    non_graphical = (env.get("HFSS_MCP_NON_GRAPHICAL") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    max_workers = int(env.get("HFSS_MCP_MAX_WORKERS") or "1")
    max_workers = max(1, min(max_workers, 4))

    return RuntimeConfig(
        adapter=name,
        data_dir=Path(data_dir) if data_dir is not None else default_data_dir(),
        aedt_version=version,
        non_graphical=non_graphical,
        inline_trials=inline,
        max_worker_processes=max_workers,
        demo_mode=demo or name == "fake",
    )
