"""AEDT installation discovery without launching the host."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

InstallStatus = Literal[
    "installed",
    "exe_missing",
    "not_running",
    "running",
    "not_found",
]


class AedtInstallation(BaseModel):
    """Structured description of one AEDT install root."""

    version_code: str
    version_label: str
    install_root: str
    win64_dir: str
    exe_path: str
    exe_exists: bool
    env_var: str | None = None
    process_running: bool = False
    status: InstallStatus


class EnvironmentStatus(BaseModel):
    """Top-level environment observation returned to agents."""

    aedt_installations: list[AedtInstallation] = Field(default_factory=list)
    preferred: AedtInstallation | None = None
    any_running: bool = False
    probe_mode: str = "read_only_environment_probe"

    def to_public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


_VERSION_DIR_RE = re.compile(r"^v(?P<code>\d{3,4})$", re.IGNORECASE)
_ENV_ROOT_RE = re.compile(r"^(?:ANSYSEM_ROOT|AWP_ROOT)(?P<code>\d+)$", re.IGNORECASE)


def version_label_from_code(code: str) -> str:
    """Map ``232`` -> ``2023.2``, ``241`` -> ``2024.1``."""
    if len(code) == 3:
        yy = int(code[:2])
        release = int(code[2])
        return f"20{yy:02d}.{release}"
    if len(code) == 4:
        yy = int(code[:2])
        release = int(code[2:])
        return f"20{yy:02d}.{release}"
    return code


def _is_process_running(image_name: str = "ansysedt.exe") -> bool:
    """Best-effort process check without third-party deps."""
    if os.name == "nt":
        try:
            import subprocess

            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=10,
            )
            return image_name.lower() in (result.stdout or "").lower()
        except (OSError, subprocess.SubprocessError):
            return False
    # Non-Windows: look for process name via /proc if present
    try:
        import subprocess

        result = subprocess.run(
            ["pgrep", "-f", "ansysedt"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        return bool((result.stdout or "").strip())
    except (OSError, subprocess.SubprocessError):
        return False


def _installation_from_root(
    install_root: Path,
    *,
    version_code: str | None = None,
    env_var: str | None = None,
    process_running: bool = False,
) -> AedtInstallation | None:
    root = install_root.expanduser()
    # Accept either .../v232 or .../v232/Win64
    if root.name.lower() == "win64":
        win64 = root
        root = root.parent
    else:
        win64 = root / "Win64"

    code = version_code
    if code is None:
        match = _VERSION_DIR_RE.match(root.name)
        if not match:
            return None
        code = match.group("code")

    exe = win64 / "ansysedt.exe"
    exe_exists = exe.is_file()
    if not root.exists() and not win64.exists():
        return None

    if process_running:
        status: InstallStatus = "running"
    elif exe_exists:
        # Installed and executable present; host not currently running (caller sets).
        status = "not_running" if not process_running else "running"
        status = "not_running"
    elif root.exists() or win64.exists():
        status = "exe_missing"
    else:
        status = "not_found"

    if process_running and exe_exists:
        status = "running"

    return AedtInstallation(
        version_code=code,
        version_label=version_label_from_code(code),
        install_root=str(root.resolve(strict=False)),
        win64_dir=str(win64.resolve(strict=False)),
        exe_path=str(exe.resolve(strict=False)),
        exe_exists=exe_exists,
        env_var=env_var,
        process_running=process_running,
        status=status,
    )


def discover_aedt_installations(
    program_files: Path | None = None,
    *,
    environ: dict[str, str] | None = None,
    process_running: bool | None = None,
    include_env: bool | None = None,
) -> list[AedtInstallation]:
    """Discover AEDT installs from Program Files and ANSYSEM_ROOT* env vars.

    Isolation rules for tests:
    - If ``program_files`` is set and ``include_env`` is None, host env roots are
      skipped (so unit tests do not pick up the real AEDT install).
    - Pass ``include_env=True`` or an explicit ``environ`` dict to merge env roots.
    """
    env = environ if environ is not None else dict(os.environ)
    running = _is_process_running() if process_running is None else process_running

    # Explicit environ => merge those roots; custom program_files alone => isolate
    merge_env = (
        (environ is not None or program_files is None)
        if include_env is None
        else include_env
    )

    found: dict[str, AedtInstallation] = {}

    # Program Files / AnsysEM / v*
    root = program_files or Path(env.get("PROGRAMFILES", r"C:\Program Files"))
    ansys_em = root / "AnsysEM"
    if ansys_em.is_dir():
        for path in sorted(ansys_em.iterdir()):
            if not path.is_dir():
                continue
            match = _VERSION_DIR_RE.match(path.name)
            if not match:
                continue
            code = match.group("code")
            inst = _installation_from_root(path, version_code=code, process_running=running)
            if inst is not None:
                found[code] = inst

    if merge_env:
        for name, value in env.items():
            match = _ENV_ROOT_RE.match(name)
            if not match or not value.strip():
                continue
            code = match.group("code")
            inst = _installation_from_root(
                Path(value),
                version_code=code,
                env_var=name,
                process_running=running,
            )
            if inst is None:
                continue
            existing = found.get(code)
            if existing is None or (not existing.exe_exists and inst.exe_exists):
                found[code] = inst
            elif existing is not None and existing.env_var is None and inst.env_var:
                found[code] = existing.model_copy(
                    update={
                        "env_var": inst.env_var,
                        "process_running": running,
                        "status": (
                            "running"
                            if running and existing.exe_exists
                            else existing.status
                        ),
                    }
                )

    # Normalize process flags on all
    results: list[AedtInstallation] = []
    for code in sorted(found.keys()):
        inst = found[code]
        if running and inst.exe_exists:
            inst = inst.model_copy(update={"process_running": True, "status": "running"})
        elif inst.exe_exists:
            inst = inst.model_copy(update={"process_running": False, "status": "not_running"})
        results.append(inst)
    return results


def inspect_environment(
    program_files: Path | None = None,
    *,
    environ: dict[str, str] | None = None,
    process_running: bool | None = None,
) -> EnvironmentStatus:
    installations = discover_aedt_installations(
        program_files,
        environ=environ,
        process_running=process_running,
    )
    preferred = None
    for inst in reversed(installations):
        if inst.exe_exists:
            preferred = inst
            break
    if preferred is None and installations:
        preferred = installations[-1]
    return EnvironmentStatus(
        aedt_installations=installations,
        preferred=preferred,
        any_running=any(i.process_running for i in installations),
    )


# Backward-compatible helper used by early tests / callers
def discover_aedt_installations_legacy(program_files: Path | None = None) -> list[dict[str, str]]:
    """Legacy shape: version_code + path (install root)."""
    return [
        {"version_code": item.version_code, "path": item.install_root}
        for item in discover_aedt_installations(program_files, process_running=False)
    ]
