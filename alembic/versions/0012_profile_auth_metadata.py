"""Add durable profile status and authentication metadata.

Revision ID: 0012_profile_auth_metadata
Revises: 0011_api_key_owner_restrict
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_profile_auth_metadata"
down_revision: str | None = "0011_api_key_owner_restrict"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "watchtower"


def upgrade() -> None:
    """Add fail-closed local access state and the last successful auth time."""

    op.add_column(
        "profile",
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "profile",
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_profile_status",
        "profile",
        "status IN ('active', 'suspended')",
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Remove profile authentication metadata."""

    op.drop_constraint(
        "ck_profile_status",
        "profile",
        schema=SCHEMA,
        type_="check",
    )
    op.drop_column("profile", "last_authenticated_at", schema=SCHEMA)
    op.drop_column("profile", "status", schema=SCHEMA)
