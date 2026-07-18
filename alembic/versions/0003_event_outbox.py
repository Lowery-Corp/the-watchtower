"""Create immutable events and transactional outbox.

Revision ID: 0003_event_outbox
Revises: 0002_monitored_service
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_event_outbox"
down_revision: str | None = "0002_monitored_service"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_event_id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("spec_version", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("environment", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["watchtower.monitored_service.id"],
            name="fk_event_service_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_event"),
        sa.UniqueConstraint(
            "service_id",
            "source_event_id",
            name="uq_event_service_source_event",
        ),
        schema="watchtower",
    )
    op.create_index(
        "ix_event_service_occurred",
        "event",
        ["service_id", "occurred_at"],
        schema="watchtower",
    )
    op.create_index(
        "ix_event_type_occurred",
        "event",
        ["event_type", "occurred_at"],
        schema="watchtower",
    )
    op.create_index(
        "ix_event_received_at",
        "event",
        ["received_at"],
        schema="watchtower",
    )

    op.create_table(
        "outbox_message",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("partition_key", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["watchtower.event.id"],
            name="fk_outbox_event_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["watchtower.monitored_service.id"],
            name="fk_outbox_service_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_message"),
        sa.UniqueConstraint("event_id", name="uq_outbox_event_id"),
        schema="watchtower",
    )
    op.create_index(
        "ix_outbox_unpublished_retry",
        "outbox_message",
        ["published_at", "next_attempt_at"],
        schema="watchtower",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outbox_unpublished_retry",
        table_name="outbox_message",
        schema="watchtower",
    )
    op.drop_table("outbox_message", schema="watchtower")
    op.drop_index("ix_event_received_at", table_name="event", schema="watchtower")
    op.drop_index("ix_event_type_occurred", table_name="event", schema="watchtower")
    op.drop_index("ix_event_service_occurred", table_name="event", schema="watchtower")
    op.drop_table("event", schema="watchtower")
