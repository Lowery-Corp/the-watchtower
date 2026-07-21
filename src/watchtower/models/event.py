"""Immutable profile-attributed canonical event records."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from watchtower.db.base import Base


class Event(Base):
    """Canonical raw event accepted for one profile-owned service."""

    __tablename__ = "event"
    __table_args__ = (
        ForeignKeyConstraint(
            ["service_id", "profile_id"],
            [
                "watchtower.monitored_service.id",
                "watchtower.monitored_service.profile_id",
            ],
            name="fk_event_service_profile",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "profile_id",
            "service_id",
            "source_event_id",
            name="uq_event_profile_service_source_event",
        ),
        UniqueConstraint(
            "id", "service_id", "profile_id", name="uq_event_id_service_profile"
        ),
        Index("ix_event_service_occurred", "service_id", "occurred_at"),
        Index("ix_event_profile_occurred", "profile_id", "occurred_at"),
        Index("ix_event_type_occurred", "event_type", "occurred_at"),
        Index("ix_event_received_at", "received_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_event_id: Mapped[UUID] = mapped_column(nullable=False)
    profile_id: Mapped[UUID] = mapped_column(nullable=False)
    service_id: Mapped[UUID] = mapped_column(nullable=False)
    spec_version: Mapped[str] = mapped_column(String(16), nullable=False)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(255))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    environment: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128))
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
