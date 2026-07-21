"""Create monitored service registry.

Revision ID: 0002_monitored_service
Revises: 0001_initial_schema
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_monitored_service"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monitored_service",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("environment", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("secret_key_id", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_monitored_service"),
        sa.UniqueConstraint("slug", name="uq_monitored_service_slug"),
        schema="watchtower",
    )
    op.create_index(
        "ix_monitored_service_active",
        "monitored_service",
        ["active"],
        schema="watchtower",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_monitored_service_active",
        table_name="monitored_service",
        schema="watchtower",
    )
    op.drop_table("monitored_service", schema="watchtower")
