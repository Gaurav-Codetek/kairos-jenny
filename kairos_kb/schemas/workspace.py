"""Workspace schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(..., description="Human-readable workspace name")
    platform: str = Field("databricks", description="databricks or snowflake")
    host: str = Field("", description="Databricks workspace URL, or the Snowflake account URL")
    # Non-secret settings. Snowflake: account, warehouse, role, databases (list) — secrets stay in .env.
    connection_config: Optional[Dict[str, Any]] = None
    cloud: str = Field("azure", description="Cloud provider: azure, aws, gcp")
    region: str = Field("", description="Cloud region")
    description: Optional[str] = None


class WorkspaceResponse(BaseModel):
    id: uuid.UUID
    workspace_id: str
    name: str
    platform: str = "databricks"
    host: str
    connection_config: Optional[Dict[str, Any]] = None
    cloud: str
    region: str
    status: str
    last_synced_at: Optional[datetime]
    description: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
