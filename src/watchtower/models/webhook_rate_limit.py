"""One-row-per-identity webhook rate-limit state."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from watchtower.db.base import Base


class WebhookRateLimit(Base):
    """Current fixed-window counter for one authenticated webhook identity."""

    __tablename__ = "webhook_rate_limit"
    __table_args__ = (
        CheckConstraint("length(identity) > 0", name="ck_webhook_rate_limit_identity_nonempty"),
        CheckConstraint("request_count >= 1", name="ck_webhook_rate_limit_request_count_positive"),
        Index("ix_webhook_rate_limit_window_started_at", "window_started_at"),
    )

    identity: Mapped[str] = mapped_column(String(255), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
