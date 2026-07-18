"""Transactional outbox records for asynchronous publication."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from watchtower.db.base import Base


class OutboxMessage(Base):
    """Kafka-ready message committed in the same transaction as its event."""

    __tablename__ = "outbox_message"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "service_id"],
            ["watchtower.event.id", "watchtower.event.service_id"],
            name="fk_outbox_event_service",
            ondelete="RESTRICT",
        ),
        Index("ix_outbox_unpublished_retry", "published_at", "next_attempt_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(nullable=False, unique=True)
    service_id: Mapped[UUID] = mapped_column(
        ForeignKey("watchtower.monitored_service.id", ondelete="RESTRICT"),
        nullable=False,
    )
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    partition_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(2000))
