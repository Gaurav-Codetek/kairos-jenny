"""Custom exception hierarchy for Kairos.

All domain-specific exceptions inherit from ``KairosException`` so callers
can catch broadly or narrowly as needed.
"""

from __future__ import annotations


class KairosException(Exception):
    """Base exception for all Kairos errors."""

    def __init__(self, message: str = "An unexpected error occurred.", status_code: int = 500) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class NotFoundError(KairosException):
    """Raised when a requested entity does not exist."""

    def __init__(self, entity: str = "Resource", entity_id: str = "") -> None:
        detail = f"{entity} not found"
        if entity_id:
            detail = f"{entity} '{entity_id}' not found"
        super().__init__(message=detail, status_code=404)


class ConnectorError(KairosException):
    """Raised when a platform connector operation fails."""

    def __init__(self, platform: str, message: str) -> None:
        super().__init__(message=f"[{platform}] {message}", status_code=502)


class LLMProviderError(KairosException):
    """Raised when an LLM provider call fails."""

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(message=f"[{provider}] {message}", status_code=502)


class SyncError(KairosException):
    """Raised when a synchronization operation fails."""

    def __init__(self, domain: str, message: str) -> None:
        super().__init__(message=f"[Sync:{domain}] {message}", status_code=500)
