"""Normalized grants connecting durable roles to permissions."""

from uuid import UUID, uuid4

from sqlalchemy import ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from watchtower.db.base import Base


class RolePermission(Base):
    """A durable permission granted to one normalized role."""

    __tablename__ = "role_permission"
    __table_args__ = (
        ForeignKeyConstraint(
            ["role_id"],
            ["watchtower.role.id"],
            name="fk_role_permission_role",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["permission_id"],
            ["watchtower.permission.id"],
            name="fk_role_permission_permission",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission_role_permission"),
        Index("ix_role_permission_permission_role", "permission_id", "role_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    role_id: Mapped[UUID] = mapped_column(nullable=False)
    permission_id: Mapped[UUID] = mapped_column(nullable=False)
