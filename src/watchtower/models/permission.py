"""Closed durable Watchtower management permissions."""

from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from watchtower.db.base import Base

PROFILES_READ_PERMISSION_ID = UUID("983c395c-f669-5779-a85d-c05c8a9c12fe")
PROFILES_MANAGE_PERMISSION_ID = UUID("6dc69737-11ce-5257-828f-75a7284dda1d")
APPLICATIONS_READ_PERMISSION_ID = UUID("36cb8b4f-f56c-5560-bba8-45d1cbec2ec4")
APPLICATIONS_MANAGE_PERMISSION_ID = UUID("0a056721-81c3-52f7-9855-1186db026471")
MEMBERSHIPS_MANAGE_PERMISSION_ID = UUID("d25d91b1-66eb-5654-b8a2-b591b89282bf")
API_KEYS_READ_PERMISSION_ID = UUID("dfbd00b8-8d1d-5c54-9bc7-1452f1478afe")
API_KEYS_MANAGE_PERMISSION_ID = UUID("93132ccb-ed47-5acf-9f80-9ecda36474bd")
EVENTS_READ_PERMISSION_ID = UUID("124e1cc1-1636-5d11-b6d4-90d434463cad")

PERMISSION_IDS = {
    "profiles.read": PROFILES_READ_PERMISSION_ID,
    "profiles.manage": PROFILES_MANAGE_PERMISSION_ID,
    "applications.read": APPLICATIONS_READ_PERMISSION_ID,
    "applications.manage": APPLICATIONS_MANAGE_PERMISSION_ID,
    "memberships.manage": MEMBERSHIPS_MANAGE_PERMISSION_ID,
    "api_keys.read": API_KEYS_READ_PERMISSION_ID,
    "api_keys.manage": API_KEYS_MANAGE_PERMISSION_ID,
    "events.read": EVENTS_READ_PERMISSION_ID,
}
_ALLOWED_NAMES_SQL = ", ".join(f"'{name}'" for name in PERMISSION_IDS)


class Permission(Base):
    """One closed, human-management authorization capability."""

    __tablename__ = "permission"
    __table_args__ = (
        UniqueConstraint("name", name="uq_permission_name"),
        CheckConstraint(
            f"name IN ({_ALLOWED_NAMES_SQL})",
            name="ck_permission_name_allowed",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
