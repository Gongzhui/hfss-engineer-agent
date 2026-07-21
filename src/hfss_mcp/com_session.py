"""COM session helpers ported from first-party ``hfss-cli`` attached_session.

Attach model:
- COM ROT / Dispatch → ``GetAppDesktop()`` → ``oDesktop.RunScript(...)``
- No UI mouse automation.

Also supports *ensuring* a graphical Desktop that owns an open project so MCP
can attach and the user can see the GUI.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from hfss_mcp.errors import AdapterError


def normalize_aedt_version(version: str | None) -> str | None:
    if not version:
        return None
    text = str(version).strip()
    if not text:
        return None
    # 2023.2 / 23.2 / 232
    if len(text) == 3 and text.isdigit():
        return f"20{text[:2]}.{text[2]}"
    if text.count(".") == 1:
        major, minor = text.split(".", 1)
        if len(major) == 2 and major.isdigit():
            return f"20{major}.{minor}"
        return text
    return text


def desktop_prog_id(version: str | None = None) -> str:
    norm = normalize_aedt_version(version)
    if norm:
        return f"Ansoft.ElectronicsDesktop.{norm}"
    return "Ansoft.ElectronicsDesktop"


def load_win32_client() -> Any:
    try:
        import win32com.client as client  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise AdapterError(
            "win32com is required for COM attach to AEDT GUI sessions",
            code="missing_pywin32",
            details={"reason": str(exc)},
        ) from exc
    return client


def iter_rot_desktops(client: Any, version: str | None = None) -> list[Any]:
    """Enumerate Electronics Desktop objects registered in the COM ROT."""
    if os.name != "nt":
        return []
    try:
        import pythoncom  # type: ignore
    except Exception:
        return []
    normalized = normalize_aedt_version(version)
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
    desktops: list[Any] = []
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
            display_name = str(moniker.GetDisplayName(bind_context, None))
        except Exception:
            continue
        if "ElectronicsDesktop" not in display_name:
            continue
        if normalized and f".{normalized}" not in display_name:
            # moniker looks like ElectronicsDesktop.2023.2.0:PID
            short = normalized  # 2023.2
            if short not in display_name:
                continue
        try:
            unknown = rot.GetObject(moniker)
            dispatch = client.Dispatch(unknown.QueryInterface(pythoncom.IID_IDispatch))
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
        desktops.append(desktop)
    return desktops


def get_desktop(
    *,
    version: str | None = None,
    process_id: int | None = None,
    create_if_missing: bool = False,
) -> Any:
    """Return an oDesktop for an existing COM session, optionally creating one.

    If ``process_id`` is set, only a matching ROT desktop is accepted (no silent
    fallback to a different PID). If unset, prefer any ROT desktop; optionally
    ``Dispatch`` a new graphical instance when ``create_if_missing``.
    """
    client = load_win32_client()
    requested = int(process_id or 0)
    for desktop in iter_rot_desktops(client, version):
        try:
            pid = int(desktop.GetProcessID())
        except Exception:
            continue
        if requested and pid != requested:
            continue
        return desktop
    if requested:
        raise AdapterError(
            f"No COM-reachable AEDT Desktop for PID {requested}. "
            "Only COM-registered (script-launched) Desktops can be attached.",
            code="aedt_com_pid_unreachable",
            details={"process_id": requested, "version": version},
        )
    if not create_if_missing:
        raise AdapterError(
            "No COM-registered AEDT Desktop is running",
            code="aedt_com_no_desktop",
            details={"version": version},
        )
    try:
        app = client.Dispatch(desktop_prog_id(version))
        return app.GetAppDesktop()
    except Exception as exc:
        raise AdapterError(
            f"Failed to start graphical AEDT via COM: {exc}",
            code="aedt_com_launch_failed",
            details={"reason": str(exc), "prog_id": desktop_prog_id(version)},
        ) from exc


def desktop_process_id(desktop: Any) -> int:
    return int(desktop.GetProcessID())


def list_com_projects(desktop: Any) -> list[dict[str, Any]]:
    try:
        names = [str(x) for x in (desktop.GetProjectList() or [])]
    except Exception as exc:
        raise AdapterError(
            f"Failed to list projects on COM desktop: {exc}",
            code="aedt_com_list_failed",
            details={"reason": str(exc)},
        ) from exc
    items: list[dict[str, Any]] = []
    active_name = None
    try:
        active = desktop.GetActiveProject()
        if active:
            active_name = str(active.GetName())
    except Exception:
        active = None
    for name in names:
        try:
            proj = desktop.SetActiveProject(name)
        except Exception:
            continue
        path = ""
        try:
            path = str(proj.GetPath() or "")
        except Exception:
            path = ""
        designs: list[str] = []
        try:
            designs = [str(x) for x in (proj.GetTopDesignList() or [])]
        except Exception:
            designs = []
        project_file = ""
        if path:
            project_file = str((Path(path) / f"{name}.aedt").resolve(strict=False))
        items.append(
            {
                "process_id": desktop_process_id(desktop),
                "project_name": name,
                "project_path": path,
                "project_file": project_file,
                "designs": designs,
                "is_active_project": name == active_name,
                "source": "com_rot",
            }
        )
    if active_name:
        try:
            desktop.SetActiveProject(active_name)
        except Exception:
            pass
    return items


def find_com_project(
    *,
    project_path: Path | None = None,
    project_name: str | None = None,
    version: str | None = None,
) -> tuple[Any, dict[str, Any]] | None:
    """Find (desktop, project_info) for an open project on a COM desktop."""
    client = load_win32_client()
    target_stem = project_path.stem if project_path else None
    target_name = (project_name or target_stem or "").strip()
    target_file = (
        str(project_path.resolve(strict=False)).lower() if project_path else None
    )
    for desktop in iter_rot_desktops(client, version):
        for item in list_com_projects(desktop):
            name = str(item.get("project_name") or "")
            file_path = str(item.get("project_file") or "").lower()
            if target_file and file_path and file_path == target_file:
                return desktop, item
            if target_name and name == target_name:
                return desktop, item
            if target_stem and name == target_stem:
                return desktop, item
    return None


def open_project_on_desktop(
    desktop: Any,
    project_path: Path,
    design_name: str | None = None,
) -> dict[str, Any]:
    """Open (or activate) a project on an existing COM desktop."""
    path = Path(project_path).resolve(strict=False)
    if not path.is_file():
        raise AdapterError(
            f"project file not found: {path}",
            code="project_not_found",
            details={"path": str(path)},
        )
    name = path.stem
    # Already open?
    try:
        open_names = [str(x) for x in (desktop.GetProjectList() or [])]
    except Exception:
        open_names = []
    if name in open_names:
        proj = desktop.SetActiveProject(name)
    else:
        try:
            # Prefer OpenProject; path may be file or directory depending on API
            try:
                proj = desktop.OpenProject(str(path))
            except Exception:
                proj = desktop.OpenProject(str(path.with_suffix("")))
        except Exception as exc:
            msg = str(exc)
            locked = "lock" in msg.lower() or "already" in msg.lower()
            raise AdapterError(
                f"Failed to open project in GUI Desktop: {exc}",
                code="project_open_failed" if not locked else "project_locked",
                details={
                    "path": str(path),
                    "reason": msg,
                    "hint": (
                        "Close the project in other AEDT windows (non-COM GUI) "
                        "so MCP can open it in a COM-registered graphical Desktop."
                        if locked
                        else None
                    ),
                },
            ) from exc
    if design_name:
        try:
            proj.SetActiveDesign(design_name)
        except Exception as exc:
            raise AdapterError(
                f"Failed to activate design {design_name!r}: {exc}",
                code="design_activate_failed",
                details={"design": design_name, "reason": str(exc)},
            ) from exc
    designs: list[str] = []
    try:
        designs = [str(x) for x in (proj.GetTopDesignList() or [])]
    except Exception:
        designs = []
    return {
        "process_id": desktop_process_id(desktop),
        "project_name": name,
        "project_path": str(path.parent),
        "project_file": str(path),
        "designs": designs,
        "design": design_name,
        "source": "com_open",
    }


def ensure_graphical_project(
    *,
    project_path: Path,
    design_name: str,
    version: str | None = None,
    process_id: int | None = None,
) -> dict[str, Any]:
    """Ensure project is open in a COM-registered *graphical* Desktop.

    Returns session info including ``process_id`` for subsequent PyAEDT attach
    or ``RunScript`` calls. Never closes the Desktop.
    """
    path = Path(project_path)
    # 1) Prefer already-open COM project
    found = find_com_project(project_path=path, version=version)
    if found is not None:
        desktop, item = found
        if design_name:
            try:
                proj = desktop.SetActiveProject(str(item["project_name"]))
                proj.SetActiveDesign(design_name)
            except Exception:
                pass
        item = dict(item)
        item["design"] = design_name
        item["process_id"] = desktop_process_id(desktop)
        return item

    # 2) Attach to requested PID if COM-reachable, then open
    if process_id:
        try:
            desktop = get_desktop(
                version=version, process_id=process_id, create_if_missing=False
            )
            return open_project_on_desktop(desktop, path, design_name)
        except AdapterError:
            pass

    # 3) Launch new graphical COM Desktop and open project
    desktop = get_desktop(version=version, process_id=None, create_if_missing=True)
    return open_project_on_desktop(desktop, path, design_name)


def _ironpython_runner_script(request_path: Path, result_path: Path) -> str:
    """IronPython 2.7-compatible runner (same strategy as hfss-cli)."""
    request_literal = "json.loads(%r)" % json.dumps(str(request_path), ensure_ascii=True)
    result_literal = "json.loads(%r)" % json.dumps(str(result_path), ensure_ascii=True)
    return "\n".join(
        [
            "import json",
            "import traceback",
            "",
            "request_path = %s" % request_literal,
            "result_path = %s" % result_literal,
            "result = {}",
            "output = {}",
            "previous_project_name = None",
            "previous_design_name = None",
            "try:",
            "    active_project = oDesktop.GetActiveProject()",
            "    if active_project:",
            "        previous_project_name = active_project.GetName()",
            "        try:",
            "            previous_design = active_project.GetActiveDesign()",
            "            if previous_design:",
            "                previous_design_name = previous_design.GetName()",
            "        except Exception:",
            "            previous_design_name = None",
            "except Exception:",
            "    previous_project_name = None",
            "try:",
            "    handle = open(request_path, 'r')",
            "    try:",
            "        payload = json.load(handle)",
            "    finally:",
            "        handle.close()",
            "    oProject = oDesktop.SetActiveProject(payload['project_name'])",
            "    oDesign = oProject.SetActiveDesign(payload['design'])",
            "    try:",
            "        oEditor = oDesign.SetActiveEditor('3D Modeler')",
            "    except Exception:",
            "        oEditor = None",
            "    globals_dict = {",
            "        'oDesktop': oDesktop,",
            "        'oProject': oProject,",
            "        'oDesign': oDesign,",
            "        'oEditor': oEditor,",
            "        'result': result,",
            "    }",
            "    exec payload.get('script_text', '') in globals_dict, globals_dict",
            "    result = globals_dict.get('result', result)",
            "    output = {'ok': True, 'result': result}",
            "except Exception:",
            "    output = {'ok': False, 'error': traceback.format_exc()}",
            "finally:",
            "    if previous_project_name:",
            "        try:",
            "            restore_project = oDesktop.SetActiveProject(previous_project_name)",
            "            if previous_design_name:",
            "                restore_project.SetActiveDesign(previous_design_name)",
            "        except Exception:",
            "            pass",
            "handle = open(result_path, 'w')",
            "try:",
            "    json.dump(output, handle)",
            "finally:",
            "    handle.close()",
            "",
        ]
    )


def execute_run_script(
    *,
    project_name: str,
    design_name: str,
    script_text: str,
    version: str | None = None,
    process_id: int | None = None,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Run IronPython ``script_text`` inside the GUI via ``oDesktop.RunScript``."""
    if not project_name or not design_name:
        raise AdapterError(
            "project_name and design_name are required for RunScript",
            code="run_script_args",
        )
    temp_root = Path(tempfile.mkdtemp(prefix="hfss-mcp-runscript-"))
    request_path = temp_root / "request.json"
    result_path = temp_root / "result.json"
    runner_path = temp_root / "runner.py"
    try:
        request_path.write_text(
            json.dumps(
                {
                    "project_name": project_name,
                    "design": design_name,
                    "script_text": script_text,
                },
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        runner_path.write_text(
            _ironpython_runner_script(request_path, result_path), encoding="ascii"
        )
        desktop = get_desktop(
            version=version,
            process_id=process_id,
            create_if_missing=False,
        )
        current_pid = desktop_process_id(desktop)
        if process_id and int(process_id) != current_pid:
            raise AdapterError(
                f"Attached session expects AEDT PID {process_id}, "
                f"but the reachable desktop is PID {current_pid}.",
                code="aedt_pid_mismatch",
                details={"expected": process_id, "actual": current_pid},
            )
        result_code = desktop.RunScript(str(runner_path))
        if int(result_code) != 0:
            raise AdapterError(
                f"AEDT RunScript failed with code {result_code}",
                code="run_script_failed",
                details={"result_code": int(result_code)},
            )
        deadline = time.time() + max(float(timeout_seconds), 1.0)
        while time.time() < deadline:
            if result_path.is_file():
                break
            time.sleep(0.1)
        if not result_path.is_file():
            raise AdapterError(
                "AEDT RunScript did not produce a result file before timeout",
                code="run_script_timeout",
                details={"timeout_seconds": timeout_seconds},
            )
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not payload.get("ok", False):
            raise AdapterError(
                str((payload or {}).get("error") or "RunScript failed"),
                code="run_script_error",
                details={"raw": payload},
            )
        result = payload.get("result")
        return result if isinstance(result, dict) else {"value": result}
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
