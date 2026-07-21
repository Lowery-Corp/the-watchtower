"""Create Watchtower user profiles.

Revision ID: 0005_profile
Revises: 0004_outbox_integrity
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_profile"
down_revision: str | None = "0004_outbox_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "watchtower"


def upgrade() -> None:
    """Create the tenant root linked to an external auth user."""

    op.create_table(
        "profile",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("auth_user_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_profile"),
        sa.UniqueConstraint("auth_user_id", name="uq_profile_auth_user_id"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Drop profiles after dependent tenant resources have been removed."""

    op.drop_table("profile", schema=SCHEMA)
