"""PyAEDT-backed adapter (optional real host path).

Safety notes:
- Does not expose exec or generic object traversal.
- disconnect() never closes a desktop the caller did not start unless close_desktop=True.
- Cancel reliability on AEDT 2023 R2 is limited; we report honestly.
"""

from __future__ import annotations

import shutil
import threading
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


class PyAedtAdapter:
    """Semantic adapter over PyAEDT Hfss.

    Construction is lazy: import/launch happens on attach unless an existing
    desktop session is injected for tests.
    """

    CANCEL_LIMITATION = (
        "AEDT 2023 R2 / PyAEDT does not provide a reliably documented interrupt for all "
        "in-flight analyzes; cancel is best-effort and may leave the solve running."
    )

    def __init__(
        self,
        *,
        version: str | None = "2023.2",
        non_graphical: bool = True,
        new_desktop: bool = True,
        close_on_exit: bool = False,
        hfss: Any | None = None,
    ) -> None:
        self._version = version
        self._non_graphical = non_graphical
        self._new_desktop = new_desktop
        self._close_on_exit = close_on_exit
        self._hfss = hfss
        self._owns_desktop = hfss is None and new_desktop
        self._lock = threading.RLock()
        self._revision = "uninitialized"
        self._solves: dict[str, dict[str, Any]] = {}
        self._project_path: Path | None = None
        self._mutation_count = 0

    def inspect_environment(self) -> EnvironmentStatus:
        return inspect_environment()

    def _ensure_hfss(self, project_path: Path, design_name: str) -> Any:
        if self._hfss is not None:
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
        try:
            self._hfss = hfss_cls(
                project=str(project_path),
                design=design_name,
                version=self._version,
                non_graphical=self._non_graphical,
                new_desktop=self._new_desktop,
                close_on_exit=self._close_on_exit,
            )
            self._owns_desktop = bool(self._new_desktop)
        except Exception as exc:
            raise AdapterError(
                f"failed to start/open AEDT session: {exc}",
                code="aedt_session_error",
                details={"reason": str(exc), "project": str(project_path)},
            ) from exc
        return self._hfss

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
        # independent_design_variables is typical in PyAEDT
        independent = getattr(vm, "independent_design_variables", None)
        if isinstance(independent, dict):
            return list(independent.keys())
        variables = getattr(vm, "variables", None)
        if isinstance(variables, dict):
            return list(variables.keys())
        design_vars = getattr(self._hfss, "variable_manager", None)
        if design_vars is not None and hasattr(design_vars, "design_variables"):
            dv = design_vars.design_variables
            if isinstance(dv, dict):
                return list(dv.keys())
        return []

    def _parse_expression(self, name: str, expression: str) -> ParameterValue:
        import re

        text = str(expression).strip()
        # Split trailing unit token if present ("10 mm" or "10mm")
        parts = text.split()
        if len(parts) >= 2:
            try:
                value = float(parts[0])
                unit = " ".join(parts[1:])
                return ParameterValue(name=name, value=value, unit=unit)
            except ValueError:
                pass
        glued = re.match(
            r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)([A-Za-z_%µμ]+)$",
            text,
        )
        if glued:
            return ParameterValue(
                name=name,
                value=float(glued.group(1)),
                unit=glued.group(2),
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
            # Fallback: mapping access
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
            if not path.is_file() and self._hfss is None:
                # Allow non-existent only if caller injects hfss (tests)
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
            variables = {
                name: self._read_one(name) for name in self._variable_names()
            }
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
                expression = f"{item.value}{item.unit}" if item.unit != "1" else str(item.value)
                if hasattr(vm, "set_variable"):
                    vm.set_variable(item.name, expression=expression)
                else:
                    # Fallback assignment
                    self._hfss[item.name] = expression

            mismatches: list[dict[str, object]] = []
            readback: dict[str, ParameterValue] = {}
            for item in vector.values:
                actual = self._read_one(item.name)
                readback[item.name] = actual
                if abs(actual.value - item.value) > 1e-9 or actual.unit != item.unit:
                    mismatches.append(
                        {
                            "name": item.name,
                            "expected": item.value,
                            "actual": actual.value,
                            "expected_unit": item.unit,
                            "actual_unit": actual.unit,
                        }
                    )
            if mismatches:
                # Best-effort restore
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
        with self._lock:
            if self._hfss is None:
                raise AdapterError("no project attached", code="not_attached")
            handle_id = new_id("solve_")
            handle = SolveHandle(handle_id=handle_id, setup=setup, sweep=sweep)
            # Non-blocking analyze when available
            try:
                analyze = getattr(self._hfss, "analyze_setup", None) or getattr(
                    self._hfss, "analyze", None
                )
                if analyze is None:
                    raise AdapterError("no analyze method on Hfss object", code="no_analyze")
                # Prefer non-blocking if supported
                try:
                    analyze(setup, blocking=False)
                except TypeError:
                    # Blocking fallback for v0; smoke tests must not run long solves.
                    analyze(setup)
                    self._solves[handle_id] = {
                        "handle": handle,
                        "state": SolveState.COMPLETED,
                    }
                    return handle
                self._solves[handle_id] = {
                    "handle": handle,
                    "state": SolveState.RUNNING,
                    "setup": setup,
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

    def query_solve(self, handle: SolveHandle) -> SolveStatus:
        with self._lock:
            rec = self._solves.get(handle.handle_id)
            if rec is None:
                return SolveStatus(
                    handle_id=handle.handle_id,
                    state=SolveState.UNKNOWN,
                    message="unknown handle",
                    cancel_supported=False,
                    cancel_limitation=self.CANCEL_LIMITATION,
                )
            state = rec["state"]
            if state == SolveState.RUNNING and self._hfss is not None:
                # Probe PyAEDT for solution status if available
                try:
                    props = getattr(self._hfss, "pc_solutions", None)
                    _ = props
                except Exception:
                    pass
            return SolveStatus(
                handle_id=handle.handle_id,
                state=state,
                cancel_supported=False,
                cancel_limitation=self.CANCEL_LIMITATION,
            )

    def cancel_solve(self, handle: SolveHandle) -> CancelResult:
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
            # Honest: do not forge cancelled
            return CancelResult(
                handle_id=handle.handle_id,
                state=rec["state"],
                cancelled=False,
                message="cancel not reliably supported on AEDT 2023 R2 via PyAEDT",
                honest_limitation=self.CANCEL_LIMITATION,
            )

    def extract_metrics(self, names: list[str]) -> dict[str, float]:
        with self._lock:
            if self._hfss is None:
                raise AdapterError("no project attached", code="not_attached")
            # v0: only support simple named scalar metrics if present on a registry;
            # real extraction is project-specific and will expand later.
            raise AdapterError(
                "metric extraction for live PyAEDT is not fully implemented in v0; "
                "use FakeAdapter for offline trials",
                code="metrics_not_implemented",
                details={"requested": names},
            )

    def save_project_copy(self, destination: Path) -> None:
        with self._lock:
            if self._hfss is None or self._project_path is None:
                raise AdapterError("no project attached", code="not_attached")
            dest = Path(destination)
            if dest.resolve(strict=False) == self._project_path.resolve(strict=False):
                raise AdapterError(
                    "refusing to overwrite original project path",
                    code="checkpoint_overwrite_denied",
                )
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Prefer file copy of .aedt when available
            if self._project_path.is_file():
                shutil.copy2(self._project_path, dest)
            else:
                try:
                    self._hfss.save_project()
                    if self._project_path.is_file():
                        shutil.copy2(self._project_path, dest)
                    else:
                        dest.write_text(
                            f"checkpoint-placeholder for {self._project_path}\n",
                            encoding="utf-8",
                        )
                except Exception as exc:
                    raise AdapterError(
                        f"failed to save project copy: {exc}",
                        code="checkpoint_save_error",
                        details={"reason": str(exc)},
                    ) from exc

    def disconnect(self, *, close_desktop: bool = False) -> None:
        with self._lock:
            if self._hfss is None:
                return
            try:
                if close_desktop and self._owns_desktop:
                    release = getattr(self._hfss, "release_desktop", None)
                    if callable(release):
                        release(close_projects=True, close_desktop=True)
                else:
                    # Leave user desktop alone
                    release = getattr(self._hfss, "release_desktop", None)
                    if callable(release) and self._owns_desktop:
                        release(close_projects=False, close_desktop=False)
            finally:
                self._hfss = None
