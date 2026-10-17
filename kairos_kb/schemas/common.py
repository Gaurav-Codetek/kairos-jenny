"""Common schema components shared across API endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str


class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int = 1
    per_page: int = 50


class SyncRequest(BaseModel):
    catalog_filter: Optional[List[str]] = Field(None, description="Optional list of catalog names to sync")
    job_filter: Optional[List[str]] = Field(
        None, description="Optional list of pipelines to sync, by job name or job id (case-insensitive)"
    )
    run_limit: int = Field(25, description="Max runs to fetch per job")
    skip_lineage: bool = Field(False, description="Skip lineage sync")


class SyncResponse(BaseModel):
    workspace_id: str
    status: str
    results: Dict[str, Any]
