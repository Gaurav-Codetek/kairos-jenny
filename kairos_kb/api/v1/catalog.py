"""Catalog endpoints — browse the Unity Catalog hierarchy."""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kairos_kb.db.engine import get_db
from kairos_kb.exceptions import NotFoundError
from kairos_kb.models.catalog import Catalog
from kairos_kb.models.column import Column
from kairos_kb.models.schema import Schema
from kairos_kb.models.table import Table
from kairos_kb.schemas.catalog import CatalogResponse, ColumnResponse, SchemaResponse, TableResponse

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/catalogs", response_model=List[CatalogResponse])
async def list_catalogs(workspace_id: uuid.UUID | None = None, db: AsyncSession = Depends(get_db)):
    """List all catalogs, optionally filtered by workspace."""
    query = select(Catalog).order_by(Catalog.name)
    if workspace_id:
        query = query.where(Catalog.workspace_id == workspace_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/catalogs/{catalog_id}/schemas", response_model=List[SchemaResponse])
async def list_schemas(catalog_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """List schemas in a catalog."""
    result = await db.execute(
        select(Schema).where(Schema.catalog_id == catalog_id).order_by(Schema.name)
    )
    return result.scalars().all()


@router.get("/schemas/{schema_id}/tables", response_model=List[TableResponse])
async def list_tables(schema_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """List tables in a schema."""
    result = await db.execute(
        select(Table)
        .options(selectinload(Table.columns))
        .where(Table.schema_id == schema_id)
        .order_by(Table.name)
    )
    return result.scalars().all()


@router.get("/tables/{table_id}", response_model=TableResponse)
async def get_table(table_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get table details with columns."""
    result = await db.execute(select(Table).options(selectinload(Table.columns)).where(Table.id == table_id))
    table = result.scalars().first()
    if not table:
        raise NotFoundError("Table", str(table_id))

    # Fetch columns
    col_result = await db.execute(
        select(Column).where(Column.table_id == table_id).order_by(Column.ordinal_position)
    )
    columns = col_result.scalars().all()

    response = TableResponse.model_validate(table)
    response.columns = [ColumnResponse.model_validate(c) for c in columns]
    return response
