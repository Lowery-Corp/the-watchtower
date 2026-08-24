"""Profile-scoped digest-only API-key persistence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.models.api_key import ApiKey


async def create_api_key(
    session: AsyncSession,
    *,
    profile_id: UUID,
    name: str,
    public_prefix: str,
    secret_digest: bytes,
    service_id: UUID | None,
    expires_at: datetime | None,
) -> ApiKey:
    """Persist only the verifier and non-secret metadata without committing."""

    api_key = ApiKey(
        profile_id=profile_id,
        name=name,
        public_prefix=public_prefix,
        secret_digest=secret_digest,
        scopes=["events:write"],
        service_id=service_id,
        expires_at=expires_at,
    )
    session.add(api_key)
    await session.flush()
    return api_key


async def get_api_key_by_id(
    session: AsyncSession,
    *,
    profile_id: UUID,
    api_key_id: UUID,
) -> ApiKey | None:
    """Read a key only inside its owning profile."""

    return (
        await session.scalars(
            select(ApiKey).where(
                ApiKey.profile_id == profile_id,
                ApiKey.id == api_key_id,
            )
        )
    ).one_or_none()


async def get_api_key_for_ingestion(
    session: AsyncSession,
    *,
    profile_id: UUID,
    api_key_id: UUID,
) -> ApiKey | None:
    """Lock one key against concurrent revocation for the ingestion transaction."""

    return (
        await session.scalars(
            select(ApiKey)
            .where(
                ApiKey.profile_id == profile_id,
                ApiKey.id == api_key_id,
            )
            .with_for_update()
        )
    ).one_or_none()


async def get_api_key_by_prefix(
    session: AsyncSession,
    *,
    public_prefix: str,
) -> ApiKey | None:
    """Resolve a structurally valid non-secret prefix for authentication."""

    return (
        await session.scalars(select(ApiKey).where(ApiKey.public_prefix == public_prefix))
    ).one_or_none()


async def list_api_keys(
    session: AsyncSession,
    *,
    profile_id: UUID,
) -> list[ApiKey]:
    """List non-secret key rows for one profile."""

    result = await session.scalars(
        select(ApiKey).where(ApiKey.profile_id == profile_id).order_by(ApiKey.created_at, ApiKey.id)
    )
    return list(result.all())
