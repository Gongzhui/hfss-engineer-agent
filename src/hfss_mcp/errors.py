"""Domain and policy error types with structured payloads."""

from __future__ import annotations

from typing import Any


class HfssMcpError(Exception):
    """Base error with a machine-readable code and structured details."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "hfss_mcp_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details: dict[str, Any] = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
        }


class PolicyError(HfssMcpError):
    """Candidate or request rejected by policy before adapter mutation."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "policy_rejected",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class ManifestError(PolicyError):
    """Manifest schema, path, or identity problems."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "manifest_invalid",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class RevisionConflictError(HfssMcpError):
    """Expected design revision does not match adapter state."""

    def __init__(
        self,
        message: str,
        *,
        expected: str,
        actual: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        payload = {"expected_revision": expected, "actual_revision": actual}
        if details:
            payload.update(details)
        super().__init__(message, code="revision_conflict", details=payload)


class ReadbackMismatchError(HfssMcpError):
    """Parameter write did not match read-back values."""

    def __init__(
        self,
        message: str,
        *,
        mismatches: list[dict[str, Any]],
        details: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"mismatches": mismatches}
        if details:
            payload.update(details)
        super().__init__(message, code="readback_mismatch", details=payload)


class AdapterError(HfssMcpError):
    """Adapter-level operational failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "adapter_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class JobError(HfssMcpError):
    """Durable job store or runner failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "job_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)


class CheckpointError(HfssMcpError):
    """Checkpoint creation or integrity failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "checkpoint_error",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)
