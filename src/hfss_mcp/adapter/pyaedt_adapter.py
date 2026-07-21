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
        kwargs: dict[str, Any] = {
            "project": str(project_path) if project_path else None,
            "design": design_name or None,
            "version": self._version,
            "non_graphical": False if attach else self._non_graphical,
            "new_desktop": False if attach else self._new_desktop,
            "close_on_exit": False if attach else self._close_on_exit,
        }
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

    def _activate_project_design(self, project_path: Path, design_name: str) -> None:
        if self._hfss is None:
            return
        # Prefer matching already-open project by path/name
        try:
            target_name = project_path.stem if project_path else None
            proj_list = list(getattr(self._hfss, "project_list", None) or [])
            if target_name and proj_list:
                # load_project if path exists and not open
                open_names = {str(p) for p in proj_list}
                if target_name not in open_names and project_path.is_file():
                    loader = getattr(self._hfss, "load_project", None)
                    if callable(loader):
                        with suppress(Exception):
                            loader(str(project_path), set_active=True)
                set_active = getattr(self._hfss, "set_active_project", None)
                if callable(set_active) and target_name in (
                    open_names | {target_name}
                ):
                    with suppress(Exception):
                        set_active(target_name)
            if design_name:
                set_design = getattr(self._hfss, "set_active_design", None)
                if callable(set_design):
                    with suppress(Exception):
                        set_design(design_name)
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
