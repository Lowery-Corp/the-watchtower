"""Harden managed keys and tenant deletion semantics.

Revision ID: 0008_security_hardening
Revises: 0007_api_keys
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_security_hardening"
down_revision: str | None = "0007_api_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "watchtower"


def upgrade() -> None:
    """Version key rows, constrain verifier metadata, and prevent owner cascades."""

    op.add_column(
        "api_key",
        sa.Column(
            "token_version",
            sa.SmallInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        schema=SCHEMA,
    )
    op.create_unique_constraint(
        "uq_api_key_secret_digest", "api_key", ["secret_digest"], schema=SCHEMA
    )
    op.create_check_constraint(
        "ck_api_key_secret_digest_length",
        "api_key",
        "octet_length(secret_digest) = 32",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_api_key_scopes_array",
        "api_key",
        "jsonb_typeof(scopes) = 'array'",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_api_key_expires_after_creation",
        "api_key",
        "expires_at IS NULL OR expires_at > created_at",
        schema=SCHEMA,
    )

    op.drop_constraint(
        "fk_outbox_service_profile",
        "outbox_message",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_monitored_service_profile",
        "monitored_service",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_monitored_service_profile",
        "monitored_service",
        "profile",
        ["profile_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Restore the pre-hardening constraints."""

    op.drop_constraint(
        "fk_monitored_service_profile",
        "monitored_service",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_monitored_service_profile",
        "monitored_service",
        "profile",
        ["profile_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_outbox_service_profile",
        "outbox_message",
        "monitored_service",
        ["service_id", "profile_id"],
        ["id", "profile_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        "ck_api_key_expires_after_creation",
        "api_key",
        schema=SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        "ck_api_key_scopes_array", "api_key", schema=SCHEMA, type_="check"
    )
    op.drop_constraint(
        "ck_api_key_secret_digest_length",
        "api_key",
        schema=SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        "uq_api_key_secret_digest",
        "api_key",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_column("api_key", "token_version", schema=SCHEMA)
