"""Discover running AEDT sessions and GUI-open projects (attach-first default)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

SessionTransport = Literal["com", "grpc", "unknown"]


class OpenDesignInfo(BaseModel):
    design_name: str
    design_type: str | None = None
    is_active: bool = False


class OpenProjectInfo(BaseModel):
    project_name: str
    project_path: str | None = None
    is_active: bool = False
    designs: list[OpenDesignInfo] = Field(default_factory=list)


class RunningSessionInfo(BaseModel):
    process_id: int
    transport: SessionTransport
    grpc_port: int | None = None
    version_hint: str | None = None
    projects: list[OpenProjectInfo] = Field(default_factory=list)
    source: str = "discovery"


class SessionDiscoveryResult(BaseModel):
    sessions: list[RunningSessionInfo] = Field(default_factory=list)
    any_gui_session: bool = False
    preferred_process_id: int | None = None
    preferred_project_path: str | None = None
    preferred_design_name: str | None = None
    notes: list[str] = Field(default_factory=list)

    def to_public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, int(pid))
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return True
                return int(code.value) == 259  # STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _normalize_path(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return str(Path(path).expanduser().resolve(strict=False))
    except Exception:
        return str(path)


def _com_list_sessions(version: str | None = None) -> list[RunningSessionInfo]:
    """Windows COM ROT discovery of Electronics Desktop + open projects."""
    if os.name != "nt":
        return []
    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
    except Exception:
        return []

    sessions: list[RunningSessionInfo] = []
    try:
        pythoncom.CoInitialize()
    except Exception:
        pass

    try:
        rot = pythoncom.GetRunningObjectTable()
        enum = rot.EnumRunning()
        bind_context = pythoncom.CreateBindCtx(0)
    except Exception:
        return []

    seen: set[int] = set()
    while True:
        try:
            monikers = enum.Next(1)
        except Exception:
            break
        if not monikers:
            break
        moniker = monikers[0]
        try:
            display = str(moniker.GetDisplayName(bind_context, None))
        except Exception:
            continue
        if "ElectronicsDesktop" not in display:
            continue
        if version and f".{version}" not in display and version.replace(".", "") not in display:
            # soft filter — still accept generic Ansoft.ElectronicsDesktop
            if f"Ansoft.ElectronicsDesktop.{version}" not in display:
                pass
        try:
            unknown = rot.GetObject(moniker)
            dispatch = win32com.client.Dispatch(unknown.QueryInterface(pythoncom.IID_IDispatch))
            try:
                desktop = dispatch.GetAppDesktop()
            except Exception:
                desktop = dispatch
            pid = int(desktop.GetProcessID())
        except Exception:
            continue
        if pid in seen:
            continue
        seen.add(pid)
        projects = _com_list_projects(desktop)
        sessions.append(
            RunningSessionInfo(
                process_id=pid,
                transport="com",
                grpc_port=None,
                version_hint=version,
                projects=projects,
                source="com_rot",
            )
        )
    return sessions


def _com_list_projects(desktop: Any) -> list[OpenProjectInfo]:
    out: list[OpenProjectInfo] = []
    try:
        names = list(desktop.GetProjectList() or [])
    except Exception:
        return out
    active_name = None
    try:
        active = desktop.GetActiveProject()
        if active is not None:
            active_name = str(active.GetName())
    except Exception:
        pass
    for name in names:
        try:
            project = desktop.SetActiveProject(name)
        except Exception:
            try:
                project = desktop.GetProject(name)
            except Exception:
                continue
        path = None
        try:
            path = str(project.GetPath())
            # AEDT sometimes returns directory; join name
            if path and not path.lower().endswith((".aedt", ".aedtz")):
                candidate = Path(path) / f"{name}.aedt"
                path = str(candidate) if candidate.is_file() else str(Path(path) / name)
        except Exception:
            path = None
        designs: list[OpenDesignInfo] = []
        active_design = None
        try:
            ad = project.GetActiveDesign()
            if ad is not None:
                active_design = str(ad.GetName())
        except Exception:
            pass
        try:
            # GetTopDesignList returns "Type::Name" sometimes
            raw_list = list(project.GetTopDesignList() or [])
            for item in raw_list:
                text = str(item)
                dtype = None
                dname = text
                if "::" in text:
                    dtype, dname = text.split("::", 1)
                designs.append(
                    OpenDesignInfo(
                        design_name=dname,
                        design_type=dtype,
                        is_active=(dname == active_design),
                    )
                )
        except Exception:
            if active_design:
                designs.append(
                    OpenDesignInfo(design_name=active_design, is_active=True)
                )
        out.append(
            OpenProjectInfo(
                project_name=str(name),
                project_path=_normalize_path(path),
                is_active=(str(name) == active_name),
                designs=designs,
            )
        )
    return out


def _pyaedt_active_sessions(version: str | None = None) -> list[RunningSessionInfo]:
    """Supplement discovery with PyAEDT process/port scan."""
    active_sessions: Any = None
    try:
        import importlib

        mod = importlib.import_module("ansys.aedt.core.generic.general_methods")
        active_sessions = getattr(mod, "active_sessions", None)
    except Exception:
        try:
            import importlib

            mod = importlib.import_module("pyaedt.generic.general_methods")
            active_sessions = getattr(mod, "active_sessions", None)
        except Exception:
            return []
    if not callable(active_sessions):
        return []
    try:
        raw = active_sessions(version=version) if version else active_sessions()
    except Exception:
        try:
            raw = active_sessions()
        except Exception:
            return []
    sessions: list[RunningSessionInfo] = []
    if not isinstance(raw, dict):
        return sessions
    for pid, port in raw.items():
        try:
            process_id = int(pid)
            port_i = int(port)
        except Exception:
            continue
        transport: SessionTransport = "grpc" if port_i > 0 else "com"
        sessions.append(
            RunningSessionInfo(
                process_id=process_id,
                transport=transport,
                grpc_port=port_i if port_i > 0 else None,
                version_hint=version,
                projects=[],
                source="pyaedt_active_sessions",
            )
        )
    return sessions


def _parse_lock_assignment(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if "=" not in text or text.startswith("$"):
        return None
    key, value = text.split("=", 1)
    value = value.strip()
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        value = value[1:-1].replace("\\\\", "\\")
    return key.strip(), value


def _discover_lock_backed_projects() -> list[RunningSessionInfo]:
    """Discover open projects via *.aedt.lock (works when COM ROT is empty)."""
    roots = [
        Path.home() / "Documents",
        Path.home() / "Desktop",
        Path(os.environ.get("USERPROFILE", "")) / "Documents" / "Ansoft",
        Path(os.environ.get("TEMP", "")),
    ]
    # Also parent of common AEDT personal folder
    ansoft = Path.home() / "Documents" / "Ansoft"
    if ansoft.is_dir():
        roots.append(ansoft)

    by_pid: dict[int, RunningSessionInfo] = {}
    seen_locks: set[str] = set()
    for root in roots:
        if not root or not root.exists():
            continue
        try:
            locks = list(root.rglob("*.aedt.lock"))
        except OSError:
            continue
        for lock_file in locks:
            key = str(lock_file.resolve(strict=False)).lower()
            if key in seen_locks:
                continue
            seen_locks.add(key)
            try:
                text = lock_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            values: dict[str, str] = {}
            for line in text.splitlines():
                parsed = _parse_lock_assignment(line)
                if parsed:
                    values.setdefault(parsed[0], parsed[1])
            try:
                pid = int(values.get("DesktopProcessID") or "0")
            except ValueError:
                pid = 0
            if pid <= 0 or not _process_alive(pid):
                continue
            # lock beside project: Foo.aedt.lock -> Foo.aedt
            project_file = lock_file.with_suffix("")
            if project_file.suffix.lower() != ".aedt":
                # Windows: Path('x.aedt.lock').with_suffix('') -> 'x.aedt'
                project_file = Path(str(lock_file)[: -len(".lock")])
            if not project_file.is_file():
                continue
            try:
                listen = int(values.get("ListenPort") or "0") or None
            except ValueError:
                listen = None
            # Parse designs from window title if available later; default empty
            designs: list[OpenDesignInfo] = []
            proj = OpenProjectInfo(
                project_name=project_file.stem,
                project_path=_normalize_path(str(project_file)),
                is_active=True,
                designs=designs,
            )
            existing = by_pid.get(pid)
            if existing is None:
                by_pid[pid] = RunningSessionInfo(
                    process_id=pid,
                    transport="com" if not listen else "grpc",
                    grpc_port=listen if listen and listen > 0 else None,
                    projects=[proj],
                    source="aedt_lock",
                )
            else:
                projects = list(existing.projects) + [proj]
                by_pid[pid] = existing.model_copy(
                    update={
                        "projects": projects,
                        "grpc_port": existing.grpc_port or listen,
                    }
                )
    return list(by_pid.values())


def _enrich_designs_from_window_titles(
    sessions: list[RunningSessionInfo],
) -> list[RunningSessionInfo]:
    """Parse MainWindowTitle: '... - Project - Design - ...'."""
    if os.name != "nt":
        return sessions
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        enum_windows = user32.EnumWindows
        get_window_text = user32.GetWindowTextW
        get_window_text_length = user32.GetWindowTextLengthW
        get_window_thread_process_id = user32.GetWindowThreadProcessId
        is_window_visible = user32.IsWindowVisible

        titles: dict[int, str] = {}
        enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def _callback(hwnd: int, _lparam: int) -> bool:
            if not is_window_visible(hwnd):
                return True
            length = get_window_text_length(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            get_window_text(hwnd, buf, length + 1)
            text = buf.value
            if "Electronics Desktop" not in text:
                return True
            pid = wintypes.DWORD()
            get_window_thread_process_id(hwnd, ctypes.byref(pid))
            titles[int(pid.value)] = text
            return True

        enum_windows(enum_proc_type(_callback), 0)
    except Exception:
        return sessions

    updated: list[RunningSessionInfo] = []
    for sess in sessions:
        title = titles.get(sess.process_id)
        if not title:
            updated.append(sess)
            continue
        # Example: Ansys Electronics Desktop 2023 R2 - Project1 - HFSSDesign1 - 3D Modeler
        parts = [p.strip() for p in title.split(" - ")]
        design_name = None
        project_name = None
        if len(parts) >= 3:
            project_name = parts[1]
            design_name = parts[2]
        projects = list(sess.projects)
        if design_name and projects:
            new_projects = []
            for proj in projects:
                designs = list(proj.designs)
                if not any(d.design_name == design_name for d in designs):
                    designs.append(
                        OpenDesignInfo(design_name=design_name, is_active=True)
                    )
                if project_name and proj.project_name != project_name:
                    # keep path-based name
                    pass
                new_projects.append(
                    proj.model_copy(
                        update={
                            "designs": designs,
                            "is_active": True,
                        }
                    )
                )
            projects = new_projects
        elif design_name and not projects and project_name:
            projects = [
                OpenProjectInfo(
                    project_name=project_name,
                    project_path=None,
                    is_active=True,
                    designs=[OpenDesignInfo(design_name=design_name, is_active=True)],
                )
            ]
        updated.append(sess.model_copy(update={"projects": projects}))
    return updated


def discover_running_sessions(
    *,
    version: str | None = "2023.2",
) -> SessionDiscoveryResult:
    """Discover running AEDT and open projects (locks + COM + process scan)."""
    notes: list[str] = []
    by_pid: dict[int, RunningSessionInfo] = {}

    for sess in _discover_lock_backed_projects():
        by_pid[sess.process_id] = sess
        notes.append(f"lock-backed open project on pid {sess.process_id}")

    for sess in _com_list_sessions(version):
        existing = by_pid.get(sess.process_id)
        if existing is None or (not existing.projects and sess.projects):
            by_pid[sess.process_id] = sess
        elif sess.projects:
            # merge projects
            names = {p.project_path for p in existing.projects}
            merged = list(existing.projects)
            for p in sess.projects:
                if p.project_path not in names:
                    merged.append(p)
            by_pid[sess.process_id] = existing.model_copy(update={"projects": merged})

    for sess in _pyaedt_active_sessions(version):
        existing = by_pid.get(sess.process_id)
        if existing is None:
            by_pid[sess.process_id] = sess
        else:
            if existing.transport == "com" and sess.transport == "grpc":
                by_pid[sess.process_id] = existing.model_copy(
                    update={"transport": "grpc", "grpc_port": sess.grpc_port}
                )

    sessions = sorted(by_pid.values(), key=lambda s: s.process_id)
    sessions = _enrich_designs_from_window_titles(sessions)

    if not sessions:
        notes.append("no running AEDT session detected")
    elif all(not s.projects for s in sessions):
        notes.append(
            "AEDT process(es) found but open project list empty "
            "(save the project once so a .aedt.lock appears, or enable COM/gRPC attach)"
        )

    preferred_pid = None
    preferred_path = None
    preferred_design = None
    for sess in sessions:
        for proj in sess.projects:
            if proj.is_active or preferred_path is None:
                preferred_pid = sess.process_id
                preferred_path = proj.project_path
                active_d = next((d for d in proj.designs if d.is_active), None)
                preferred_design = (
                    active_d.design_name
                    if active_d
                    else (proj.designs[0].design_name if proj.designs else None)
                )
                if proj.is_active:
                    break
        if preferred_path and any(p.is_active for p in sess.projects):
            break

    return SessionDiscoveryResult(
        sessions=sessions,
        any_gui_session=len(sessions) > 0,
        preferred_process_id=preferred_pid,
        preferred_project_path=preferred_path,
        preferred_design_name=preferred_design,
        notes=notes,
    )


def find_open_project(
    discovery: SessionDiscoveryResult,
    project_path: str | Path,
) -> tuple[RunningSessionInfo, OpenProjectInfo] | None:
    """Match an absolute project path against open sessions.

    Prefer exact path equality. Same project *name* only matches when the open
    entry has no path, or lives in the same directory (avoids binding a copy
    of Example1.aedt to another folder's Example1).
    """
    target = _normalize_path(str(project_path))
    if not target:
        return None
    target_l = target.lower()
    target_path = Path(target)
    target_stem = target_path.stem.lower()
    try:
        target_parent = str(target_path.parent.resolve(strict=False)).lower()
    except Exception:
        target_parent = str(target_path.parent).lower()
    for sess in discovery.sessions:
        for proj in sess.projects:
            p = _normalize_path(proj.project_path)
            if p and p.lower() == target_l:
                return sess, proj
            # COM may report directory + name separately
            if p and proj.project_name:
                combined = str(
                    (Path(p) / f"{proj.project_name}.aedt").resolve(strict=False)
                ).lower()
                if combined == target_l:
                    return sess, proj
            if proj.project_name.lower() != target_stem:
                continue
            if not p:
                return sess, proj
            try:
                open_parent = str(Path(p).resolve(strict=False)).lower()
                if Path(p).suffix.lower() == ".aedt":
                    open_parent = str(Path(p).parent.resolve(strict=False)).lower()
            except Exception:
                open_parent = str(Path(p).parent if Path(p).suffix else Path(p)).lower()
            if open_parent == target_parent:
                return sess, proj
    return None


@dataclass
class AttachTarget:
    process_id: int
    transport: SessionTransport
    grpc_port: int | None = None
    project_path: str | None = None
    project_name: str | None = None
    design_name: str | None = None
    non_graphical: bool = False
    new_desktop: bool = False
    close_on_exit: bool = False
    notes: list[str] = field(default_factory=list)
