"""Enforce profile ownership across services, events, and outbox rows.

Revision ID: 0006_tenant_ownership
Revises: 0005_profile
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "0006_tenant_ownership"
down_revision: str | None = "0005_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "watchtower"


def _assert_tenant_tables_are_empty(bind: Connection) -> None:
    count = bind.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM watchtower.monitored_service) + "
            "(SELECT count(*) FROM watchtower.event) + "
            "(SELECT count(*) FROM watchtower.outbox_message)"
        )
    ).scalar_one()
    if count:
        raise RuntimeError(
            "Tenant ownership migration requires an explicit profile mapping for existing rows"
        )


def upgrade() -> None:
    """Attach every tenant-owned record to a database-enforced profile."""

    bind = op.get_bind()
    _assert_tenant_tables_are_empty(bind)

    op.add_column(
        "monitored_service", sa.Column("profile_id", sa.Uuid(), nullable=True), schema=SCHEMA
    )
    op.add_column("event", sa.Column("profile_id", sa.Uuid(), nullable=True), schema=SCHEMA)
    op.add_column(
        "outbox_message", sa.Column("profile_id", sa.Uuid(), nullable=True), schema=SCHEMA
    )

    op.drop_constraint(
        "fk_outbox_event_service", "outbox_message", schema=SCHEMA, type_="foreignkey"
    )
    op.drop_constraint(
        "fk_outbox_service_id", "outbox_message", schema=SCHEMA, type_="foreignkey"
    )
    op.drop_constraint("fk_event_service_id", "event", schema=SCHEMA, type_="foreignkey")
    op.drop_constraint(
        "uq_event_service_source_event", "event", schema=SCHEMA, type_="unique"
    )
    op.drop_constraint("uq_event_id_service", "event", schema=SCHEMA, type_="unique")
    op.drop_constraint(
        "uq_monitored_service_slug", "monitored_service", schema=SCHEMA, type_="unique"
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
    op.create_unique_constraint(
        "uq_monitored_service_profile_slug",
        "monitored_service",
        ["profile_id", "slug"],
        schema=SCHEMA,
    )
    op.create_unique_constraint(
        "uq_monitored_service_id_profile",
        "monitored_service",
        ["id", "profile_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_monitored_service_profile_active",
        "monitored_service",
        ["profile_id", "active"],
        schema=SCHEMA,
    )

    op.create_foreign_key(
        "fk_event_service_profile",
        "event",
        "monitored_service",
        ["service_id", "profile_id"],
        ["id", "profile_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_event_profile_service_source_event",
        "event",
        ["profile_id", "service_id", "source_event_id"],
        schema=SCHEMA,
    )
    op.create_unique_constraint(
        "uq_event_id_service_profile",
        "event",
        ["id", "service_id", "profile_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_event_profile_occurred",
        "event",
        ["profile_id", "occurred_at"],
        schema=SCHEMA,
    )

    op.create_foreign_key(
        "fk_outbox_event_service_profile",
        "outbox_message",
        "event",
        ["event_id", "service_id", "profile_id"],
        ["id", "service_id", "profile_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
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

    op.alter_column("monitored_service", "profile_id", nullable=False, schema=SCHEMA)
    op.alter_column("event", "profile_id", nullable=False, schema=SCHEMA)
    op.alter_column("outbox_message", "profile_id", nullable=False, schema=SCHEMA)


def downgrade() -> None:
    """Return to global service identities after checking slug compatibility."""

    bind = op.get_bind()
    duplicate_slug = bind.execute(
        sa.text(
            "SELECT slug FROM watchtower.monitored_service "
            "GROUP BY slug HAVING count(*) > 1 LIMIT 1"
        )
    ).scalar_one_or_none()
    if duplicate_slug is not None:
        raise RuntimeError(
            "Cannot downgrade tenant ownership while service slugs overlap across profiles"
        )

    op.drop_constraint(
        "fk_outbox_event_service_profile",
        "outbox_message",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_outbox_service_profile", "outbox_message", schema=SCHEMA, type_="foreignkey"
    )
    op.drop_constraint(
        "fk_event_service_profile", "event", schema=SCHEMA, type_="foreignkey"
    )
    op.drop_constraint(
        "uq_event_profile_service_source_event", "event", schema=SCHEMA, type_="unique"
    )
    op.drop_constraint(
        "uq_event_id_service_profile", "event", schema=SCHEMA, type_="unique"
    )
    op.drop_index("ix_event_profile_occurred", table_name="event", schema=SCHEMA)

    op.create_unique_constraint(
        "uq_event_service_source_event",
        "event",
        ["service_id", "source_event_id"],
        schema=SCHEMA,
    )
    op.create_unique_constraint(
        "uq_event_id_service", "event", ["id", "service_id"], schema=SCHEMA
    )
    op.create_foreign_key(
        "fk_event_service_id",
        "event",
        "monitored_service",
        ["service_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_outbox_event_service",
        "outbox_message",
        "event",
        ["event_id", "service_id"],
        ["id", "service_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_outbox_service_id",
        "outbox_message",
        "monitored_service",
        ["service_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )

    op.drop_index(
        "ix_monitored_service_profile_active",
        table_name="monitored_service",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "uq_monitored_service_profile_slug",
        "monitored_service",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "uq_monitored_service_id_profile",
        "monitored_service",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "fk_monitored_service_profile",
        "monitored_service",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.create_unique_constraint(
        "uq_monitored_service_slug", "monitored_service", ["slug"], schema=SCHEMA
    )

    op.drop_column("outbox_message", "profile_id", schema=SCHEMA)
    op.drop_column("event", "profile_id", schema=SCHEMA)
    op.drop_column("monitored_service", "profile_id", schema=SCHEMA)
