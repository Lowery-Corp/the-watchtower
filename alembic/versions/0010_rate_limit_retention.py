"""Index webhook rate-limit rows for bounded stale-state pruning.

Revision ID: 0010_rate_limit_retention
Revises: 0009_webhook_rate_limit
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_rate_limit_retention"
down_revision: str | None = "0009_webhook_rate_limit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "watchtower"


def upgrade() -> None:
    """Index window age so opportunistic bounded cleanup stays efficient."""

    op.create_index(
        "ix_webhook_rate_limit_window_started_at",
        "webhook_rate_limit",
        ["window_started_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Remove the webhook rate-limit age index."""

    op.drop_index(
        "ix_webhook_rate_limit_window_started_at",
        table_name="webhook_rate_limit",
        schema=SCHEMA,
    )
