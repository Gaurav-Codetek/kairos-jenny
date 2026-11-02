"""Workspace schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator


class WorkspaceCreate(BaseModel):
    name: str = Field(..., description="Human-readable workspace name")
    platform: str = Field("databricks", description="databricks or snowflake")
    host: str = Field("", description="Databricks workspace URL, or the Snowflake account URL")
    # Non-secret settings. Snowflake: account, warehouse, role, databases (list) — secrets stay in .env.
    # Databricks: warehouse_id (the SQL warehouse; else DATABRICKS_SQL_WAREHOUSE_ID).
    connection_config: Optional[Dict[str, Any]] = None
    # Databricks: this workspace's personal access token. Stored encrypted, never returned; blank uses DATABRICKS_TOKEN.
    token: Optional[str] = None
    cloud: str = Field("azure", description="Cloud provider: azure, aws, gcp")
    region: str = Field("", description="Cloud region")
    description: Optional[str] = None


class WorkspaceToken(BaseModel):
    """A new personal access token for a Databricks connection (rotating an expiring one)."""

    token: str = Field(..., min_length=1)


class WorkspaceWarehouse(BaseModel):
    """The SQL warehouse a Databricks connection runs its queries on."""

    warehouse_id: str = Field(..., min_length=1, max_length=64)


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

    @field_validator("connection_config", mode="after")
    @classmethod
    def _hide_token(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        from kairos_kb.connectors.credentials import public

        return public(v) if v else v
