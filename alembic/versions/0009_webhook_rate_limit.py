"""Create shared webhook rate-limit state.

Revision ID: 0009_webhook_rate_limit
Revises: 0008_security_hardening
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_webhook_rate_limit"
down_revision: str | None = "0008_security_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "watchtower"


def upgrade() -> None:
    """Create one fixed-window counter row per authenticated identity."""

    op.create_table(
        "webhook_rate_limit",
        sa.Column("identity", sa.String(length=255), nullable=False),
        sa.Column(
            "window_started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("length(identity) > 0", name="ck_webhook_rate_limit_identity_nonempty"),
        sa.CheckConstraint(
            "request_count >= 1", name="ck_webhook_rate_limit_request_count_positive"
        ),
        sa.PrimaryKeyConstraint("identity", name="pk_webhook_rate_limit"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Remove shared webhook rate-limit state."""

    op.drop_table("webhook_rate_limit", schema=SCHEMA)
