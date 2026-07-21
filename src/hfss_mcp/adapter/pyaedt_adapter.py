"""PyAEDT-backed adapter for exclusive worker use.

Designed for one process / one AEDT desktop / one project workspace copy.
"""

from __future__ import annotations

import shutil
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

from hfss_mcp.domain import (
    ApplyResult,
    CancelResult,
    DesignSnapshot,
    ParameterDiffItem,
    ParameterValue,
    ParameterVector,
    SolveHandle,
    SolveState,
    SolveStatus,
    utc_now_iso,
)
from hfss_mcp.environment import EnvironmentStatus, inspect_environment
from hfss_mcp.errors import AdapterError, ReadbackMismatchError, RevisionConflictError
from hfss_mcp.ids import new_id, sha256_hex
from hfss_mcp.metrics import extract_metrics as extract_metrics_real
from hfss_mcp.metrics_spec import MetricSpec


class PyAedtAdapter:
    """Semantic adapter over PyAEDT Hfss.

    Supports:
    - **attach** to a user GUI session (``new_desktop=False``, never close user Desktop)
    - **new** exclusive Desktop for unattended workers
    """

    CANCEL_LIMITATION = (
        "Cancel only terminates AEDT processes owned by this adapter when it launched "
        "them (new_desktop). User GUI sessions are never closed."
    )

    def __init__(
        self,
        *,
        version: str | None = "2023.2",
        non_graphical: bool = True,
        new_desktop: bool = True,
        close_on_exit: bool = True,
        aedt_process_id: int | None = None,
        grpc_port: int | None = None,
        machine: str = "localhost",
        hfss: Any | None = None,
        owned_pids: list[int] | None = None,
    ) -> None:
        self._version = version
        self._non_graphical = non_graphical
        self._new_desktop = new_desktop
        # Never close desktop when attaching to an external process
        if aedt_process_id is not None or (not new_desktop and hfss is None):
            close_on_exit = False
            non_graphical = False if non_graphical and aedt_process_id else non_graphical
        self._close_on_exit = close_on_exit
        self._aedt_process_id = aedt_process_id
        self._grpc_port = grpc_port
        self._machine = machine
        self._hfss = hfss
        self._owns_desktop = hfss is None and new_desktop and aedt_process_id is None
        self._lock = threading.RLock()
        self._revision = "uninitialized"
        self._solves: dict[str, dict[str, Any]] = {}
        self._project_path: Path | None = None
        self._mutation_count = 0
        self._desktop_pid: int | None = aedt_process_id
        self._owned_pids: set[int] = set(owned_pids or [])
        self._aedt_process_ids_before: set[int] = set()
        self._attached_to_user = bool(aedt_process_id is not None or not new_desktop)
        self._user_desktop: Any | None = None

    def inspect_environment(self) -> EnvironmentStatus:
        return inspect_environment()

    def _list_ansysedt_pids(self) -> set[int]:
        try:
            import subprocess

            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq ansysedt.exe", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=15,
            )
            pids: set[int] = set()
            for line in (result.stdout or "").splitlines():
                # "ansysedt.exe","1234",...
                parts = [p.strip().strip('"') for p in line.split(",")]
                if len(parts) >= 2 and parts[0].lower().startswith("ansysedt"):
                    try:
                        pids.add(int(parts[1]))
                    except ValueError:
                        continue
            return pids
        except Exception:
            return set()

    def _ensure_hfss(self, project_path: Path, design_name: str) -> Any:
        if self._hfss is not None:
            # Switch active project/design if needed
            self._activate_project_design(project_path, design_name)
            return self._hfss
        import importlib

        hfss_cls: Any = None
        last_err: Exception | None = None
        for module_name in ("ansys.aedt.core", "pyaedt"):
            try:
                mod = importlib.import_module(module_name)
                hfss_cls = mod.Hfss
                break
            except (ImportError, AttributeError) as exc:
                last_err = exc
        if hfss_cls is None:
            raise AdapterError(
                "PyAEDT is not importable",
                code="pyaedt_import_error",
                details={"reason": str(last_err)},
            )
        before = self._list_ansysedt_pids()
        self._aedt_process_ids_before = before

        attach = self._aedt_process_id is not None or not self._new_desktop
        # When attaching to a live GUI session, do NOT pass project= path into the
        # constructor — that tries to re-open the file and hits "Project is locked".
        # Connect to the Desktop first, then activate the already-open project by name.
        kwargs: dict[str, Any] = {
            "version": self._version,
            "non_graphical": False if attach else self._non_graphical,
            "new_desktop": False if attach else self._new_desktop,
            "close_on_exit": False if attach else self._close_on_exit,
        }
        if not attach:
            if project_path:
                kwargs["project"] = str(project_path)
            if design_name:
                kwargs["design"] = design_name
        if self._aedt_process_id is not None:
            kwargs["aedt_process_id"] = int(self._aedt_process_id)
            kwargs["new_desktop"] = False
            kwargs["close_on_exit"] = False
            kwargs["non_graphical"] = False
        if self._grpc_port is not None and self._grpc_port > 0:
            kwargs["port"] = int(self._grpc_port)
            kwargs["machine"] = self._machine
            kwargs["new_desktop"] = False
            kwargs["close_on_exit"] = False

        # Drop None values PyAEDT may not like
        kwargs = {k: v for k, v in kwargs.items() if v is not None}

        try:
            # Prefer Desktop-level attach for GUI, then wrap as Hfss on active design
            if attach:
                self._hfss = self._attach_hfss_to_running_desktop(
                    hfss_cls, project_path, design_name, kwargs
                )
            else:
                self._hfss = hfss_cls(**kwargs)
            self._owns_desktop = bool(kwargs.get("new_desktop", False)) and (
                self._aedt_process_id is None
            )
            self._attached_to_user = not self._owns_desktop
        except Exception as exc:
            raise AdapterError(
                f"failed to attach/open AEDT session: {exc}",
                code="aedt_session_error",
                details={
                    "reason": str(exc),
                    "project": str(project_path),
                    "attach_pid": self._aedt_process_id,
                    "port": self._grpc_port,
                    "new_desktop": kwargs.get("new_desktop"),
                },
            ) from exc

        after = self._list_ansysedt_pids()
        if self._owns_desktop:
            self._owned_pids |= after - before
        # Record process id for diagnostics (never kill user PID on cancel)
        try:
            pid = getattr(self._hfss, "aedt_process_id", None)
            if pid:
                self._desktop_pid = int(pid)
                if self._owns_desktop:
                    self._owned_pids.add(int(pid))
            desk = getattr(self._hfss, "desktop_class", None)
            if desk is not None:
                pid2 = getattr(desk, "aedt_process_id", None)
                if pid2:
                    self._desktop_pid = int(pid2)
                    if self._owns_desktop:
                        self._owned_pids.add(int(pid2))
        except Exception:
            pass
        self._activate_project_design(project_path, design_name)
        return self._hfss

    def _attach_hfss_to_running_desktop(
        self,
        hfss_cls: Any,
        project_path: Path,
        design_name: str,
        base_kwargs: dict[str, Any],
    ) -> Any:
        """Attach without reopening the locked .aedt file."""
        import importlib

        errors: list[str] = []

        # Strategy 0: COM Desktop by PID (hfss-cli style) — proves process is reachable
        if self._aedt_process_id is not None:
            try:
                from hfss_mcp.com_session import get_desktop

                com_desk = get_desktop(
                    version=self._version,
                    process_id=int(self._aedt_process_id),
                    create_if_missing=False,
                )
                self._user_desktop = com_desk
            except Exception as com_exc:
                errors.append(f"com:{com_exc}")

        # Strategy 1: Hfss without project= (session only)
        try:
            # Never pass lock-file ListenPort as gRPC — only explicit grpc_port
            kwargs = dict(base_kwargs)
            if "port" in kwargs and self._grpc_port is None:
                kwargs.pop("port", None)
            hfss = hfss_cls(**kwargs)
            self._activate_on_app(hfss, project_path, design_name)
            return hfss
        except Exception as first_exc:
            errors.append(f"hfss:{first_exc}")
            last: Exception = first_exc

        # Strategy 2: Desktop attach then Hfss(specified_desktop / existing)
        try:
            desktop_cls = None
            for module_name in ("ansys.aedt.core", "pyaedt"):
                try:
                    mod = importlib.import_module(module_name)
                    desktop_cls = getattr(mod, "Desktop", None)
                    if desktop_cls is not None:
                        break
                except Exception:
                    continue
            if desktop_cls is None:
                raise last
            desk_kwargs = {
                k: v
                for k, v in base_kwargs.items()
                if k
                in {
                    "version",
                    "non_graphical",
                    "new_desktop",
                    "close_on_exit",
                    "aedt_process_id",
                    "port",
                    "machine",
                }
            }
            if self._grpc_port is None:
                desk_kwargs.pop("port", None)
            desktop = desktop_cls(**desk_kwargs)
            try:
                hfss = hfss_cls(
                    project=None,
                    design=design_name or None,
                    version=base_kwargs.get("version"),
                    new_desktop=False,
                    close_on_exit=False,
                    non_graphical=False,
                    aedt_process_id=self._aedt_process_id,
                )
            except TypeError:
                hfss = hfss_cls(**{k: v for k, v in base_kwargs.items() if k != "port" or self._grpc_port})
            self._activate_on_app(hfss, project_path, design_name)
            self._user_desktop = desktop
            return hfss
        except Exception as second_exc:
            errors.append(f"desktop:{second_exc}")
            raise AdapterError(
                f"GUI attach failed: {second_exc}",
                code="aedt_attach_failed",
                details={
                    "errors": errors,
                    "pid": self._aedt_process_id,
                    "port": self._grpc_port,
                },
            ) from second_exc

    def _activate_on_app(self, app: Any, project_path: Path, design_name: str) -> None:
        target_name = project_path.stem if project_path else None
        try:
            proj_list = list(getattr(app, "project_list", None) or [])
            open_names = {str(p) for p in proj_list}
            if target_name and target_name in open_names:
                set_active = getattr(app, "set_active_project", None)
                if callable(set_active):
                    set_active(target_name)
            elif target_name and proj_list:
                # Fuzzy: match ignoring case
                for name in open_names:
                    if name.lower() == target_name.lower():
                        set_active = getattr(app, "set_active_project", None)
                        if callable(set_active):
                            set_active(name)
                        break
            if design_name:
                set_design = getattr(app, "set_active_design", None)
                if callable(set_design):
                    with suppress(Exception):
                        set_design(design_name)
        except Exception:
            pass

    def _activate_project_design(self, project_path: Path, design_name: str) -> None:
        if self._hfss is None:
            return
        # Prefer matching already-open project by name — never force-load locked file
        # when attached to a user session.
        try:
            self._activate_on_app(self._hfss, project_path, design_name)
            if self._attached_to_user:
                return
            target_name = project_path.stem if project_path else None
            proj_list = list(getattr(self._hfss, "project_list", None) or [])
            if target_name and proj_list:
                open_names = {str(p) for p in proj_list}
                if target_name not in open_names and project_path.is_file():
                    loader = getattr(self._hfss, "load_project", None)
                    if callable(loader):
                        with suppress(Exception):
                            loader(str(project_path), set_active=True)
        except Exception:
            pass

    def owned_aedt_pids(self) -> list[int]:
        return sorted(self._owned_pids)

    def _compute_revision(self) -> str:
        names = sorted(self._variable_names())
        parts = []
        for name in names:
            val = self._read_one(name)
            parts.append(f"{name}={val.value}{val.unit}")
        payload = f"{self._project_path}|{self._mutation_count}|{'|'.join(parts)}"
        return sha256_hex(payload)[:16]

    def _variable_names(self) -> list[str]:
        assert self._hfss is not None
        vm = self._hfss.variable_manager
        independent = getattr(vm, "independent_design_variables", None)
        if isinstance(independent, dict):
            return list(independent.keys())
        variables = getattr(vm, "variables", None)
        if isinstance(variables, dict):
            return list(variables.keys())
        if hasattr(vm, "design_variables") and isinstance(vm.design_variables, dict):
            return list(vm.design_variables.keys())
        return []

    def _parse_expression(self, name: str, expression: str) -> ParameterValue:
        import re

        text = str(expression).strip()
        parts = text.split()
        if len(parts) >= 2:
            try:
                return ParameterValue(
                    name=name, value=float(parts[0]), unit=" ".join(parts[1:])
                )
            except ValueError:
                pass
        glued = re.match(
            r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)([A-Za-z_%µμ]+)$",
            text,
        )
        if glued:
            return ParameterValue(
                name=name, value=float(glued.group(1)), unit=glued.group(2)
            )
        try:
            return ParameterValue(name=name, value=float(text), unit="1")
        except ValueError as exc:
            raise AdapterError(
                f"cannot parse variable expression for {name!r}: {expression!r}",
                code="variable_parse_error",
                details={"name": name, "expression": expression},
            ) from exc

    def _read_one(self, name: str) -> ParameterValue:
        assert self._hfss is not None
        vm = self._hfss.variable_manager
        if hasattr(vm, "get_expression"):
            expr = vm.get_expression(name)
        else:
            independent = getattr(vm, "independent_design_variables", {})
            if name not in independent:
                raise AdapterError(
                    f"variable {name!r} not found",
                    code="variable_not_found",
                    details={"name": name},
                )
            expr = independent[name]
        return self._parse_expression(name, str(expr))

    def attach_project(self, project_path: Path, design_name: str) -> DesignSnapshot:
        with self._lock:
            path = Path(project_path)
            # Attach mode may target a project already open in GUI even if path
            # resolution is imperfect; only require the file when starting a new Desktop.
            if (
                not path.is_file()
                and self._hfss is None
                and self._new_desktop
                and self._aedt_process_id is None
            ):
                raise AdapterError(
                    f"project file not found: {path}",
                    code="project_not_found",
                    details={"path": str(path)},
                )
            self._ensure_hfss(path, design_name)
            self._project_path = path
            self._mutation_count = 0
            self._revision = self._compute_revision()
            return self.snapshot()

    def snapshot(self) -> DesignSnapshot:
        with self._lock:
            if self._hfss is None or self._project_path is None:
                raise AdapterError("no project attached", code="not_attached")
            variables = {name: self._read_one(name) for name in self._variable_names()}
            setups = list(getattr(self._hfss, "setup_names", []) or [])
            return DesignSnapshot(
                project_path=str(self._project_path),
                project_name=str(
                    getattr(self._hfss, "project_name", self._project_path.stem)
                ),
                design_name=str(getattr(self._hfss, "design_name", "")),
                revision=self._revision,
                variables=variables,
                setups=setups,
                captured_at=utc_now_iso(),
            )

    def read_variables(self, names: list[str]) -> dict[str, ParameterValue]:
        with self._lock:
            if self._hfss is None:
                raise AdapterError("no project attached", code="not_attached")
            return {name: self._read_one(name) for name in names}

    def apply_parameter_vector(
        self,
        vector: ParameterVector,
        *,
        expected_revision: str,
    ) -> ApplyResult:
        with self._lock:
            if self._hfss is None:
                raise AdapterError("no project attached", code="not_attached")
            if expected_revision != self._revision:
                raise RevisionConflictError(
                    "expected revision does not match current design revision",
                    expected=expected_revision,
                    actual=self._revision,
                )
            before = {item.name: self._read_one(item.name) for item in vector.values}
            revision_before = self._revision
            vm = self._hfss.variable_manager
            for item in vector.values:
                expression = (
                    f"{item.value}{item.unit}" if item.unit != "1" else str(item.value)
                )
                if hasattr(vm, "set_variable"):
                    vm.set_variable(item.name, expression=expression)
                else:
                    self._hfss[item.name] = expression

            mismatches: list[dict[str, object]] = []
            readback: dict[str, ParameterValue] = {}
            for item in vector.values:
                actual = self._read_one(item.name)
                readback[item.name] = actual
                # unit may normalize (mm vs mm); value compare with tolerance
                if abs(actual.value - item.value) > 1e-6:
                    mismatches.append(
                        {
                            "name": item.name,
                            "expected": item.value,
                            "actual": actual.value,
                            "expected_unit": item.unit,
                            "actual_unit": actual.unit,
                        }
                    )
                elif actual.unit.replace(" ", "").lower() != item.unit.replace(" ", "").lower():
                    # allow mm vs millimeter only if values match; else mismatch
                    if actual.unit.lower() not in {item.unit.lower(), item.unit.lower() + "s"}:
                        mismatches.append(
                            {
                                "name": item.name,
                                "expected_unit": item.unit,
                                "actual_unit": actual.unit,
                            }
                        )
            if mismatches:
                for name, prev in before.items():
                    expression = (
                        f"{prev.value}{prev.unit}" if prev.unit != "1" else str(prev.value)
                    )
                    try:
                        if hasattr(vm, "set_variable"):
                            vm.set_variable(name, expression=expression)
                        else:
                            self._hfss[name] = expression
                    except Exception:
                        pass
                raise ReadbackMismatchError(
                    "parameter read-back did not match written values",
                    mismatches=mismatches,
                )

            self._mutation_count += 1
            self._revision = self._compute_revision()
            diff = [
                ParameterDiffItem(
                    name=item.name,
                    before_value=before[item.name].value,
                    after_value=item.value,
                    unit=item.unit,
                    changed=before[item.name].value != item.value
                    or before[item.name].unit != item.unit,
                )
                for item in vector.values
            ]
            # Persist project after mutation
            try:
                if hasattr(self._hfss, "save_project"):
                    self._hfss.save_project()
            except Exception:
                pass
            return ApplyResult(
                ok=True,
                revision_before=revision_before,
                revision_after=self._revision,
                diff=diff,
                readback=readback,
            )

    def validate_design(self, setup: str, sweep: str | None = None) -> dict[str, object]:
        with self._lock:
            if self._hfss is None:
                raise AdapterError("no project attached", code="not_attached")
            setups = list(getattr(self._hfss, "setup_names", []) or [])
            if setup not in setups:
                return {
                    "ok": False,
                    "setup": setup,
                    "sweep": sweep,
                    "errors": [f"setup {setup!r} not found; known={setups}"],
                }
            return {"ok": True, "setup": setup, "sweep": sweep, "errors": []}

    # --- Setup CRUD (full property bag + sweeps) ---------------------------------

    def _require_hfss(self) -> Any:
        if self._hfss is None:
            raise AdapterError("no project attached", code="not_attached")
        return self._hfss

    def _get_setup_object(self, name: str) -> Any:
        hfss = self._require_hfss()
        getter = getattr(hfss, "get_setup", None)
        setup = None
        if callable(getter):
            try:
                setup = getter(name)
            except Exception:
                setup = None
        if setup is None:
            for item in getattr(hfss, "setups", []) or []:
                if str(getattr(item, "name", "")) == name:
                    setup = item
                    break
        if setup is None:
            known = list(getattr(hfss, "setup_names", []) or [])
            raise AdapterError(
                f"setup not found: {name}",
                code="setup_not_found",
                details={"name": name, "known": known},
            )
        return setup

    def _serialize_setup(self, setup: Any) -> dict[str, Any]:
        from hfss_mcp.setup_ops import json_safe

        name = str(getattr(setup, "name", "") or "")
        props = json_safe(getattr(setup, "props", None) or {})
        setup_type = None
        for attr in ("setuptype", "setup_type", "solution_type"):
            val = getattr(setup, attr, None)
            if val is not None:
                setup_type = str(val)
                break
        sweeps: list[dict[str, Any]] = []
        for sweep in getattr(setup, "sweeps", []) or []:
            sweeps.append(
                {
                    "name": str(getattr(sweep, "name", "") or ""),
                    "props": json_safe(getattr(sweep, "props", None) or {}),
                }
            )
        return {
            "name": name,
            "setup_type": setup_type,
            "props": props if isinstance(props, dict) else {},
            "sweep_count": len(sweeps),
            "sweeps": sweeps,
        }

    def list_setups(self) -> list[dict[str, Any]]:
        with self._lock:
            hfss = self._require_hfss()
            items: list[dict[str, Any]] = []
            for setup in getattr(hfss, "setups", []) or []:
                items.append(self._serialize_setup(setup))
            if not items:
                for name in list(getattr(hfss, "setup_names", []) or []):
                    try:
                        items.append(self._serialize_setup(self._get_setup_object(str(name))))
                    except AdapterError:
                        items.append(
                            {
                                "name": str(name),
                                "setup_type": None,
                                "props": {},
                                "sweep_count": 0,
                                "sweeps": [],
                            }
                        )
            return items

    def get_setup(self, name: str) -> dict[str, Any]:
        with self._lock:
            return self._serialize_setup(self._get_setup_object(name))

    def create_setup(
        self,
        *,
        name: str,
        setup_type: str | None = None,
        properties: dict[str, Any] | None = None,
        sweeps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            hfss = self._require_hfss()
            known = list(getattr(hfss, "setup_names", []) or [])
            if name in known:
                raise AdapterError(
                    f"setup already exists: {name}",
                    code="setup_exists",
                    details={"name": name},
                )
            kwargs = dict(properties or {})
            try:
                created = hfss.create_setup(
                    name=name,
                    setup_type=setup_type,
                    **kwargs,
                )
            except TypeError:
                # older signature without setup_type kw
                created = hfss.create_setup(name, **kwargs)
            except Exception as exc:
                raise AdapterError(
                    f"failed to create setup {name!r}: {exc}",
                    code="setup_create_failed",
                    details={"reason": str(exc), "properties": kwargs},
                ) from exc
            if created in (None, False):
                raise AdapterError(
                    f"failed to create setup {name!r}",
                    code="setup_create_failed",
                )
            # Apply props again via update for keys create_setup may ignore
            if kwargs:
                try:
                    setup_obj = self._get_setup_object(name)
                    updater = getattr(setup_obj, "update", None)
                    if callable(updater):
                        updater(properties=kwargs)
                except Exception:
                    pass
            for sw in sweeps or []:
                self._create_sweep_unlocked(setup_name=name, sweep=sw)
            try:
                if hasattr(hfss, "save_project"):
                    hfss.save_project()
            except Exception:
                pass
            return self._serialize_setup(self._get_setup_object(name))

    def update_setup(
        self,
        *,
        name: str,
        properties: dict[str, Any],
        new_name: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            setup = self._get_setup_object(name)
            props = dict(properties or {})
            if new_name:
                props["Name"] = new_name
            if not props:
                raise AdapterError(
                    "no setup properties provided to update",
                    code="setup_update_empty",
                )
            updater = getattr(setup, "update", None)
            if not callable(updater):
                raise AdapterError(
                    "setup object does not support update()",
                    code="setup_update_unsupported",
                )
            try:
                ok = updater(properties=props)
            except TypeError:
                ok = updater(props)
            except Exception as exc:
                raise AdapterError(
                    f"failed to update setup {name!r}: {exc}",
                    code="setup_update_failed",
                    details={"reason": str(exc), "properties": props},
                ) from exc
            if ok is False:
                raise AdapterError(
                    f"failed to update setup {name!r}",
                    code="setup_update_failed",
                )
            target = new_name or name
            try:
                if hasattr(self._hfss, "save_project"):
                    self._hfss.save_project()
            except Exception:
                pass
            return self._serialize_setup(self._get_setup_object(target))

    def delete_setup(self, name: str) -> dict[str, Any]:
        with self._lock:
            hfss = self._require_hfss()
            known = list(getattr(hfss, "setup_names", []) or [])
            if name not in known:
                raise AdapterError(
                    f"setup not found: {name}",
                    code="setup_not_found",
                    details={"name": name, "known": known},
                )
            try:
                ok = hfss.delete_setup(name)
            except Exception as exc:
                raise AdapterError(
                    f"failed to delete setup {name!r}: {exc}",
                    code="setup_delete_failed",
                    details={"reason": str(exc)},
                ) from exc
            if ok is False:
                raise AdapterError(
                    f"failed to delete setup {name!r}",
                    code="setup_delete_failed",
                )
            try:
                if hasattr(hfss, "save_project"):
                    hfss.save_project()
            except Exception:
                pass
            remaining = list(getattr(hfss, "setup_names", []) or [])
            return {"ok": True, "deleted": name, "remaining": remaining}

    def _create_sweep_unlocked(
        self, *, setup_name: str, sweep: dict[str, Any]
    ) -> dict[str, Any]:
        hfss = self._require_hfss()
        setup = self._get_setup_object(setup_name)
        from hfss_mcp.setup_ops import json_safe

        range_type = str(sweep.get("range_type") or "LinearCount")
        unit = str(sweep.get("unit") or "GHz")
        name = sweep.get("name")
        start = sweep.get("start")
        stop = sweep.get("stop")
        points = sweep.get("points")
        step = sweep.get("step")
        sweep_type = str(sweep.get("sweep_type") or sweep.get("type") or "Discrete")
        save_fields = bool(sweep.get("save_fields", True))
        save_rad_fields = bool(sweep.get("save_rad_fields", False))
        props_extra = dict(sweep.get("props") or sweep.get("properties") or {})

        # Numeric coercion for start/stop/step if given as bare numbers
        def _num(v: Any) -> float | None:
            if v is None:
                return None
            if isinstance(v, (int, float)):
                return float(v)
            text = str(v).strip()
            # "1GHz" -> leave to unit param; try parse leading float
            try:
                return float(text)
            except ValueError:
                # strip unit letters
                import re

                m = re.match(r"^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)", text)
                return float(m.group(1)) if m else None

        created: Any = None
        try:
            if range_type == "LinearStep":
                method = getattr(hfss, "create_linear_step_sweep", None)
                if not callable(method):
                    method = getattr(setup, "create_linear_step_sweep", None)
                if not callable(method):
                    raise AdapterError(
                        "create_linear_step_sweep not available",
                        code="sweep_create_unsupported",
                    )
                created = method(
                    setup=setup_name,
                    unit=unit,
                    start_frequency=_num(start),
                    stop_frequency=_num(stop),
                    step_size=_num(step),
                    name=name,
                    save_fields=save_fields,
                    save_rad_fields=save_rad_fields,
                    sweep_type=sweep_type,
                )
            elif range_type == "SinglePoint":
                method = getattr(setup, "create_single_point_sweep", None)
                if callable(method):
                    created = method(
                        freq=_num(start) if start is not None else _num(stop),
                        name=name,
                        save_fields=save_fields,
                        save_rad_fields=save_rad_fields,
                    )
                else:
                    # fall back to 1-point linear count
                    created = hfss.create_linear_count_sweep(
                        setup=setup_name,
                        unit=unit,
                        start_frequency=_num(start) if start is not None else _num(stop),
                        stop_frequency=_num(stop) if stop is not None else _num(start),
                        num_of_freq_points=1,
                        name=name,
                        save_fields=save_fields,
                        save_rad_fields=save_rad_fields,
                        sweep_type=sweep_type,
                    )
            else:
                # LinearCount / LogScale (LogScale via props after create)
                created = hfss.create_linear_count_sweep(
                    setup=setup_name,
                    unit=unit,
                    start_frequency=_num(start),
                    stop_frequency=_num(stop),
                    num_of_freq_points=int(points) if points is not None else None,
                    name=name,
                    save_fields=save_fields,
                    save_rad_fields=save_rad_fields,
                    sweep_type=sweep_type,
                    interpolation_tol=float(
                        sweep.get("interpolation_tol", 0.5)
                    ),
                    interpolation_max_solutions=int(
                        sweep.get("interpolation_max_solutions", 250)
                    ),
                )
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(
                f"failed to create sweep on {setup_name!r}: {exc}",
                code="sweep_create_failed",
                details={"reason": str(exc), "sweep": sweep},
            ) from exc
        if created is False:
            raise AdapterError(
                f"failed to create sweep on {setup_name!r}",
                code="sweep_create_failed",
            )

        # Resolve sweep name
        sweep_name = name
        if created is not None and created is not False:
            sn = getattr(created, "name", None)
            if sn:
                sweep_name = str(sn)
        if not sweep_name:
            # last sweep
            names = []
            try:
                names = list(setup.get_sweep_names() or [])
            except Exception:
                names = [str(getattr(s, "name", "")) for s in (getattr(setup, "sweeps", []) or [])]
            sweep_name = names[-1] if names else "Sweep"

        if props_extra or range_type == "LogScale":
            try:
                sw_obj = setup.get_sweep(sweep_name) if hasattr(setup, "get_sweep") else created
                if range_type == "LogScale" and sw_obj is not None:
                    props_extra = {"RangeType": "LogScale", **props_extra}
                if sw_obj is not None and props_extra:
                    sp = getattr(sw_obj, "props", None)
                    if isinstance(sp, dict) or hasattr(sp, "__setitem__"):
                        for k, v in props_extra.items():
                            sp[k] = v
                    updater = getattr(sw_obj, "update", None)
                    if callable(updater):
                        updater()
            except Exception:
                pass

        # Re-read
        try:
            setup = self._get_setup_object(setup_name)
            sw_obj = None
            if hasattr(setup, "get_sweep"):
                sw_obj = setup.get_sweep(sweep_name)
            if sw_obj is None:
                for s in getattr(setup, "sweeps", []) or []:
                    if str(getattr(s, "name", "")) == sweep_name:
                        sw_obj = s
                        break
            props = json_safe(getattr(sw_obj, "props", None) or {}) if sw_obj else {}
        except Exception:
            props = {}
        return {
            "setup": setup_name,
            "sweep": sweep_name,
            "props": props if isinstance(props, dict) else {},
        }

    def create_sweep(
        self,
        *,
        setup_name: str,
        sweep: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            result = self._create_sweep_unlocked(setup_name=setup_name, sweep=sweep)
            try:
                if self._hfss is not None and hasattr(self._hfss, "save_project"):
                    self._hfss.save_project()
            except Exception:
                pass
            return result

    def update_sweep(
        self,
        *,
        setup_name: str,
        sweep_name: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            from hfss_mcp.setup_ops import json_safe

            setup = self._get_setup_object(setup_name)
            sw_obj = None
            if hasattr(setup, "get_sweep"):
                try:
                    sw_obj = setup.get_sweep(sweep_name)
                except Exception:
                    sw_obj = None
            if sw_obj is None:
                for s in getattr(setup, "sweeps", []) or []:
                    if str(getattr(s, "name", "")) == sweep_name:
                        sw_obj = s
                        break
            if sw_obj is None:
                raise AdapterError(
                    f"sweep not found: {sweep_name}",
                    code="sweep_not_found",
                    details={"setup": setup_name, "sweep": sweep_name},
                )
            # Map convenience keys into native props
            props = dict(properties or {})
            mapping = {
                "start": "RangeStart",
                "stop": "RangeEnd",
                "points": "RangeCount",
                "step": "RangeStep",
                "type": "Type",
                "sweep_type": "Type",
                "save_fields": "SaveFields",
                "save_rad_fields": "SaveRadFields",
                "range_type": "RangeType",
                "unit": "RangeUnits",
            }
            native: dict[str, Any] = {}
            for k, v in props.items():
                if k in ("props", "properties"):
                    if isinstance(v, dict):
                        native.update(v)
                    continue
                native[mapping.get(k, k)] = v
            if not native:
                raise AdapterError(
                    "no sweep properties provided to update",
                    code="sweep_update_empty",
                )
            sp = getattr(sw_obj, "props", None)
            if sp is None:
                raise AdapterError(
                    "sweep object has no props",
                    code="sweep_update_unsupported",
                )
            for k, v in native.items():
                try:
                    sp[k] = v
                except Exception:
                    # SetupProps may need setattr-style
                    try:
                        setattr(sp, k, v)
                    except Exception:
                        pass
            updater = getattr(sw_obj, "update", None)
            if not callable(updater):
                raise AdapterError(
                    "sweep object does not support update()",
                    code="sweep_update_unsupported",
                )
            try:
                ok = updater()
            except Exception as exc:
                raise AdapterError(
                    f"failed to update sweep {sweep_name!r}: {exc}",
                    code="sweep_update_failed",
                    details={"reason": str(exc)},
                ) from exc
            if ok is False:
                raise AdapterError(
                    f"failed to update sweep {sweep_name!r}",
                    code="sweep_update_failed",
                )
            try:
                if self._hfss is not None and hasattr(self._hfss, "save_project"):
                    self._hfss.save_project()
            except Exception:
                pass
            return {
                "setup": setup_name,
                "sweep": sweep_name,
                "props": json_safe(getattr(sw_obj, "props", None) or {}),
            }

    def delete_sweep(self, *, setup_name: str, sweep_name: str) -> dict[str, Any]:
        with self._lock:
            setup = self._get_setup_object(setup_name)
            deleter = getattr(setup, "delete_sweep", None)
            if not callable(deleter):
                raise AdapterError(
                    "setup object does not support delete_sweep()",
                    code="sweep_delete_unsupported",
                )
            try:
                ok = deleter(sweep_name)
            except Exception as exc:
                raise AdapterError(
                    f"failed to delete sweep {sweep_name!r}: {exc}",
                    code="sweep_delete_failed",
                    details={"reason": str(exc)},
                ) from exc
            if ok is False:
                raise AdapterError(
                    f"failed to delete sweep {sweep_name!r}",
                    code="sweep_delete_failed",
                )
            remaining: list[str] = []
            try:
                remaining = [str(x) for x in (setup.get_sweep_names() or [])]
            except Exception:
                remaining = [
                    str(getattr(s, "name", ""))
                    for s in (getattr(setup, "sweeps", []) or [])
                ]
            try:
                if self._hfss is not None and hasattr(self._hfss, "save_project"):
                    self._hfss.save_project()
            except Exception:
                pass
            return {
                "ok": True,
                "setup": setup_name,
                "deleted": sweep_name,
                "remaining": remaining,
            }

    def start_solve(self, setup: str, sweep: str | None = None) -> SolveHandle:
        """Start solve. In worker processes, blocking=True is preferred for reliability."""
        with self._lock:
            if self._hfss is None:
                raise AdapterError("no project attached", code="not_attached")
            handle_id = new_id("solve_")
            handle = SolveHandle(handle_id=handle_id, setup=setup, sweep=sweep)
            try:
                ok = self._run_analyze(setup)
                state = SolveState.COMPLETED if ok is not False else SolveState.FAILED
                self._solves[handle_id] = {
                    "handle": handle,
                    "state": state,
                    "setup": setup,
                    "sweep": sweep,
                    "blocking": True,
                }
            except AdapterError:
                raise
            except Exception as exc:
                raise AdapterError(
                    f"failed to start solve: {exc}",
                    code="solve_start_error",
                    details={"reason": str(exc)},
                ) from exc
            return handle

    def _run_analyze(self, setup: str) -> bool:
        """Analyze setup using the most reliable path available on PyAEDT 1.3 / AEDT 2023.2."""
        assert self._hfss is not None
        # 1) Native design Analyze (most stable across versions)
        odesign = getattr(self._hfss, "odesign", None)
        if odesign is not None and hasattr(odesign, "Analyze"):
            try:
                odesign.Analyze(setup)
                return True
            except Exception as exc:
                last = exc
            else:
                return True
        else:
            last = None
        # 2) PyAEDT analyze with blocking
        for method_name in ("analyze_setup", "analyze"):
            method = getattr(self._hfss, method_name, None)
            if not callable(method):
                continue
            try:
                return bool(method(setup, blocking=True))
            except TypeError:
                try:
                    return bool(method(setup))
                except Exception as exc:
                    last = exc
            except Exception as exc:
                last = exc
        # 3) Setup object analyze
        try:
            setup_obj = self._hfss.get_setup(setup)
            if hasattr(setup_obj, "analyze"):
                return bool(setup_obj.analyze())
        except Exception as exc:
            last = exc
        raise AdapterError(
            f"failed to analyze setup {setup!r}: {last}",
            code="solve_start_error",
            details={"reason": str(last)},
        )

    def _probe_solution_done(self, setup: str, sweep: str | None) -> bool | None:
        """Return True if solution present, False if failed, None if unknown/still running."""
        assert self._hfss is not None
        try:
            # export_profile / solution type checks
            sols = getattr(self._hfss, "or_solutions", None) or getattr(
                self._hfss, "osolution", None
            )
            _ = sols
            # Try get_solution_data lightly
            post = getattr(self._hfss, "post", None)
            if post is None:
                return None
            name = f"{setup} : {sweep}" if sweep else setup
            try:
                data = post.get_solution_data(
                    expressions="dB(S(1,1))",
                    setup_sweep_name=name,
                )
                if data not in (None, False):
                    return True
            except Exception:
                return None
        except Exception:
            return None
        return None

    def query_solve(self, handle: SolveHandle) -> SolveStatus:
        with self._lock:
            rec = self._solves.get(handle.handle_id)
            if rec is None:
                return SolveStatus(
                    handle_id=handle.handle_id,
                    state=SolveState.UNKNOWN,
                    message="unknown handle",
                    cancel_supported=self._owns_desktop,
                    cancel_limitation=self.CANCEL_LIMITATION,
                )
            state = rec["state"]
            if state == SolveState.RUNNING and self._hfss is not None:
                done = self._probe_solution_done(
                    str(rec.get("setup")),
                    str(rec["sweep"]) if rec.get("sweep") is not None else None,
                )
                if done is True:
                    rec["state"] = SolveState.COMPLETED
                    state = SolveState.COMPLETED
                elif done is False:
                    rec["state"] = SolveState.FAILED
                    state = SolveState.FAILED
            return SolveStatus(
                handle_id=handle.handle_id,
                state=state,
                cancel_supported=self._owns_desktop and bool(self._owned_pids),
                cancel_limitation=self.CANCEL_LIMITATION,
            )

    def cancel_solve(self, handle: SolveHandle) -> CancelResult:
        """Cancel by terminating only owned AEDT processes for this worker."""
        with self._lock:
            rec = self._solves.get(handle.handle_id)
            if rec is None:
                return CancelResult(
                    handle_id=handle.handle_id,
                    state=SolveState.UNKNOWN,
                    cancelled=False,
                    message="unknown handle",
                    honest_limitation=self.CANCEL_LIMITATION,
                )
            if not self._owns_desktop or not self._owned_pids:
                return CancelResult(
                    handle_id=handle.handle_id,
                    state=rec["state"],
                    cancelled=False,
                    message="no owned AEDT process to terminate",
                    honest_limitation=self.CANCEL_LIMITATION,
                )
            killed = self._kill_owned_aedt()
            if killed:
                rec["state"] = SolveState.CANCELLED
                return CancelResult(
                    handle_id=handle.handle_id,
                    state=SolveState.CANCELLED,
                    cancelled=True,
                    message=f"terminated owned AEDT pids={killed}",
                )
            return CancelResult(
                handle_id=handle.handle_id,
                state=rec["state"],
                cancelled=False,
                message="failed to terminate owned AEDT process",
                honest_limitation=self.CANCEL_LIMITATION,
            )

    def _kill_owned_aedt(self) -> list[int]:
        killed: list[int] = []
        for pid in list(self._owned_pids):
            try:
                import subprocess

                # Never kill processes that existed before we started
                if pid in self._aedt_process_ids_before:
                    continue
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
                killed.append(pid)
            except Exception:
                continue
        return killed

    def extract_metrics(self, names: list[str]) -> dict[str, float]:
        raise AdapterError(
            "use extract_metric_specs with structured MetricSpec list",
            code="use_metric_specs",
            details={"names": names},
        )

    def extract_metric_specs(self, specs: list[MetricSpec]) -> dict[str, float]:
        with self._lock:
            if self._hfss is None:
                raise AdapterError("no project attached", code="not_attached")
            return extract_metrics_real(self._hfss, specs)

    def save_project_copy(self, destination: Path) -> None:
        with self._lock:
            if self._project_path is None:
                raise AdapterError("no project attached", code="not_attached")
            dest = Path(destination)
            if dest.resolve(strict=False) == self._project_path.resolve(strict=False):
                raise AdapterError(
                    "refusing to overwrite original/working project path",
                    code="checkpoint_overwrite_denied",
                )
            dest.parent.mkdir(parents=True, exist_ok=True)
            if self._hfss is not None:
                try:
                    self._hfss.save_project()
                except Exception:
                    pass
            if self._project_path.is_file():
                shutil.copy2(self._project_path, dest)
            else:
                raise AdapterError(
                    "project file missing for checkpoint",
                    code="checkpoint_save_error",
                )

    def restore_project_file(self, checkpoint_file: Path) -> None:
        """Replace working project file from checkpoint (caller closes/reopens session)."""
        with self._lock:
            if self._project_path is None:
                raise AdapterError("no project attached", code="not_attached")
            src = Path(checkpoint_file)
            if not src.is_file():
                raise AdapterError("checkpoint file missing", code="checkpoint_missing")
            # Prefer full disconnect over close_project (PyAEDT 1.3 can crash on close)
            if self._hfss is not None:
                with suppress(Exception):
                    self.disconnect(close_desktop=True)
                self._hfss = None
            shutil.copy2(src, self._project_path)

    def disconnect(self, *, close_desktop: bool = False) -> None:
        with self._lock:
            if self._hfss is None:
                return
            try:
                release = getattr(self._hfss, "release_desktop", None)
                if not callable(release):
                    return
                if self._attached_to_user or not self._owns_desktop:
                    # Leave the user's GUI and projects running
                    with suppress(Exception):
                        release(close_projects=False, close_desktop=False)
                elif self._owns_desktop:
                    with suppress(Exception):
                        release(
                            close_projects=True,
                            close_desktop=bool(close_desktop) or True,
                        )
            finally:
                self._hfss = None

    @property
    def is_attached_to_user(self) -> bool:
        return self._attached_to_user

    @property
    def desktop_pid(self) -> int | None:
        return self._desktop_pid
