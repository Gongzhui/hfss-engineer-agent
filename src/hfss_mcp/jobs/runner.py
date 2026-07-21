"""Legacy TrialRunner shim — production uses Supervisor + worker processes."""

from __future__ import annotations

# Kept as a thin module so older imports do not break; prefer jobs.supervisor.
from hfss_mcp.jobs.supervisor import Supervisor

__all__ = ["Supervisor"]
