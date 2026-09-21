"""Prevent profile deletion from erasing managed-key security history.

Revision ID: 0011_api_key_owner_restrict
Revises: 0010_rate_limit_retention
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_api_key_owner_restrict"
down_revision: str | None = "0010_rate_limit_retention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "watchtower"


def upgrade() -> None:
    """Require managed keys to be removed explicitly before their owner."""

    op.drop_constraint(
        "fk_api_key_profile",
        "api_key",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_api_key_profile",
        "api_key",
        "profile",
        ["profile_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Restore profile-driven managed-key cascading deletion."""

    op.drop_constraint(
        "fk_api_key_profile",
        "api_key",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_api_key_profile",
        "api_key",
        "profile",
        ["profile_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="CASCADE",
    )
