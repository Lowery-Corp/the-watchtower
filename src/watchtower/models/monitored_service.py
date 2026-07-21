"""Profile-owned monitored service identity."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from watchtower.db.base import Base


class MonitoredService(Base):
    """Registered source service owned by exactly one profile."""

    __tablename__ = "monitored_service"
    __table_args__ = (
        UniqueConstraint("profile_id", "slug", name="uq_monitored_service_profile_slug"),
        UniqueConstraint("id", "profile_id", name="uq_monitored_service_id_profile"),
        Index("ix_monitored_service_active", "active"),
        Index("ix_monitored_service_profile_active", "profile_id", "active"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("watchtower.profile.id", ondelete="RESTRICT"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    secret_key_id: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
