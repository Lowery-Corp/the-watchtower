"""Create the Watchtower PostgreSQL schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS watchtower")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS watchtower")
