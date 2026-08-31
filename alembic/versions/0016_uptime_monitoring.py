"""Add website uptime monitors and check history.

Revision ID: 0016_uptime_monitoring
Revises: 0015_api_key_application_rbac
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_uptime_monitoring"
down_revision: str | None = "0015_api_key_application_rbac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "watchtower"


def upgrade() -> None:
    """Create monitor configuration and bounded check-history storage."""

    op.create_table(
        "website_monitor",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("next_check_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_is_up", sa.Boolean(), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_response_time_ms", sa.Integer(), nullable=True),
        sa.Column("last_failure_kind", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "last_status_code IS NULL OR last_status_code BETWEEN 100 AND 599",
            name="ck_website_monitor_last_status_code",
        ),
        sa.CheckConstraint(
            "last_response_time_ms IS NULL OR last_response_time_ms >= 0",
            name="ck_website_monitor_last_response_time",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["watchtower.monitored_service.id"],
            name="fk_website_monitor_service",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_website_monitor"),
        sa.UniqueConstraint("service_id", "url", name="uq_website_monitor_service_url"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_website_monitor_due",
        "website_monitor",
        ["active", "next_check_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_website_monitor_service",
        "website_monitor",
        ["service_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "website_monitor_check",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("monitor_id", sa.Uuid(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_up", sa.Boolean(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("failure_kind", sa.String(length=32), nullable=True),
        sa.CheckConstraint(
            "status_code IS NULL OR status_code BETWEEN 100 AND 599",
            name="ck_website_monitor_check_status_code",
        ),
        sa.CheckConstraint(
            "response_time_ms IS NULL OR response_time_ms >= 0",
            name="ck_website_monitor_check_response_time",
        ),
        sa.ForeignKeyConstraint(
            ["monitor_id"],
            ["watchtower.website_monitor.id"],
            name="fk_website_monitor_check_monitor",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_website_monitor_check"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_website_monitor_check_monitor_checked",
        "website_monitor_check",
        ["monitor_id", "checked_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_website_monitor_check_checked_at",
        "website_monitor_check",
        ["checked_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Remove uptime history before monitor definitions."""

    op.drop_table("website_monitor_check", schema=SCHEMA)
    op.drop_table("website_monitor", schema=SCHEMA)
