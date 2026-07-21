"""In-memory FakeAdapter for offline end-to-end trials."""

from __future__ import annotations

import copy
import threading
import time
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


class FakeAdapter:
    """Deterministic AEDT stand-in implementing the semantic protocol."""

    def __init__(
        self,
        *,
        project_path: Path | None = None,
        project_name: str = "DemoProject",
        design_name: str = "HFSSDesign1",
        variables: dict[str, ParameterValue] | None = None,
        setups: list[str] | None = None,
        metrics: dict[str, float] | None = None,
        solve_duration_s: float = 0.05,
        fail_readback_names: set[str] | None = None,
        cancel_supported: bool = True,
        program_files: Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._attached = False
        self._project_path = (
            Path(project_path)
            if project_path is not None
            else Path(r"C:\fake\projects\DemoProject.aedt")
        )
        self._project_name = project_name
        self._design_name = design_name
        self._variables: dict[str, ParameterValue] = copy.deepcopy(variables or {})
        self._setups = list(setups or ["Setup1"])
        self._metrics = dict(metrics or {"S11_dB": -10.0, "Gain_dBi": 5.0})
        self._solve_duration_s = solve_duration_s
        self._fail_readback_names = set(fail_readback_names or set())
        self._cancel_supported = cancel_supported
        self._program_files = program_files
        self._solves: dict[str, dict[str, object]] = {}
        self._mutation_count = 0
        self._revision = self._compute_revision()

    def _compute_revision(self) -> str:
        payload = {
            "project": str(self._project_path),
            "design": self._design_name,
            "vars": {
                k: {"v": v.value, "u": v.unit}
                for k, v in sorted(self._variables.items())
            },
            "n": self._mutation_count,
        }
        return sha256_hex(repr(payload))[:16]

    def inspect_environment(self) -> EnvironmentStatus:
        return inspect_environment(
            self._program_files,
            process_running=False,
        )

    def attach_project(self, project_path: Path, design_name: str) -> DesignSnapshot:
        with self._lock:
            path = Path(project_path)
            if path.suffix.lower() not in {".aedt", ".aedtz"}:
                raise AdapterError(
                    "fake adapter only accepts .aedt/.aedtz",
                    code="invalid_project",
                    details={"path": str(path)},
                )
            self._project_path = path
            self._project_name = path.stem
            self._design_name = design_name
            self._attached = True
            if not self._variables:
                # Provide a minimal default set if empty
                self._variables = {
                    "patch_w": ParameterValue(name="patch_w", value=10.0, unit="mm"),
                    "patch_l": ParameterValue(name="patch_l", value=12.0, unit="mm"),
                }
            self._revision = self._compute_revision()
            return self.snapshot()

    def snapshot(self) -> DesignSnapshot:
        with self._lock:
            if not self._attached:
                raise AdapterError("no project attached", code="not_attached")
            return DesignSnapshot(
                project_path=str(self._project_path),
                project_name=self._project_name,
                design_name=self._design_name,
                revision=self._revision,
                variables=copy.deepcopy(self._variables),
                setups=list(self._setups),
                captured_at=utc_now_iso(),
            )

    def read_variables(self, names: list[str]) -> dict[str, ParameterValue]:
        with self._lock:
            if not self._attached:
                raise AdapterError("no project attached", code="not_attached")
            missing = [n for n in names if n not in self._variables]
            if missing:
                raise AdapterError(
                    "variables not found in design",
                    code="variable_not_found",
                    details={"missing": missing},
                )
            return {n: copy.deepcopy(self._variables[n]) for n in names}

    def apply_parameter_vector(
        self,
        vector: ParameterVector,
        *,
        expected_revision: str,
    ) -> ApplyResult:
        with self._lock:
            if not self._attached:
                raise AdapterError("no project attached", code="not_attached")
            if expected_revision != self._revision:
                raise RevisionConflictError(
                    "expected revision does not match current design revision",
                    expected=expected_revision,
                    actual=self._revision,
                )
            before = copy.deepcopy(self._variables)
            revision_before = self._revision

            # Batch write
            for item in vector.values:
                if item.name not in self._variables:
                    raise AdapterError(
                        f"variable {item.name!r} does not exist",
                        code="variable_not_found",
                        details={"name": item.name},
                    )
                self._variables[item.name] = ParameterValue(
                    name=item.name,
                    value=item.value,
                    unit=item.unit,
                )

            # Simulated corrupt read-back for testing
            readback: dict[str, ParameterValue] = {}
            mismatches: list[dict[str, object]] = []
            for item in vector.values:
                stored = self._variables[item.name]
                if item.name in self._fail_readback_names:
                    bogus = ParameterValue(
                        name=item.name,
                        value=stored.value + 999.0,
                        unit=stored.unit,
                    )
                    readback[item.name] = bogus
                    mismatches.append(
                        {
                            "name": item.name,
                            "expected": item.value,
                            "actual": bogus.value,
                            "unit": item.unit,
                        }
                    )
                else:
                    readback[item.name] = copy.deepcopy(stored)

            if mismatches:
                # Roll back on read-back failure
                self._variables = before
                raise ReadbackMismatchError(
                    "parameter read-back did not match written values",
                    mismatches=mismatches,
                )

            self._mutation_count += 1
            self._revision = self._compute_revision()
            diff: list[ParameterDiffItem] = []
            for item in vector.values:
                prev = before.get(item.name)
                diff.append(
                    ParameterDiffItem(
                        name=item.name,
                        before_value=prev.value if prev else None,
                        after_value=item.value,
                        unit=item.unit,
                        changed=prev is None or prev.value != item.value or prev.unit != item.unit,
                    )
                )
            return ApplyResult(
                ok=True,
                revision_before=revision_before,
                revision_after=self._revision,
                diff=diff,
                readback=readback,
            )

    def validate_design(self, setup: str, sweep: str | None = None) -> dict[str, object]:
        with self._lock:
            if not self._attached:
                raise AdapterError("no project attached", code="not_attached")
            if setup not in self._setups:
                return {
                    "ok": False,
                    "setup": setup,
                    "sweep": sweep,
                    "errors": [f"setup {setup!r} not found"],
                }
            return {"ok": True, "setup": setup, "sweep": sweep, "errors": []}

    def start_solve(self, setup: str, sweep: str | None = None) -> SolveHandle:
        with self._lock:
            if not self._attached:
                raise AdapterError("no project attached", code="not_attached")
            if setup not in self._setups:
                raise AdapterError(
                    f"setup {setup!r} not found",
                    code="setup_not_found",
                    details={"setup": setup},
                )
            handle_id = new_id("solve_")
            handle = SolveHandle(handle_id=handle_id, setup=setup, sweep=sweep)
            self._solves[handle_id] = {
                "handle": handle,
                "state": SolveState.RUNNING,
                "started": time.monotonic(),
                "cancel_requested": False,
            }
            return handle

    def query_solve(self, handle: SolveHandle) -> SolveStatus:
        with self._lock:
            rec = self._solves.get(handle.handle_id)
            if rec is None:
                return SolveStatus(
                    handle_id=handle.handle_id,
                    state=SolveState.UNKNOWN,
                    message="unknown solve handle",
                )
            state_obj = rec["state"]
            assert isinstance(state_obj, SolveState)
            if state_obj == SolveState.RUNNING:
                started = rec["started"]
                assert isinstance(started, float)
                elapsed = time.monotonic() - started
                if rec["cancel_requested"]:
                    if self._cancel_supported:
                        rec["state"] = SolveState.CANCELLED
                        state_obj = SolveState.CANCELLED
                    # else: still running; honest limitation
                elif elapsed >= self._solve_duration_s:
                    rec["state"] = SolveState.COMPLETED
                    state_obj = SolveState.COMPLETED
                    # Nudge metrics based on variables for realism
                    w = self._variables.get("patch_w")
                    if w is not None:
                        self._metrics["S11_dB"] = -10.0 - (w.value / 10.0)
                        self._metrics["Gain_dBi"] = 5.0 + (w.value / 20.0)
            state = state_obj
            progress = None
            if state == SolveState.RUNNING:
                started = rec["started"]
                assert isinstance(started, float)
                elapsed = time.monotonic() - started
                progress = min(0.99, elapsed / max(self._solve_duration_s, 1e-6))
            elif state == SolveState.COMPLETED:
                progress = 1.0
            return SolveStatus(
                handle_id=handle.handle_id,
                state=state,
                progress=progress,
                cancel_supported=self._cancel_supported,
                cancel_limitation=(
                    None
                    if self._cancel_supported
                    else "FakeAdapter configured with cancel_supported=False"
                ),
            )

    def cancel_solve(self, handle: SolveHandle) -> CancelResult:
        with self._lock:
            rec = self._solves.get(handle.handle_id)
            if rec is None:
                return CancelResult(
                    handle_id=handle.handle_id,
                    state=SolveState.UNKNOWN,
                    cancelled=False,
                    message="unknown solve handle",
                )
            if rec["state"] in {SolveState.COMPLETED, SolveState.FAILED, SolveState.CANCELLED}:
                state = rec["state"]
                assert isinstance(state, SolveState)
                return CancelResult(
                    handle_id=handle.handle_id,
                    state=state,
                    cancelled=state == SolveState.CANCELLED,
                    message=f"solve already terminal: {state.value}",
                )
            rec["cancel_requested"] = True
            if not self._cancel_supported:
                return CancelResult(
                    handle_id=handle.handle_id,
                    state=SolveState.RUNNING,
                    cancelled=False,
                    message="cancel requested but host cannot reliably interrupt this solve",
                    honest_limitation=(
                        "AEDT/Fake cancel not supported for this solve; "
                        "state remains running until natural completion"
                    ),
                )
            rec["state"] = SolveState.CANCELLED
            return CancelResult(
                handle_id=handle.handle_id,
                state=SolveState.CANCELLED,
                cancelled=True,
                message="solve cancelled",
            )

    def extract_metrics(self, names: list[str]) -> dict[str, float]:
        with self._lock:
            if not self._attached:
                raise AdapterError("no project attached", code="not_attached")
            # Provide defaults for structured S11 metric names used in tests
            out: dict[str, float] = {}
            for n in names:
                if n in self._metrics:
                    out[n] = float(self._metrics[n])
                elif n.endswith("_dB") or "S11" in n:
                    w = self._variables.get("patch_w")
                    base = -12.0 - (w.value / 10.0 if w else 0.0)
                    out[n] = base if "freq" not in n.lower() else 2.4
                else:
                    raise AdapterError(
                        "metrics not available",
                        code="metric_not_found",
                        details={"missing": [n]},
                    )
            return out

    def extract_metric_specs(self, specs: list[Any]) -> dict[str, float]:
        names = [getattr(s, "name", str(s)) for s in specs]
        return self.extract_metrics(names)

    def restore_project_file(self, checkpoint_file: Path) -> None:
        import shutil

        with self._lock:
            if self._project_path is None:
                raise AdapterError("no project attached", code="not_attached")
            src = Path(checkpoint_file)
            if not src.is_file():
                raise AdapterError("checkpoint missing", code="checkpoint_missing")
            shutil.copy2(src, self._project_path)

    def save_project_copy(self, destination: Path) -> None:
        with self._lock:
            if not self._attached:
                raise AdapterError("no project attached", code="not_attached")
            dest = Path(destination)
            if dest.resolve(strict=False) == self._project_path.resolve(strict=False):
                raise AdapterError(
                    "refusing to overwrite original project path",
                    code="checkpoint_overwrite_denied",
                    details={"path": str(dest)},
                )
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Write a deterministic fake project blob
            payload = (
                f"FAKE_AEDT_PROJECT\n"
                f"path={self._project_path}\n"
                f"design={self._design_name}\n"
                f"revision={self._revision}\n"
                f"vars={self._variables!r}\n"
            ).encode()
            dest.write_bytes(payload)

    def disconnect(self, *, close_desktop: bool = False) -> None:
        with self._lock:
            self._attached = False
            # close_desktop is ignored for safety in fake mode
            _ = close_desktop

    # Test helpers
    def force_revision(self, revision: str) -> None:
        with self._lock:
            self._revision = revision

    def set_metrics(self, metrics: dict[str, float]) -> None:
        with self._lock:
            self._metrics.update(metrics)
