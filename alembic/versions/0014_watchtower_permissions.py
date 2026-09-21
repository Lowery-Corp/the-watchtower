"""Add normalized Watchtower permissions and role grants.

Revision ID: 0014_watchtower_permissions
Revises: 0013_watchtower_roles
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_watchtower_permissions"
down_revision: str | None = "0013_watchtower_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "watchtower"
WATCHTOWER_ADMIN_ROLE_ID = "8f4ab5f3-9114-5f56-bd69-3f73a6001ac8"
APP_ADMIN_ROLE_ID = "f8ebf73d-e0f5-5cfa-9255-670b46d483d5"
VIEWER_ROLE_ID = "5a7912bc-9032-5b72-a919-72c2b96e592c"

PERMISSIONS = (
    ("983c395c-f669-5779-a85d-c05c8a9c12fe", "profiles.read"),
    ("6dc69737-11ce-5257-828f-75a7284dda1d", "profiles.manage"),
    ("36cb8b4f-f56c-5560-bba8-45d1cbec2ec4", "applications.read"),
    ("0a056721-81c3-52f7-9855-1186db026471", "applications.manage"),
    ("d25d91b1-66eb-5654-b8a2-b591b89282bf", "memberships.manage"),
    ("dfbd00b8-8d1d-5c54-9bc7-1452f1478afe", "api_keys.read"),
    ("93132ccb-ed47-5acf-9f80-9ecda36474bd", "api_keys.manage"),
    ("124e1cc1-1636-5d11-b6d4-90d434463cad", "events.read"),
)

ROLE_PERMISSION_GRANTS = (
    ("b46a24bc-9815-5a92-8c83-e13ef74b1c55", WATCHTOWER_ADMIN_ROLE_ID, PERMISSIONS[0][0]),
    ("7f0617f4-6018-5297-89f1-16991fae1ab6", WATCHTOWER_ADMIN_ROLE_ID, PERMISSIONS[1][0]),
    ("d1c13e16-ee0e-5dfb-ad95-61bc0cf3dcc2", WATCHTOWER_ADMIN_ROLE_ID, PERMISSIONS[2][0]),
    ("5512f395-70db-5b0e-87cd-a1f12bf0bb3d", WATCHTOWER_ADMIN_ROLE_ID, PERMISSIONS[3][0]),
    ("d0e5cc9a-4e4a-52c2-ae17-cfe3b209a942", WATCHTOWER_ADMIN_ROLE_ID, PERMISSIONS[4][0]),
    ("5a4f4309-1486-5b4c-b7d7-8b62dd5a7e93", WATCHTOWER_ADMIN_ROLE_ID, PERMISSIONS[5][0]),
    ("3fc79b0a-ea8a-51e0-8019-df23b1bd5856", WATCHTOWER_ADMIN_ROLE_ID, PERMISSIONS[6][0]),
    ("96de34f3-05a2-5354-a07b-04e17f1f4747", WATCHTOWER_ADMIN_ROLE_ID, PERMISSIONS[7][0]),
    ("7b755ea8-d50c-565b-9764-02e1977d84d7", APP_ADMIN_ROLE_ID, PERMISSIONS[2][0]),
    ("b350d6cb-cbc9-59e0-9c43-d0bf6608f3eb", APP_ADMIN_ROLE_ID, PERMISSIONS[3][0]),
    ("c04c9bc7-cf5e-53fa-b749-3d79bb7894af", APP_ADMIN_ROLE_ID, PERMISSIONS[4][0]),
    ("aeaf24e8-354b-564d-adfb-3133d774f9f1", APP_ADMIN_ROLE_ID, PERMISSIONS[5][0]),
    ("2f8006e1-c9c6-500e-b2b3-52226402f0ec", APP_ADMIN_ROLE_ID, PERMISSIONS[6][0]),
    ("59d0a5ff-09a8-5e65-ab3d-c001a9dd3f54", APP_ADMIN_ROLE_ID, PERMISSIONS[7][0]),
    ("c7bcb94f-cac0-5520-bd37-89b5af99e78c", VIEWER_ROLE_ID, PERMISSIONS[2][0]),
    ("87c3ca46-596a-5477-9b35-b2e05af4ae8c", VIEWER_ROLE_ID, PERMISSIONS[7][0]),
)


def upgrade() -> None:
    """Create the closed permission catalog and deterministic role grants."""

    allowed_names = ", ".join(f"'{name}'" for _, name in PERMISSIONS)
    op.create_table(
        "permission",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.CheckConstraint(f"name IN ({allowed_names})", name="ck_permission_name_allowed"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_permission_name"),
        schema=SCHEMA,
    )
    op.create_table(
        "role_permission",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            [f"{SCHEMA}.permission.id"],
            name="fk_role_permission_permission",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            [f"{SCHEMA}.role.id"],
            name="fk_role_permission_role",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission_role_permission"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_role_permission_permission_role",
        "role_permission",
        ["permission_id", "role_id"],
        schema=SCHEMA,
    )

    op.bulk_insert(
        sa.table(
            "permission",
            sa.column("id", sa.Uuid()),
            sa.column("name", sa.String()),
            schema=SCHEMA,
        ),
        [{"id": permission_id, "name": name} for permission_id, name in PERMISSIONS],
    )
    op.bulk_insert(
        sa.table(
            "role_permission",
            sa.column("id", sa.Uuid()),
            sa.column("role_id", sa.Uuid()),
            sa.column("permission_id", sa.Uuid()),
            schema=SCHEMA,
        ),
        [
            {"id": grant_id, "role_id": role_id, "permission_id": permission_id}
            for grant_id, role_id, permission_id in ROLE_PERMISSION_GRANTS
        ],
    )


def downgrade() -> None:
    """Remove only permission grants and permission metadata."""

    op.drop_table("role_permission", schema=SCHEMA)
    op.drop_table("permission", schema=SCHEMA)
