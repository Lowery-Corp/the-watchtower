"""Profile-owned API-key lifecycle use cases."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.core.api_keys import digest_api_key, generate_api_key
from watchtower.models.api_key import ApiKey
from watchtower.repositories.api_keys import (
    create_api_key,
    get_api_key_by_id,
    list_api_keys,
)
from watchtower.repositories.monitored_services import get_monitored_service_by_id
from watchtower.schemas.api_key import ApiKeyCreate, ApiKeyUpdate


class ApiKeyNotFoundError(LookupError):
    """The key or requested service is not owned by the current profile."""


class ApiKeyConflictError(ValueError):
    """The requested key metadata conflicts inside the profile."""


async def issue_api_key(
    session: AsyncSession,
    *,
    profile_id: UUID,
    payload: ApiKeyCreate,
) -> tuple[ApiKey, SecretStr]:
    """Generate and persist a one-time machine key atomically."""

    generated = generate_api_key()
    token = generated.token.get_secret_value()
    try:
        async with session.begin():
            if payload.service_id is not None:
                service = await get_monitored_service_by_id(
                    session,
                    profile_id=profile_id,
                    service_id=payload.service_id,
                )
                if service is None:
                    raise ApiKeyNotFoundError("Service not found")
            api_key = await create_api_key(
                session,
                profile_id=profile_id,
                name=payload.name,
                public_prefix=generated.public_prefix,
                secret_digest=digest_api_key(token),
                service_id=payload.service_id,
                expires_at=payload.expires_at,
            )
    except IntegrityError as exc:
        raise ApiKeyConflictError("API key name already exists") from exc
    return api_key, generated.token


async def list_profile_api_keys(
    session: AsyncSession,
    *,
    profile_id: UUID,
) -> list[ApiKey]:
    """List a profile's non-secret key metadata."""

    async with session.begin():
        return await list_api_keys(session, profile_id=profile_id)


async def get_profile_api_key(
    session: AsyncSession,
    *,
    profile_id: UUID,
    api_key_id: UUID,
) -> ApiKey:
    """Read one key without revealing cross-tenant IDs."""

    async with session.begin():
        api_key = await get_api_key_by_id(
            session, profile_id=profile_id, api_key_id=api_key_id
        )
    if api_key is None:
        raise ApiKeyNotFoundError("API key not found")
    return api_key


async def update_profile_api_key(
    session: AsyncSession,
    *,
    profile_id: UUID,
    api_key_id: UUID,
    payload: ApiKeyUpdate,
) -> ApiKey:
    """Update safe metadata without rotating or exposing the key secret."""

    try:
        async with session.begin():
            api_key = await get_api_key_by_id(
                session, profile_id=profile_id, api_key_id=api_key_id
            )
            if api_key is None:
                raise ApiKeyNotFoundError("API key not found")
            fields = payload.model_dump(exclude_unset=True)
            if "expires_at" in fields:
                requested_expiry = fields["expires_at"]
                if requested_expiry is None or (
                    api_key.expires_at is not None
                    and requested_expiry > api_key.expires_at
                ):
                    raise ApiKeyConflictError(
                        "API key expiry cannot be extended or removed"
                    )
            for field, value in fields.items():
                setattr(api_key, field, value)
            await session.flush()
            await session.refresh(api_key)
            return api_key
    except IntegrityError as exc:
        raise ApiKeyConflictError("API key name already exists") from exc


async def revoke_api_key(
    session: AsyncSession,
    *,
    profile_id: UUID,
    api_key_id: UUID,
) -> None:
    """Soft-revoke a key immediately and idempotently."""

    async with session.begin():
        api_key = await get_api_key_by_id(
            session, profile_id=profile_id, api_key_id=api_key_id
        )
        if api_key is None:
            raise ApiKeyNotFoundError("API key not found")
        if api_key.revoked_at is None:
            api_key.revoked_at = datetime.now(UTC)
            await session.flush()
