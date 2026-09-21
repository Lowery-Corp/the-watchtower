"""Digest-only application machine keys with durable creator metadata."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from watchtower.db.base import Base


class ApiKey(Base):
    """Revocable machine credential; plaintext key material is never stored."""

    __tablename__ = "api_key"
    __table_args__ = (
        UniqueConstraint("service_id", "name", name="uq_api_key_service_name"),
        UniqueConstraint("secret_digest", name="uq_api_key_secret_digest"),
        CheckConstraint(
            "octet_length(secret_digest) = 32",
            name="ck_api_key_secret_digest_length",
        ),
        CheckConstraint("jsonb_typeof(scopes) = 'array'", name="ck_api_key_scopes_array"),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="ck_api_key_expires_after_creation",
        ),
        CheckConstraint(
            "credential_kind IN ('service_ingestion', 'profile_uptime')",
            name="ck_api_key_credential_kind",
        ),
        CheckConstraint(
            "(credential_kind = 'service_ingestion' AND "
            "(service_id IS NOT NULL OR revoked_at IS NOT NULL)) OR "
            "(credential_kind = 'profile_uptime' AND service_id IS NULL AND "
            "expires_at IS NULL AND revoked_at IS NULL)",
            name="ck_api_key_kind_binding",
        ),
        CheckConstraint(
            "(credential_kind = 'service_ingestion' AND "
            "scopes = '[\"events:write\"]'::jsonb) OR "
            "(credential_kind = 'profile_uptime' AND "
            "scopes = '[\"uptime:read\"]'::jsonb)",
            name="ck_api_key_kind_scopes",
        ),
        Index("ix_api_key_service_revoked", "service_id", "revoked_at"),
        Index("ix_api_key_profile", "profile_id"),
        Index(
            "uq_api_key_profile_uptime",
            "profile_id",
            unique=True,
            postgresql_where=text("credential_kind = 'profile_uptime'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("watchtower.profile.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    credential_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="service_ingestion", server_default="service_ingestion"
    )
    token_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    public_prefix: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    secret_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    service_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("watchtower.monitored_service.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
