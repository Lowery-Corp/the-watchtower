"""Create profile-owned digest-only API keys.

Revision ID: 0007_api_keys
Revises: 0006_tenant_ownership
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_api_keys"
down_revision: str | None = "0006_tenant_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "watchtower"


def upgrade() -> None:
    """Create revocable API-key metadata without plaintext secrets."""

    op.create_table(
        "api_key",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("public_prefix", sa.String(length=32), nullable=False),
        sa.Column("secret_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column(
            "scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("service_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["watchtower.profile.id"],
            name="fk_api_key_profile",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["service_id", "profile_id"],
            [
                "watchtower.monitored_service.id",
                "watchtower.monitored_service.profile_id",
            ],
            name="fk_api_key_service_profile",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_api_key"),
        sa.UniqueConstraint("public_prefix", name="uq_api_key_public_prefix"),
        sa.UniqueConstraint("profile_id", "name", name="uq_api_key_profile_name"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_api_key_profile_revoked",
        "api_key",
        ["profile_id", "revoked_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Remove API-key metadata."""

    op.drop_index(
        "ix_api_key_profile_revoked", table_name="api_key", schema=SCHEMA
    )
    op.drop_table("api_key", schema=SCHEMA)
