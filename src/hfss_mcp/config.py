"""Runtime configuration for production vs test/demo modes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from hfss_mcp.environment import inspect_environment

AdapterName = Literal["pyaedt", "fake"]
SessionMode = Literal["auto", "attach", "new"]


@dataclass(frozen=True)
class RuntimeConfig:
    adapter: AdapterName
    data_dir: Path
    aedt_version: str
    non_graphical: bool
    inline_trials: bool  # only allowed for fake/tests
    max_worker_processes: int
    demo_mode: bool
    session_mode: SessionMode
    # When True (opt-in via HFSS_MCP_ATTACH_LIVE=1; default False), mutate the
    # live GUI project after checkpoint — rewrites the original .aedt, unsafe.
    attach_live_project: bool

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
    if (env.get("HFSS_MCP_DEMO") or "").strip().lower() in {"1", "true", "yes"}:
        return "fake"
    status = inspect_environment()
    if status.preferred is not None and status.preferred.exe_exists:
        return "pyaedt"
    return "fake"


def resolve_session_mode(
    *,
    explicit: SessionMode | None = None,
    environ: dict[str, str] | None = None,
) -> SessionMode:
    env = environ if environ is not None else dict(os.environ)
    if explicit is not None:
        return explicit
    raw = (env.get("HFSS_MCP_SESSION_MODE") or "auto").strip().lower()
    if raw in {"auto", "attach", "new"}:
        return raw  # type: ignore[return-value]
    return "auto"


def load_runtime_config(
    *,
    adapter: AdapterName | None = None,
    data_dir: Path | None = None,
    force_inline: bool | None = None,
    session_mode: SessionMode | None = None,
) -> RuntimeConfig:
    env = dict(os.environ)
    name = resolve_adapter_name(explicit=adapter, environ=env)
    demo = (env.get("HFSS_MCP_DEMO") or "").strip().lower() in {"1", "true", "yes"}
    if name == "fake" and not demo and adapter is None and not env.get("HFSS_MCP_ADAPTER"):
        demo = False
    inline_env = (env.get("HFSS_MCP_INLINE_TRIALS") or "").strip().lower()
    if force_inline is not None:
        inline = force_inline
    elif inline_env in {"1", "true", "yes"}:
        inline = True
    elif inline_env in {"0", "false", "no"}:
        inline = False
    else:
        inline = name == "fake"

    # Real AEDT: allow inline when attaching to GUI (shared session); never block with multi-desktop
    sess = resolve_session_mode(explicit=session_mode, environ=env)

    version = (env.get("HFSS_MCP_AEDT_VERSION") or "2023.2").strip()
    # Graphical default when attaching; non-graphical for pure new-desktop workers
    non_graphical_env = env.get("HFSS_MCP_NON_GRAPHICAL")
    if non_graphical_env is None or non_graphical_env.strip() == "":
        # Headless by default: trials run in exclusive worker desktops; GUI
        # attach paths select graphical mode explicitly where needed.
        non_graphical = True
    else:
        non_graphical = non_graphical_env.strip().lower() not in {"0", "false", "no"}

    max_workers = int(env.get("HFSS_MCP_MAX_WORKERS") or "1")
    max_workers = max(1, min(max_workers, 4))

    # Default off: mutating the live GUI project would rewrite the original
    # .aedt, breaking the byte-invariance safety invariant. Opt in explicitly
    # with HFSS_MCP_ATTACH_LIVE=1 (interactive use only).
    attach_live = (env.get("HFSS_MCP_ATTACH_LIVE") or "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }

    # In attach/auto mode, prefer single-process execution so we do not fight the GUI session
    if name == "pyaedt" and sess in {"attach", "auto"} and force_inline is None:
        # Supervisor still used for "new" fallback; attach path uses process-local runner
        pass

    if name == "pyaedt" and sess == "new" and force_inline is None:
        inline = False

    return RuntimeConfig(
        adapter=name,
        data_dir=Path(data_dir) if data_dir is not None else default_data_dir(),
        aedt_version=version,
        non_graphical=non_graphical,
        inline_trials=inline,
        max_worker_processes=max_workers,
        demo_mode=demo or name == "fake",
        session_mode=sess,
        attach_live_project=attach_live,
    )
