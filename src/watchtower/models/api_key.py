"""Digest-only profile-owned machine API keys."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
    CheckConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from watchtower.db.base import Base


class ApiKey(Base):
    """Revocable machine credential; plaintext key material is never stored."""

    __tablename__ = "api_key"
    __table_args__ = (
        UniqueConstraint("profile_id", "name", name="uq_api_key_profile_name"),
        UniqueConstraint("secret_digest", name="uq_api_key_secret_digest"),
        CheckConstraint(
            "octet_length(secret_digest) = 32",
            name="ck_api_key_secret_digest_length",
        ),
        CheckConstraint(
            "jsonb_typeof(scopes) = 'array'", name="ck_api_key_scopes_array"
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="ck_api_key_expires_after_creation",
        ),
        ForeignKeyConstraint(
            ["service_id", "profile_id"],
            [
                "watchtower.monitored_service.id",
                "watchtower.monitored_service.profile_id",
            ],
            name="fk_api_key_service_profile",
            ondelete="RESTRICT",
        ),
        Index("ix_api_key_profile_revoked", "profile_id", "revoked_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("watchtower.profile.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    token_version: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="1"
    )
    public_prefix: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    secret_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    service_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def safe_metadata(self) -> dict[str, Any]:
        """Return non-secret metadata for diagnostics without the verifier."""

        return {
            "id": self.id,
            "profile_id": self.profile_id,
            "name": self.name,
            "public_prefix": self.public_prefix,
            "scopes": self.scopes,
            "service_id": self.service_id,
            "revoked_at": self.revoked_at,
        }
