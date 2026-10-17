"""data products: business-facing bundles of the map, built for agents

Revision ID: 9c4e2a7b1d35
Revises: b3e7d1c9a204
Create Date: 2026-10-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "9c4e2a7b1d35"
down_revision: Union[str, None] = "b3e7d1c9a204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("seeds", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("bundle", sa.JSON(), nullable=True),
        sa.Column("spec", sa.JSON(), nullable=True),
        sa.Column("validation", sa.JSON(), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_data_product_slug"),
    )
    op.create_index("ix_data_products_workspace_id", "data_products", ["workspace_id"])
    op.create_index("ix_data_products_status", "data_products", ["status"])


def downgrade() -> None:
    op.drop_index("ix_data_products_status", table_name="data_products")
    op.drop_index("ix_data_products_workspace_id", table_name="data_products")
    op.drop_table("data_products")
