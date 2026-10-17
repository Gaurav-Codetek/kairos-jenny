"""Abstract storage backend interface.

Use this abstraction for all artifact / snapshot storage so the system
can swap from local filesystem to S3 without touching calling code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional


class StorageBackend(ABC):
    """Contract for object storage backends."""

    @abstractmethod
    async def save(self, path: str, data: bytes | str) -> str:
        """Save data to the given path. Returns the full path."""

    @abstractmethod
    async def load(self, path: str) -> bytes:
        """Load data from the given path."""

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Check if a path exists."""

    @abstractmethod
    async def list_objects(self, prefix: str) -> List[str]:
        """List all objects under a prefix."""

    @abstractmethod
    async def delete(self, path: str) -> None:
        """Delete an object."""
