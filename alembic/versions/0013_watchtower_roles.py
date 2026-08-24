"""Add normalized Watchtower roles and application memberships.

Revision ID: 0013_watchtower_roles
Revises: 0012_profile_auth_metadata
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_watchtower_roles"
down_revision: str | None = "0012_profile_auth_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "watchtower"
WATCHTOWER_ADMIN_ROLE_ID = "8f4ab5f3-9114-5f56-bd69-3f73a6001ac8"
APP_ADMIN_ROLE_ID = "f8ebf73d-e0f5-5cfa-9255-670b46d483d5"
VIEWER_ROLE_ID = "5a7912bc-9032-5b72-a919-72c2b96e592c"


def upgrade() -> None:
    """Create role metadata, assignments, stable seeds, and owner memberships."""

    op.create_table(
        "role",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("scope_kind", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "(name = 'watchtower_admin' AND scope_kind = 'global') OR "
            "(name IN ('app_admin', 'viewer') AND scope_kind = 'application')",
            name="ck_role_name_scope_kind",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "scope_kind", name="uq_role_id_scope_kind"),
        sa.UniqueConstraint("name", name="uq_role_name"),
        schema=SCHEMA,
    )
    op.create_table(
        "profile_role",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("role_scope_kind", sa.String(length=16), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("granted_by_profile_id", sa.Uuid(), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(role_scope_kind = 'global' AND application_id IS NULL) OR "
            "(role_scope_kind = 'application' AND application_id IS NOT NULL)",
            name="ck_profile_role_scope_application",
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            [f"{SCHEMA}.monitored_service.id"],
            name="fk_profile_role_application",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_profile_id"],
            [f"{SCHEMA}.profile.id"],
            name="fk_profile_role_granted_by_profile",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            [f"{SCHEMA}.profile.id"],
            name="fk_profile_role_profile",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["role_id", "role_scope_kind"],
            [f"{SCHEMA}.role.id", f"{SCHEMA}.role.scope_kind"],
            name="fk_profile_role_role_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_profile_role_profile",
        "profile_role",
        ["profile_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_profile_role_role_scope",
        "profile_role",
        ["role_id", "role_scope_kind"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_profile_role_granted_by_profile",
        "profile_role",
        ["granted_by_profile_id"],
        schema=SCHEMA,
        postgresql_where=sa.text("granted_by_profile_id IS NOT NULL"),
    )
    op.create_index(
        "ix_profile_role_application_profile",
        "profile_role",
        ["application_id", "profile_id"],
        unique=False,
        schema=SCHEMA,
        postgresql_where=sa.text("application_id IS NOT NULL"),
    )
    op.create_index(
        "uq_profile_role_global",
        "profile_role",
        ["profile_id", "role_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("application_id IS NULL"),
    )
    op.create_index(
        "uq_profile_role_application",
        "profile_role",
        ["profile_id", "role_id", "application_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("application_id IS NOT NULL"),
    )

    op.bulk_insert(
        sa.table(
            "role",
            sa.column("id", sa.Uuid()),
            sa.column("name", sa.String()),
            sa.column("scope_kind", sa.String()),
            schema=SCHEMA,
        ),
        [
            {
                "id": WATCHTOWER_ADMIN_ROLE_ID,
                "name": "watchtower_admin",
                "scope_kind": "global",
            },
            {
                "id": APP_ADMIN_ROLE_ID,
                "name": "app_admin",
                "scope_kind": "application",
            },
            {
                "id": VIEWER_ROLE_ID,
                "name": "viewer",
                "scope_kind": "application",
            },
        ],
    )
    op.execute(
        sa.text(
            "INSERT INTO watchtower.profile_role "
            "(id, profile_id, role_id, role_scope_kind, application_id, "
            "granted_by_profile_id) "
            "SELECT md5('watchtower-owner-app-admin:' || service.id::text)::uuid, "
            "service.profile_id, CAST(:role_id AS uuid), 'application', service.id, NULL "
            "FROM watchtower.monitored_service AS service"
        ).bindparams(role_id=APP_ADMIN_ROLE_ID)
    )


def downgrade() -> None:
    """Remove only Watchtower role assignments and role metadata."""

    op.drop_table("profile_role", schema=SCHEMA)
    op.drop_table("role", schema=SCHEMA)
