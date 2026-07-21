"""Watchtower-local profile linked to an external auth identity."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from watchtower.db.base import Base


class Profile(Base):
    """Tenant root for one externally authenticated user."""

    __tablename__ = "profile"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    auth_user_id: Mapped[UUID] = mapped_column(unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
