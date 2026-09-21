"""Website uptime monitor configuration and latest result."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from watchtower.db.base import Base


class WebsiteMonitor(Base):
    """One URL checked on behalf of an existing monitored service."""

    __tablename__ = "website_monitor"
    __table_args__ = (
        CheckConstraint(
            "last_status_code IS NULL OR last_status_code BETWEEN 100 AND 599",
            name="ck_website_monitor_last_status_code",
        ),
        CheckConstraint(
            "last_response_time_ms IS NULL OR last_response_time_ms >= 0",
            name="ck_website_monitor_last_response_time",
        ),
        UniqueConstraint("service_id", "url", name="uq_website_monitor_service_url"),
        Index("ix_website_monitor_due", "active", "next_check_at"),
        Index("ix_website_monitor_service", "service_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    service_id: Mapped[UUID] = mapped_column(
        ForeignKey("watchtower.monitored_service.id", ondelete="RESTRICT"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    next_check_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_is_up: Mapped[bool | None] = mapped_column(Boolean)
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_response_time_ms: Mapped[int | None] = mapped_column(Integer)
    last_failure_kind: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
