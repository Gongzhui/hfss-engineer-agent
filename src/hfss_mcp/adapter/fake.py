"""In-memory FakeAdapter for offline MCP tests."""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any

from hfss_mcp.domain import DesignSnapshot, ParameterValue, utc_now_iso
from hfss_mcp.errors import AdapterError
from hfss_mcp.ids import sha256_hex


class FakeAdapter:
    """Deterministic stand-in for the live COM design."""

    def __init__(
        self,
        *,
        project_path: Path | None = None,
        project_name: str = "DemoProject",
        design_name: str = "HFSSDesign1",
        variables: dict[str, ParameterValue] | None = None,
        setups: list[str] | None = None,
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
        self._mutation_count = 0
        self._revision = self._compute_revision()

    def _compute_revision(self) -> str:
        payload = {
            "n": self._mutation_count,
            "vars": {k: {"v": v.value, "u": v.unit} for k, v in sorted(self._variables.items())},
        }
        return sha256_hex(str(payload))[:16]

    def attach_project(self, project_path: Path, design_name: str) -> DesignSnapshot:
        with self._lock:
            path = Path(project_path)
            self._project_path = path
            self._project_name = path.stem
            self._design_name = design_name
            self._attached = True
            if not self._variables:
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

    def set_variables(self, items: list[ParameterValue]) -> dict[str, Any]:
        with self._lock:
            if not self._attached:
                raise AdapterError("no project attached", code="not_attached")
            readback: dict[str, ParameterValue] = {}
            for item in items:
                if item.name not in self._variables:
                    raise AdapterError(
                        f"variable {item.name!r} does not exist",
                        code="variable_not_found",
                        details={"name": item.name},
                    )
                self._variables[item.name] = ParameterValue(
                    name=item.name, value=item.value, unit=item.unit
                )
                readback[item.name] = copy.deepcopy(self._variables[item.name])
            self._mutation_count += 1
            self._revision = self._compute_revision()
            return {
                "ok": True,
                "readback": {k: v.model_dump() for k, v in readback.items()},
                "saved": False,
                "revision": self._revision,
            }

    def start_solve(self, setup: str, sweep: str | None = None) -> None:
        with self._lock:
            if not self._attached:
                raise AdapterError("no project attached", code="not_attached")
            if setup not in self._setups:
                raise AdapterError(
                    f"setup {setup!r} not found",
                    code="setup_not_found",
                    details={"setup": setup},
                )
            _ = sweep

    def disconnect(self, *, close_desktop: bool = False) -> None:
        with self._lock:
            self._attached = False
            _ = close_desktop
