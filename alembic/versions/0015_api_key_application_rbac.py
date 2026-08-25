"""Decouple API-key creator metadata from application ownership.

Revision ID: 0015_api_key_application_rbac
Revises: 0014_watchtower_permissions
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_api_key_application_rbac"
down_revision: str | None = "0014_watchtower_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "watchtower"


def upgrade() -> None:
    """Make service identity authoritative while retaining creator history."""

    op.drop_constraint("fk_api_key_service_profile", "api_key", schema=SCHEMA, type_="foreignkey")
    op.create_foreign_key(
        "fk_api_key_service",
        "api_key",
        "monitored_service",
        ["service_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.drop_constraint("uq_api_key_profile_name", "api_key", schema=SCHEMA, type_="unique")
    op.create_unique_constraint(
        "uq_api_key_service_name", "api_key", ["service_id", "name"], schema=SCHEMA
    )
    op.create_check_constraint(
        "ck_api_key_service_or_revoked",
        "api_key",
        "service_id IS NOT NULL OR revoked_at IS NOT NULL",
        schema=SCHEMA,
    )
    op.drop_index("ix_api_key_profile_revoked", table_name="api_key", schema=SCHEMA)
    op.create_index(
        "ix_api_key_service_revoked",
        "api_key",
        ["service_id", "revoked_at"],
        schema=SCHEMA,
    )
    op.create_index("ix_api_key_profile", "api_key", ["profile_id"], schema=SCHEMA)


def downgrade() -> None:
    """Restore creator-owned bindings only when every key is compatible."""

    connection = op.get_bind()
    incompatible = connection.execute(
        sa.text(
            "SELECT api_key.id FROM watchtower.api_key AS api_key "
            "JOIN watchtower.monitored_service AS service "
            "ON service.id = api_key.service_id "
            "WHERE api_key.profile_id <> service.profile_id LIMIT 1"
        )
    ).scalar_one_or_none()
    if incompatible is not None:
        raise RuntimeError("Cannot downgrade API-key ownership: cross-owner API keys exist")

    duplicate_creator_name = connection.execute(
        sa.text(
            "SELECT profile_id, name FROM watchtower.api_key "
            "GROUP BY profile_id, name HAVING count(*) > 1 LIMIT 1"
        )
    ).one_or_none()
    if duplicate_creator_name is not None:
        raise RuntimeError("Cannot downgrade API-key ownership: duplicate creator key names exist")

    op.drop_index("ix_api_key_profile", table_name="api_key", schema=SCHEMA)
    op.drop_index("ix_api_key_service_revoked", table_name="api_key", schema=SCHEMA)
    op.create_index(
        "ix_api_key_profile_revoked",
        "api_key",
        ["profile_id", "revoked_at"],
        schema=SCHEMA,
    )
    op.drop_constraint("ck_api_key_service_or_revoked", "api_key", schema=SCHEMA, type_="check")
    op.drop_constraint("uq_api_key_service_name", "api_key", schema=SCHEMA, type_="unique")
    op.create_unique_constraint(
        "uq_api_key_profile_name", "api_key", ["profile_id", "name"], schema=SCHEMA
    )
    op.drop_constraint("fk_api_key_service", "api_key", schema=SCHEMA, type_="foreignkey")
    op.create_foreign_key(
        "fk_api_key_service_profile",
        "api_key",
        "monitored_service",
        ["service_id", "profile_id"],
        ["id", "profile_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
