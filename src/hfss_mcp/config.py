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
    env = environ if environ is not None else dict(os.environ)
    if explicit is not None:
        return explicit
    raw = (env.get("HFSS_MCP_ADAPTER") or "").strip().lower()
    if raw in {"pyaedt", "fake"}:
        return raw  # type: ignore[return-value]
    if (env.get("HFSS_MCP_DEMO") or "").strip().lower() in {"1", "true", "yes"}:
        return "fake"
    status = inspect_environment()
    if status.preferred is not None and status.preferred.exe_exists:
        return "pyaedt"
    return "fake"


def load_runtime_config(
    *,
    adapter: AdapterName | None = None,
    data_dir: Path | None = None,
) -> RuntimeConfig:
    env = dict(os.environ)
    name = resolve_adapter_name(explicit=adapter, environ=env)
    demo = (env.get("HFSS_MCP_DEMO") or "").strip().lower() in {"1", "true", "yes"}
    version = (env.get("HFSS_MCP_AEDT_VERSION") or "2023.2").strip()
    return RuntimeConfig(
        adapter=name,
        data_dir=Path(data_dir) if data_dir is not None else default_data_dir(),
        aedt_version=version,
        demo_mode=demo or name == "fake",
    )
