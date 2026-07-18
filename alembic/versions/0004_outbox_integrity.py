"""Enforce outbox event/service identity consistency.

Revision ID: 0004_outbox_integrity
Revises: 0003_event_outbox
Create Date: 2026-07-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_outbox_integrity"
down_revision: str | None = "0003_event_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "watchtower"


def upgrade() -> None:
    """Bind every outbox row to the matching event and service pair."""

    op.create_unique_constraint(
        "uq_event_id_service",
        "event",
        ["id", "service_id"],
        schema=SCHEMA,
    )
    op.drop_constraint(
        "fk_outbox_event_id",
        "outbox_message",
        schema=SCHEMA,
        type_="foreignkey",
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


def downgrade() -> None:
    """Restore the original event-only outbox foreign key."""

    op.drop_constraint(
        "fk_outbox_event_service",
        "outbox_message",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_outbox_event_id",
        "outbox_message",
        "event",
        ["event_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_event_id_service",
        "event",
        schema=SCHEMA,
        type_="unique",
    )
