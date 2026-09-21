"""Durable Watchtower authorization roles."""

from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from watchtower.db.base import Base

WATCHTOWER_ADMIN_ROLE_ID = UUID("8f4ab5f3-9114-5f56-bd69-3f73a6001ac8")
APP_ADMIN_ROLE_ID = UUID("f8ebf73d-e0f5-5cfa-9255-670b46d483d5")
VIEWER_ROLE_ID = UUID("5a7912bc-9032-5b72-a919-72c2b96e592c")


class Role(Base):
    """A normalized role with an immutable kind of authorization scope."""

    __tablename__ = "role"
    __table_args__ = (
        UniqueConstraint("name", name="uq_role_name"),
        UniqueConstraint("id", "scope_kind", name="uq_role_id_scope_kind"),
        CheckConstraint(
            "(name = 'watchtower_admin' AND scope_kind = 'global') OR "
            "(name IN ('app_admin', 'viewer') AND scope_kind = 'application')",
            name="ck_role_name_scope_kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
