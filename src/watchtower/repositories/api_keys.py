"""Application-scoped digest-only API-key persistence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.models.api_key import ApiKey
from watchtower.models.monitored_service import MonitoredService
from watchtower.repositories.monitored_services import application_permission_exists


async def create_api_key(
    session: AsyncSession,
    *,
    profile_id: UUID,
    name: str,
    public_prefix: str,
    secret_digest: bytes,
    service_id: UUID,
    expires_at: datetime | None,
) -> ApiKey:
    """Persist creator metadata and a required machine source without committing."""

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
    session: AsyncSession, *, api_key_id: UUID, for_update: bool = False
) -> ApiKey | None:
    """Read one globally identified key, optionally locking it for mutation."""

    statement = select(ApiKey).where(ApiKey.id == api_key_id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return (await session.scalars(statement)).one_or_none()


async def get_api_key_for_ingestion(session: AsyncSession, *, api_key_id: UUID) -> ApiKey | None:
    """Lock one key against concurrent revocation for the ingestion transaction."""

    return await get_api_key_by_id(session, api_key_id=api_key_id, for_update=True)


async def get_api_key_by_prefix(session: AsyncSession, *, public_prefix: str) -> ApiKey | None:
    """Resolve a structurally valid non-secret prefix for authentication."""

    return (
        await session.scalars(select(ApiKey).where(ApiKey.public_prefix == public_prefix))
    ).one_or_none()


async def get_profile_uptime_key(
    session: AsyncSession, *, profile_id: UUID, for_update: bool = False
) -> ApiKey | None:
    statement = select(ApiKey).where(
        ApiKey.profile_id == profile_id,
        ApiKey.credential_kind == "profile_uptime",
    )
    if for_update:
        statement = statement.with_for_update()
    return (await session.scalars(statement)).one_or_none()


async def list_profile_uptime_keys(session: AsyncSession, *, profile_id: UUID) -> list[ApiKey]:
    return list(
        (
            await session.scalars(
                select(ApiKey).where(
                    ApiKey.profile_id == profile_id,
                    ApiKey.credential_kind == "profile_uptime",
                )
            )
        ).all()
    )


async def list_authorized_api_keys(
    session: AsyncSession, *, profile_id: UUID, permission_name: str
) -> list[ApiKey]:
    """List service-bound keys in applications readable by one human profile."""

    result = await session.scalars(
        select(ApiKey)
        .join(MonitoredService, MonitoredService.id == ApiKey.service_id)
        .where(
            ApiKey.service_id.is_not(None),
            application_permission_exists(
                profile_id=profile_id,
                application_id=MonitoredService.id,
                permission_name=permission_name,
            ),
        )
        .order_by(ApiKey.created_at, ApiKey.id)
    )
    return list(result.all())
