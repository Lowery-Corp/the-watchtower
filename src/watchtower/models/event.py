"""Immutable canonical event records."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from watchtower.db.base import Base


class Event(Base):
    """Canonical raw event accepted from a monitored service."""

    __tablename__ = "event"
    __table_args__ = (
        UniqueConstraint(
            "service_id",
            "source_event_id",
            name="uq_event_service_source_event",
        ),
        UniqueConstraint("id", "service_id", name="uq_event_id_service"),
        Index("ix_event_service_occurred", "service_id", "occurred_at"),
        Index("ix_event_type_occurred", "event_type", "occurred_at"),
        Index("ix_event_received_at", "received_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_event_id: Mapped[UUID] = mapped_column(nullable=False)
    service_id: Mapped[UUID] = mapped_column(
        ForeignKey("watchtower.monitored_service.id", ondelete="RESTRICT"),
        nullable=False,
    )
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
