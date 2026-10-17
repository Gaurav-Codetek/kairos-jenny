"""Databricks connector — concrete implementation of PlatformConnector.

Uses the Databricks REST API via httpx for Unity Catalog, Jobs, and
SQL execution. Lineage is extracted from system tables via SQL.
Configuration is read from the centralised ``Settings`` object.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from kairos_kb.config import get_settings
from kairos_kb.connectors.base import PlatformConnector
from kairos_kb.exceptions import ConnectorError

logger = logging.getLogger(__name__)


class DatabricksConnector(PlatformConnector):
    """Talks to a Databricks workspace over its REST APIs."""

    def __init__(self, *, host: str | None = None, token: str | None = None) -> None:
        settings = get_settings()
        self._host = (host or settings.databricks_host).rstrip("/")
        self._token = token or settings.databricks_token
        self._timeout = settings.databricks_request_timeout_seconds
        self._statement_timeout = settings.databricks_statement_timeout_seconds
        self._jobs_api = settings.databricks_jobs_api_version
        self._workspace_api = settings.databricks_workspace_api_version
        self._sql_api = settings.databricks_sql_api_version
        self._uc_api = settings.databricks_unity_catalog_api_version
        self._warehouse_id = settings.databricks_sql_warehouse_id

        if not self._host or not self._token:
            logger.warning("DatabricksConnector created without host/token — calls will fail.")

    # ── Internal helpers ─────────────────────────────────────────────
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Dict[str, Any] | None = None,
        json_body: Dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Dict[str, Any]:
        """Issue one REST call with error handling."""
        url = f"{self._host}{path}"
        try:
            async with httpx.AsyncClient(timeout=timeout or self._timeout) as client:
                resp = await client.request(
                    method, url, headers=self._headers(),
                    params=params, json=json_body,
                )
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            raise ConnectorError("Databricks", f"HTTP {exc.response.status_code}: {exc.response.text}")
        except httpx.RequestError as exc:
            detail = str(exc) or type(exc).__name__
            raise ConnectorError("Databricks", f"Connection error: {detail}")

    async def _paginate(
        self,
        method: str,
        path: str,
        result_key: str,
        *,
        params: Dict[str, Any] | None = None,
        page_token_key: str = "next_page_token",
    ) -> List[Dict[str, Any]]:
        """Auto-paginate a Databricks API that uses page tokens."""
        all_items: List[Dict[str, Any]] = []
        params = dict(params or {})

        while True:
            data = await self._request(method, path, params=params)
            items = data.get(result_key, [])
            all_items.extend(items)

            next_token = data.get(page_token_key)
            if not next_token:
                break
            params["page_token"] = next_token

        return all_items

    # ── Catalog Discovery (Unity Catalog API) ────────────────────────
    async def list_catalogs(self) -> List[Dict[str, Any]]:
        """List all catalogs via Unity Catalog API."""
        return await self._paginate("GET", f"/api/{self._uc_api}/unity-catalog/catalogs", "catalogs")

    async def list_schemas(self, catalog_name: str) -> List[Dict[str, Any]]:
        """List all schemas in a catalog."""
        return await self._paginate(
            "GET",
            f"/api/{self._uc_api}/unity-catalog/schemas",
            "schemas",
            params={"catalog_name": catalog_name},
        )

    async def list_tables(self, catalog_name: str, schema_name: str) -> List[Dict[str, Any]]:
        """List all tables in a schema."""
        return await self._paginate(
            "GET",
            f"/api/{self._uc_api}/unity-catalog/tables",
            "tables",
            params={"catalog_name": catalog_name, "schema_name": schema_name},
        )

    async def get_table(self, full_name: str) -> Dict[str, Any]:
        """Get detailed table info including columns."""
        return await self._request("GET", f"/api/{self._uc_api}/unity-catalog/tables/{full_name}")

    # ── Job Discovery (Jobs API) ─────────────────────────────────────
    async def list_jobs(self, expand_tasks: bool = True) -> List[Dict[str, Any]]:
        """List all jobs in the workspace."""
        params = {"expand_tasks": "true"} if expand_tasks else None
        return await self._paginate("GET", f"/api/{self._jobs_api}/jobs/list", "jobs", params=params)

    async def get_job(self, job_id: str) -> Dict[str, Any]:
        """Get detailed job info."""
        return await self._request("GET", f"/api/{self._jobs_api}/jobs/get", params={"job_id": job_id})

    async def list_job_runs(self, job_id: str, *, limit: int = 25) -> List[Dict[str, Any]]:
        """List recent runs for a job."""
        data = await self._request(
            "GET",
            f"/api/{self._jobs_api}/jobs/runs/list",
            params={"job_id": job_id, "limit": limit},
        )
        return data.get("runs", [])

    async def get_run(self, run_id: str) -> Dict[str, Any]:
        """Fetch full run details including task runs."""
        return await self._request(
            "GET",
            f"/api/{self._jobs_api}/jobs/runs/get",
            params={"run_id": run_id, "include_history": "true"},
        )

    async def get_run_output(self, run_id: str) -> Dict[str, Any]:
        """Fetch run output/error details."""
        data = await self._request(
            "GET",
            f"/api/{self._jobs_api}/jobs/runs/get-output",
            params={"run_id": run_id},
        )
        metadata_state = data.get("metadata", {}).get("state", {})
        return {
            "error": data.get("error") or metadata_state.get("state_message"),
            "error_trace": data.get("error_trace"),
            "state_message": metadata_state.get("state_message"),
            "notebook_output": data.get("notebook_output", {}),
            "raw_output": data,
        }

    async def read_workspace_file(self, file_path: str) -> str:
        """Read a file from Databricks Workspace or Volumes. Returns the raw text.

        Two different APIs are involved and picking the wrong one fails with a
        confusing 400. Notebooks and repo files live in the workspace tree and
        are served by ``workspace/export``; Volumes and DBFS objects are served
        by the Files API. The workspace export endpoint also wants the path
        *without* the ``/Workspace`` mount prefix, so try both spellings.
        """
        if not file_path.startswith("/"):
            file_path = "/" + file_path

        candidates: List[tuple[str, Dict[str, Any] | None]] = []

        if file_path.startswith(("/Workspace/", "/Repos/", "/Users/", "/Shared/")):
            export_url = f"{self._host}/api/{self._workspace_api}/workspace/export"
            stripped = file_path[len("/Workspace") :] if file_path.startswith("/Workspace/") else file_path
            candidates.append((export_url, {"path": stripped, "direct_download": "true"}))
            if stripped != file_path:
                candidates.append((export_url, {"path": file_path, "direct_download": "true"}))
        else:
            candidates.append((f"{self._host}/api/2.0/fs/files{file_path}", None))
            # Some deployments expose volume paths under the DBFS mount too.
            candidates.append(
                (f"{self._host}/api/{self._workspace_api}/workspace/export",
                 {"path": file_path, "direct_download": "true"})
            )

        last_error: Exception | None = None
        for url, params in candidates:
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(url, headers=self._headers(), params=params)
                    resp.raise_for_status()
                    return resp.text
            except httpx.HTTPStatusError as exc:
                last_error = ConnectorError(
                    "Databricks", f"HTTP {exc.response.status_code}: {exc.response.text[:500]}"
                )
            except httpx.RequestError as exc:
                detail = str(exc) or type(exc).__name__
                last_error = ConnectorError("Databricks", f"Connection error: {detail}")

        raise last_error or ConnectorError("Databricks", f"Could not read {file_path}")

    # ── Volume files (Files API) ─────────────────────────────────────
    async def list_directory(self, path: str, *, page_size: int = 200) -> List[Dict[str, Any]]:
        """Entries in a Unity Catalog Volume directory: name, path, is_directory, file_size, last_modified."""
        from urllib.parse import quote

        res = await self._request(
            "GET", f"/api/2.0/fs/directories{quote(path.rstrip('/') or '/')}", params={"page_size": page_size}
        )
        return res.get("contents", [])

    async def read_file_head(self, path: str, max_bytes: int) -> Dict[str, Any]:
        """The first max_bytes of a Volume file, without downloading the rest (HTTP range request)."""
        from urllib.parse import quote

        url = f"{self._host}/api/2.0/fs/files{quote(path)}"
        headers = {**self._headers(), "Range": f"bytes=0-{max(0, max_bytes - 1)}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ConnectorError("Databricks", f"HTTP {exc.response.status_code}: {exc.response.text[:300]}")
        except httpx.RequestError as exc:
            raise ConnectorError("Databricks", f"Connection error: {str(exc) or type(exc).__name__}")
        total = None
        content_range = resp.headers.get("content-range") or ""
        if "/" in content_range and content_range.rsplit("/", 1)[1].isdigit():
            total = int(content_range.rsplit("/", 1)[1])
        elif resp.status_code == 200 and resp.headers.get("content-length", "").isdigit():
            total = int(resp.headers["content-length"])
        return {
            "content": resp.content[:max_bytes],
            "total_bytes": total,
            "content_type": resp.headers.get("content-type"),
            "last_modified": resp.headers.get("last-modified"),
        }

    # ── Lineage (System Tables via SQL) ──────────────────────────────
    async def get_table_lineage(self, *, catalog_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get table-level lineage from system.access.table_lineage."""
        sql = "SELECT * FROM system.access.table_lineage"
        if catalog_filter:
            sql += f" WHERE source_table_catalog = '{catalog_filter}' OR target_table_catalog = '{catalog_filter}'"
        sql += " LIMIT 10000"

        result = await self.execute_query(sql)
        return self._rows_from_statement_result(result)

    async def get_column_lineage(self, *, catalog_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get column-level lineage from system.access.column_lineage."""
        sql = "SELECT * FROM system.access.column_lineage"
        if catalog_filter:
            sql += f" WHERE source_table_catalog = '{catalog_filter}' OR target_table_catalog = '{catalog_filter}'"
        sql += " LIMIT 10000"

        result = await self.execute_query(sql)
        return self._rows_from_statement_result(result)

    # ── SQL Execution ────────────────────────────────────────────────
    async def execute_query(
        self, sql: str, *, row_limit: int | None = None, timeout_seconds: int | None = None
    ) -> Dict[str, Any]:
        """Execute a read-only SQL query via the Databricks SQL Statements API.

        Handles async polling for long-running statements. row_limit caps the
        rows Databricks returns; timeout_seconds overrides the default limit.
        """
        wait_seconds = 50
        client_timeout = wait_seconds + 15

        body: Dict[str, Any] = {
            "statement": sql,
            "warehouse_id": self._warehouse_id,
            "wait_timeout": f"{wait_seconds}s",
        }
        if row_limit:
            body["row_limit"] = int(row_limit)
        res = await self._request(
            "POST",
            f"/api/{self._sql_api}/sql/statements",
            json_body=body,
            timeout=client_timeout,
        )

        deadline = time.monotonic() + (timeout_seconds or self._statement_timeout)
        while (res.get("status", {}) or {}).get("state") in ("PENDING", "RUNNING"):
            statement_id = res.get("statement_id")
            if not statement_id:
                break
            if time.monotonic() > deadline:
                try:
                    await self._request(
                        "POST",
                        f"/api/{self._sql_api}/sql/statements/{statement_id}/cancel",
                    )
                except ConnectorError:
                    logger.warning("Could not cancel timed-out statement %s", statement_id)
                raise ConnectorError(
                    "Databricks",
                    f"SQL statement {statement_id} did not finish within {self._statement_timeout}s",
                )
            await asyncio.sleep(2)
            res = await self._request(
                "GET",
                f"/api/{self._sql_api}/sql/statements/{statement_id}",
                timeout=client_timeout,
            )
        return res

    # ── Health ───────────────────────────────────────────────────────
    async def test_connection(self) -> bool:
        """Verify connectivity by hitting the workspace status endpoint."""
        try:
            await self._request("GET", f"/api/{self._workspace_api}/workspace/get-status", params={"path": "/"})
            return True
        except ConnectorError:
            return False

    # ── Helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _rows_from_statement_result(result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Convert SQL Statements API result into a list of row dicts."""
        manifest = result.get("manifest", {})
        columns = manifest.get("schema", {}).get("columns", [])
        col_names = [c["name"] for c in columns]

        data_array = result.get("result", {}).get("data_array", [])
        return [dict(zip(col_names, row)) for row in data_array]
