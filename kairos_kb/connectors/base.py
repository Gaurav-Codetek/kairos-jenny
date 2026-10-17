"""Abstract base class for all platform connectors.

Business logic and ingestion services depend ONLY on this interface — they
never know which concrete platform they are talking to.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class PlatformConnector(ABC):
    """Contract that every data-platform connector must implement."""

    # ── Catalog Discovery ────────────────────────────────────────────
    @abstractmethod
    async def list_catalogs(self) -> List[Dict[str, Any]]:
        """List all catalogs in the workspace."""

    @abstractmethod
    async def list_schemas(self, catalog_name: str) -> List[Dict[str, Any]]:
        """List all schemas in a catalog."""

    @abstractmethod
    async def list_tables(self, catalog_name: str, schema_name: str) -> List[Dict[str, Any]]:
        """List all tables in a schema."""

    @abstractmethod
    async def get_table(self, full_name: str) -> Dict[str, Any]:
        """Get detailed table info including columns."""

    # ── Job Discovery ────────────────────────────────────────────────
    @abstractmethod
    async def list_jobs(self) -> List[Dict[str, Any]]:
        """List all jobs in the workspace."""

    @abstractmethod
    async def get_job(self, job_id: str) -> Dict[str, Any]:
        """Get detailed job info including tasks."""

    @abstractmethod
    async def list_job_runs(self, job_id: str, *, limit: int = 25) -> List[Dict[str, Any]]:
        """List recent runs for a job."""

    @abstractmethod
    async def get_run(self, run_id: str) -> Dict[str, Any]:
        """Fetch run details."""

    @abstractmethod
    async def get_run_output(self, run_id: str) -> Dict[str, Any]:
        """Fetch run output/error details."""

    # ── Lineage ──────────────────────────────────────────────────────
    @abstractmethod
    async def get_table_lineage(self, *, catalog_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get table-level lineage edges."""

    @abstractmethod
    async def get_column_lineage(self, *, catalog_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get column-level lineage edges."""

    # ── SQL Execution ────────────────────────────────────────────────
    @abstractmethod
    async def execute_query(self, sql: str) -> Dict[str, Any]:
        """Execute a read-only SQL query."""

    # ── Health ───────────────────────────────────────────────────────
    @abstractmethod
    async def test_connection(self) -> bool:
        """Verify that the connector can reach the remote platform."""
