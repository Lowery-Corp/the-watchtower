"""Add profile uptime API key discriminator and rotation metadata.

Revision ID: 0017_profile_uptime_keys
Revises: 0016_uptime_monitoring
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_profile_uptime_keys"
down_revision: str | None = "0016_uptime_monitoring"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "watchtower"


def upgrade() -> None:
    op.add_column(
        "api_key",
        sa.Column(
            "credential_kind",
            sa.String(length=32),
            nullable=False,
            server_default="service_ingestion",
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "api_key",
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.drop_constraint("ck_api_key_service_or_revoked", "api_key", schema=SCHEMA, type_="check")
    op.create_check_constraint(
        "ck_api_key_credential_kind",
        "api_key",
        "credential_kind IN ('service_ingestion', 'profile_uptime')",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_api_key_kind_binding",
        "api_key",
        "(credential_kind = 'service_ingestion' AND "
        "(service_id IS NOT NULL OR revoked_at IS NOT NULL)) OR "
        "(credential_kind = 'profile_uptime' AND service_id IS NULL AND "
        "expires_at IS NULL AND revoked_at IS NULL)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_api_key_kind_scopes",
        "api_key",
        "(credential_kind = 'service_ingestion' AND scopes = '[\"events:write\"]'::jsonb) OR "
        "(credential_kind = 'profile_uptime' AND scopes = '[\"uptime:read\"]'::jsonb)",
        schema=SCHEMA,
    )
    op.create_index(
        "uq_api_key_profile_uptime",
        "api_key",
        ["profile_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("credential_kind = 'profile_uptime'"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM watchtower.api_key "
            "WHERE credential_kind = 'profile_uptime')"
        )
    ):
        raise RuntimeError("Cannot downgrade while profile uptime API keys exist")
    op.drop_index("uq_api_key_profile_uptime", table_name="api_key", schema=SCHEMA)
    op.drop_constraint("ck_api_key_kind_scopes", "api_key", schema=SCHEMA, type_="check")
    op.drop_constraint("ck_api_key_kind_binding", "api_key", schema=SCHEMA, type_="check")
    op.drop_constraint("ck_api_key_credential_kind", "api_key", schema=SCHEMA, type_="check")
    op.create_check_constraint(
        "ck_api_key_service_or_revoked",
        "api_key",
        "service_id IS NOT NULL OR revoked_at IS NOT NULL",
        schema=SCHEMA,
    )
    op.drop_column("api_key", "rotated_at", schema=SCHEMA)
    op.drop_column("api_key", "credential_kind", schema=SCHEMA)
