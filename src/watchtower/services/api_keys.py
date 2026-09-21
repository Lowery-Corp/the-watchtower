"""Application-scoped API-key lifecycle use cases."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.core.api_keys import (
    digest_api_key,
    digest_profile_api_key,
    generate_api_key,
    generate_profile_api_key,
)
from watchtower.models.api_key import ApiKey
from watchtower.models.monitored_service import MonitoredService
from watchtower.models.profile import Profile
from watchtower.repositories.api_keys import (
    create_api_key,
    get_api_key_by_id,
    get_profile_uptime_key,
    list_authorized_api_keys,
    list_profile_uptime_keys,
)
from watchtower.repositories.monitored_services import has_application_permission
from watchtower.schemas.api_key import ApiKeyCreate, ApiKeyUpdate


class ApiKeyNotFoundError(LookupError):
    """The requested API key does not exist."""


class ApplicationNotFoundError(LookupError):
    """The requested application does not exist."""


class ApplicationAccessDeniedError(PermissionError):
    """The human actor lacks permission on the key's application."""


class ApiKeyConflictError(ValueError):
    """The requested key metadata conflicts with an explicit API-key rule."""


def _integrity_constraint_name(exc: IntegrityError) -> str | None:
    """Extract a PostgreSQL constraint name without broad error translation."""

    for candidate in (exc.orig, getattr(exc.orig, "__cause__", None)):
        name = getattr(candidate, "constraint_name", None)
        if isinstance(name, str):
            return name
    return None


async def _require_permission(
    session: AsyncSession,
    *,
    profile_id: UUID,
    application_id: UUID,
    permission_name: str,
) -> None:
    if not await has_application_permission(
        session,
        profile_id=profile_id,
        application_id=application_id,
        permission_name=permission_name,
    ):
        raise ApplicationAccessDeniedError("Application access denied")


async def _get_bound_key(
    session: AsyncSession,
    *,
    api_key_id: UUID,
    for_update: bool,
) -> ApiKey:
    api_key = await get_api_key_by_id(session, api_key_id=api_key_id, for_update=for_update)
    if api_key is None:
        raise ApiKeyNotFoundError("API key not found")
    if api_key.credential_kind == "profile_uptime":
        raise ApiKeyConflictError("Profile uptime keys can only be reissued")
    if api_key.service_id is None:
        raise ApiKeyNotFoundError("API key not found")
    return api_key


async def _lock_application(
    session: AsyncSession, *, application_id: UUID
) -> MonitoredService | None:
    """Serialize key mutations with membership changes for one application."""

    application: MonitoredService | None = await session.scalar(
        select(MonitoredService).where(MonitoredService.id == application_id).with_for_update()
    )
    return application


async def _get_bound_key_for_mutation(session: AsyncSession, *, api_key_id: UUID) -> ApiKey:
    """Acquire application then key locks before mutation authorization."""

    candidate = await _get_bound_key(session, api_key_id=api_key_id, for_update=False)
    assert candidate.service_id is not None
    if await _lock_application(session, application_id=candidate.service_id) is None:
        raise ApiKeyNotFoundError("API key not found")
    return await _get_bound_key(session, api_key_id=api_key_id, for_update=True)


async def issue_api_key(
    session: AsyncSession,
    *,
    profile_id: UUID,
    payload: ApiKeyCreate,
) -> tuple[ApiKey, SecretStr]:
    """Issue a service-bound key and retain the human creator as metadata."""

    generated = generate_api_key()
    token = generated.token.get_secret_value()
    assert payload.service_id is not None
    assert payload.name is not None
    try:
        async with session.begin():
            application = await _lock_application(session, application_id=payload.service_id)
            if application is None:
                raise ApplicationNotFoundError("Application not found")
            await _require_permission(
                session,
                profile_id=profile_id,
                application_id=application.id,
                permission_name="api_keys.manage",
            )
            api_key = await create_api_key(
                session,
                profile_id=profile_id,
                name=payload.name,
                public_prefix=generated.public_prefix,
                secret_digest=digest_api_key(token),
                service_id=application.id,
                expires_at=payload.expires_at,
            )
    except IntegrityError as exc:
        if _integrity_constraint_name(exc) != "uq_api_key_service_name":
            raise
        raise ApiKeyConflictError("API key name already exists") from exc
    return api_key, generated.token


async def issue_profile_uptime_key(
    session: AsyncSession, *, profile_id: UUID
) -> tuple[ApiKey, SecretStr, bool]:
    """Issue or atomically reissue the singleton profile uptime credential."""

    generated = generate_profile_api_key()
    token = generated.token.get_secret_value()
    async with session.begin():
        profile = await session.scalar(
            select(Profile).where(Profile.id == profile_id).with_for_update()
        )
        if profile is None:
            raise ApiKeyNotFoundError("Profile not found")
        if profile.status != "active":
            raise ApplicationAccessDeniedError("Profile access denied")
        api_key = await get_profile_uptime_key(
            session, profile_id=profile_id, for_update=True
        )
        created = api_key is None
        if api_key is None:
            api_key = ApiKey(
                profile_id=profile_id,
                name="Profile uptime API",
                credential_kind="profile_uptime",
                public_prefix=generated.public_prefix,
                secret_digest=digest_profile_api_key(token),
                scopes=["uptime:read"],
                service_id=None,
            )
            session.add(api_key)
        else:
            api_key.public_prefix = generated.public_prefix
            api_key.secret_digest = digest_profile_api_key(token)
            api_key.rotated_at = datetime.now(UTC)
            api_key.last_used_at = None
        await session.flush()
        await session.refresh(api_key)
    return api_key, generated.token, created


async def list_profile_api_keys(session: AsyncSession, *, profile_id: UUID) -> list[ApiKey]:
    """List service-bound keys in applications the actor may read."""

    async with session.begin():
        service_keys = await list_authorized_api_keys(
            session, profile_id=profile_id, permission_name="api_keys.read"
        )
        profile_keys = await list_profile_uptime_keys(session, profile_id=profile_id)
        return sorted([*service_keys, *profile_keys], key=lambda key: (key.created_at, key.id))


async def get_profile_api_key(
    session: AsyncSession, *, profile_id: UUID, api_key_id: UUID
) -> ApiKey:
    """Read one key after a PostgreSQL-backed application permission check."""

    async with session.begin():
        api_key = await _get_bound_key(session, api_key_id=api_key_id, for_update=False)
        assert api_key.service_id is not None
        await _require_permission(
            session,
            profile_id=profile_id,
            application_id=api_key.service_id,
            permission_name="api_keys.read",
        )
        return api_key


async def update_profile_api_key(
    session: AsyncSession,
    *,
    profile_id: UUID,
    api_key_id: UUID,
    payload: ApiKeyUpdate,
) -> ApiKey:
    """Lock, authorize, and update safe metadata in one transaction."""

    try:
        async with session.begin():
            api_key = await _get_bound_key_for_mutation(session, api_key_id=api_key_id)
            assert api_key.service_id is not None
            await _require_permission(
                session,
                profile_id=profile_id,
                application_id=api_key.service_id,
                permission_name="api_keys.manage",
            )
            fields = payload.model_dump(exclude_unset=True)
            if "expires_at" in fields:
                requested_expiry = fields["expires_at"]
                if requested_expiry is None or (
                    api_key.expires_at is not None and requested_expiry > api_key.expires_at
                ):
                    raise ApiKeyConflictError("API key expiry cannot be extended or removed")
            for field, value in fields.items():
                setattr(api_key, field, value)
            await session.flush()
            await session.refresh(api_key)
            return api_key
    except IntegrityError as exc:
        if _integrity_constraint_name(exc) != "uq_api_key_service_name":
            raise
        raise ApiKeyConflictError("API key name already exists") from exc


async def revoke_api_key(session: AsyncSession, *, profile_id: UUID, api_key_id: UUID) -> None:
    """Lock, authorize, and soft-revoke a key immediately and idempotently."""

    async with session.begin():
        api_key = await _get_bound_key_for_mutation(session, api_key_id=api_key_id)
        assert api_key.service_id is not None
        await _require_permission(
            session,
            profile_id=profile_id,
            application_id=api_key.service_id,
            permission_name="api_keys.manage",
        )
        if api_key.revoked_at is None:
            api_key.revoked_at = datetime.now(UTC)
            await session.flush()
