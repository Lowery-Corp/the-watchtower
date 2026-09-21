"""Profile authorization role and application membership assignments."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from watchtower.db.base import Base


class ProfileRole(Base):
    """A global or monitored-service-scoped role granted to one profile."""

    __tablename__ = "profile_role"
    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_id"],
            ["watchtower.profile.id"],
            name="fk_profile_role_profile",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["role_id", "role_scope_kind"],
            ["watchtower.role.id", "watchtower.role.scope_kind"],
            name="fk_profile_role_role_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["application_id"],
            ["watchtower.monitored_service.id"],
            name="fk_profile_role_application",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["granted_by_profile_id"],
            ["watchtower.profile.id"],
            name="fk_profile_role_granted_by_profile",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(role_scope_kind = 'global' AND application_id IS NULL) OR "
            "(role_scope_kind = 'application' AND application_id IS NOT NULL)",
            name="ck_profile_role_scope_application",
        ),
        Index("ix_profile_role_profile", "profile_id"),
        Index("ix_profile_role_role_scope", "role_id", "role_scope_kind"),
        Index(
            "ix_profile_role_granted_by_profile",
            "granted_by_profile_id",
            postgresql_where=text("granted_by_profile_id IS NOT NULL"),
        ),
        Index(
            "ix_profile_role_application_profile",
            "application_id",
            "profile_id",
            postgresql_where=text("application_id IS NOT NULL"),
        ),
        Index(
            "uq_profile_role_global",
            "profile_id",
            "role_id",
            unique=True,
            postgresql_where=text("application_id IS NULL"),
        ),
        Index(
            "uq_profile_role_application",
            "profile_id",
            "role_id",
            "application_id",
            unique=True,
            postgresql_where=text("application_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(nullable=False)
    role_id: Mapped[UUID] = mapped_column(nullable=False)
    role_scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    application_id: Mapped[UUID | None] = mapped_column(nullable=True)
    granted_by_profile_id: Mapped[UUID | None] = mapped_column(nullable=True)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
