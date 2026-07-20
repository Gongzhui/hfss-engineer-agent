"""Narrow semantic AEDT adapter protocol.

Does not expose raw PyAEDT objects, exec, or generic traversal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from hfss_mcp.domain import (
    ApplyResult,
    CancelResult,
    DesignSnapshot,
    ParameterValue,
    ParameterVector,
    SolveHandle,
    SolveStatus,
)
from hfss_mcp.environment import EnvironmentStatus


@runtime_checkable
class AedtAdapter(Protocol):
    """Semantic transactions only — no arbitrary host code execution."""

    def inspect_environment(self) -> EnvironmentStatus:
        """Discover AEDT install/runtime without opening projects."""
        ...

    def attach_project(self, project_path: Path, design_name: str) -> DesignSnapshot:
        """Open or attach an approved project/design and return a snapshot."""
        ...

    def snapshot(self) -> DesignSnapshot:
        """Authoritative project/design state and revision."""
        ...

    def read_variables(self, names: list[str]) -> dict[str, ParameterValue]:
        """Read only requested variables (caller enforces allowlist)."""
        ...

    def apply_parameter_vector(
        self,
        vector: ParameterVector,
        *,
        expected_revision: str,
    ) -> ApplyResult:
        """Batch-apply a complete vector with revision check and read-back."""
        ...

    def validate_design(self, setup: str, sweep: str | None = None) -> dict[str, object]:
        """Cheap structural validation of the approved setup."""
        ...

    def start_solve(self, setup: str, sweep: str | None = None) -> SolveHandle:
        """Start an approved solve; returns a handle for status/cancel."""
        ...

    def query_solve(self, handle: SolveHandle) -> SolveStatus:
        ...

    def cancel_solve(self, handle: SolveHandle) -> CancelResult:
        """Attempt cancel; must not forge success if the host cannot cancel."""
        ...

    def extract_metrics(self, names: list[str]) -> dict[str, float]:
        """Extract only requested metric names (caller enforces allowlist)."""
        ...

    def save_project_copy(self, destination: Path) -> None:
        """Write a project copy to destination without overwriting the original path."""
        ...

    def disconnect(self, *, close_desktop: bool = False) -> None:
        """Release adapter resources; must not close a user-owned AEDT by default."""
        ...
