"""Local filesystem storage backend.

Stores artifacts under a configurable base path (default: ./data/).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from kairos_kb.config import get_settings
from kairos_kb.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class LocalStorageBackend(StorageBackend):
    """Local filesystem implementation of StorageBackend."""

    def __init__(self, base_path: str | None = None) -> None:
        self._base = Path(base_path or get_settings().storage_base_path)
        # Ensure base directories exist
        for subdir in ("raw", "snapshots", "evidence", "logs"):
            (self._base / subdir).mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        return self._base / path

    async def save(self, path: str, data: bytes | str) -> str:
        """Save data to a file under the storage base path."""
        full_path = self._resolve(path)
        full_path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(data, str):
            full_path.write_text(data, encoding="utf-8")
        else:
            full_path.write_bytes(data)

        logger.debug("Saved %d bytes to %s", len(data), full_path)
        return str(full_path)

    async def load(self, path: str) -> bytes:
        """Load file contents."""
        full_path = self._resolve(path)
        return full_path.read_bytes()

    async def exists(self, path: str) -> bool:
        """Check if a file exists."""
        return self._resolve(path).exists()

    async def list_objects(self, prefix: str) -> List[str]:
        """List all files under a prefix directory."""
        base = self._resolve(prefix)
        if not base.exists():
            return []
        return [str(p.relative_to(self._base)) for p in base.rglob("*") if p.is_file()]

    async def delete(self, path: str) -> None:
        """Delete a file."""
        full_path = self._resolve(path)
        if full_path.exists():
            full_path.unlink()
            logger.debug("Deleted %s", full_path)
