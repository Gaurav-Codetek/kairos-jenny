"""Catalog, schema, table, and column response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class CatalogResponse(BaseModel):
    id: uuid.UUID
    entity_id: str
    name: str
    comment: Optional[str]
    owner: Optional[str]
    catalog_type: str
    first_seen_at: datetime
    last_seen_at: datetime

    model_config = {"from_attributes": True}


class SchemaResponse(BaseModel):
    id: uuid.UUID
    entity_id: str
    name: str
    full_name: str
    comment: Optional[str]
    owner: Optional[str]
    first_seen_at: datetime
    last_seen_at: datetime

    model_config = {"from_attributes": True}


class ColumnResponse(BaseModel):
    id: uuid.UUID
    entity_id: str
    name: str
    full_name: str
    data_type: str
    full_data_type: str
    ordinal_position: int
    is_nullable: bool
    comment: Optional[str]
    is_partition_column: bool
    first_seen_at: datetime
    last_seen_at: datetime

    model_config = {"from_attributes": True}


class TableResponse(BaseModel):
    id: uuid.UUID
    entity_id: str
    name: str
    full_name: str
    table_type: str
    data_source_format: Optional[str]
    comment: Optional[str]
    owner: Optional[str]
    storage_location: Optional[str]
    row_count: Optional[int]
    size_bytes: Optional[int]
    first_seen_at: datetime
    last_seen_at: datetime
    columns: List[ColumnResponse] = []

    model_config = {"from_attributes": True}
