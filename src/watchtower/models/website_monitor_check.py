"""Persisted results for website uptime checks."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from watchtower.db.base import Base


class WebsiteMonitorCheck(Base):
    """One bounded result emitted by the uptime worker."""

    __tablename__ = "website_monitor_check"
    __table_args__ = (
        CheckConstraint(
            "status_code IS NULL OR status_code BETWEEN 100 AND 599",
            name="ck_website_monitor_check_status_code",
        ),
        CheckConstraint(
            "response_time_ms IS NULL OR response_time_ms >= 0",
            name="ck_website_monitor_check_response_time",
        ),
        Index("ix_website_monitor_check_monitor_checked", "monitor_id", "checked_at"),
        Index("ix_website_monitor_check_checked_at", "checked_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    monitor_id: Mapped[UUID] = mapped_column(
        ForeignKey("watchtower.website_monitor.id", ondelete="CASCADE"), nullable=False
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    is_up: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    failure_kind: Mapped[str | None] = mapped_column(String(32))
