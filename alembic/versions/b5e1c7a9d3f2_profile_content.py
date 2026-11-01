"""profile content: each profile's YAML is kept in the database, not only as a file on the API's disk

A host whose disk is reset on every deploy (Render) lost every profile written there; the index rows stayed, so
tables looked profiled to some screens and unprofiled to others.

Revision ID: b5e1c7a9d3f2
Revises: 8a4d2f6c1e59
Create Date: 2026-11-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b5e1c7a9d3f2"
down_revision: Union[str, None] = "8a4d2f6c1e59"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("entity_profiles", sa.Column("content", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("entity_profiles", "content")
