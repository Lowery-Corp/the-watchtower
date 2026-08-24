"""Tenant-aware authentication for raw webhook requests."""

from dataclasses import dataclass
from datetime import UTC, datetime
from secrets import token_urlsafe
from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.core.api_keys import (
    ApiKeyFormatError,
    digest_api_key,
    parse_api_key,
    verify_api_key,
)
from watchtower.core.config import Settings
from watchtower.core.security import (
    WebhookAuthenticationError,
    validate_service_identity,
    validate_webhook_headers,
    verify_webhook_signature,
)
from watchtower.db.dependencies import get_db_session
from watchtower.repositories.api_keys import get_api_key_by_prefix
from watchtower.repositories.monitored_services import get_monitored_service_by_slug
from watchtower.services.webhook_rate_limits import consume_webhook_rate_limit

_GENERIC_AUTH_ERROR = "Invalid webhook authentication"
_DUMMY_SECRET = token_urlsafe(32)
_DUMMY_API_KEY_DIGEST = digest_api_key(
    "wtk_v1_aaaaaaaaaaaaaaaa.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
)


@dataclass(frozen=True, slots=True)
class AuthenticatedWebhook:
    """Authenticated tenant/source identity paired with exact request bytes."""

    profile_id: UUID
    source: str
    body: bytes
    api_key_id: UUID | None = None
    api_key_token: SecretStr | None = None


async def read_limited_body(request: Request, limit: int) -> bytes:
    """Read at most ``limit`` bytes without parsing or logging the payload."""

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > limit:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="Webhook body exceeds configured limit",
                )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Content-Length header",
            ) from exc

    body = bytearray()
    async for chunk in request.stream():
        if len(chunk) > limit - len(body):
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Webhook body exceeds configured limit",
            )
        body.extend(chunk)
    return bytes(body)


def _unauthorized(exc: Exception | None = None) -> HTTPException:
    del exc
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_GENERIC_AUTH_ERROR,
    )


async def _consume_rate_limit(
    session: AsyncSession,
    settings: Settings,
    identity: str,
) -> None:
    retry_after = await consume_webhook_rate_limit(
        session,
        identity=identity,
        max_requests=settings.webhook_rate_limit_requests,
        window_seconds=settings.webhook_rate_limit_window_seconds,
    )
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Webhook rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )


async def _authenticate_managed_key(
    *,
    session: AsyncSession,
    source: str,
    token: str,
) -> tuple[UUID, UUID]:
    """Resolve and validate one managed key before request-body consumption."""

    try:
        validate_service_identity(source)
        parsed = parse_api_key(token)
    except (ApiKeyFormatError, WebhookAuthenticationError) as exc:
        raise _unauthorized(exc) from exc

    now = datetime.now(UTC)
    async with session.begin():
        api_key = await get_api_key_by_prefix(session, public_prefix=parsed.public_prefix)
        expected_digest = api_key.secret_digest if api_key is not None else _DUMMY_API_KEY_DIGEST
        verified = verify_api_key(token, expected_digest)
        if (
            api_key is None
            or not verified
            or api_key.revoked_at is not None
            or (api_key.expires_at is not None and api_key.expires_at <= now)
            or "events:write" not in api_key.scopes
        ):
            raise _unauthorized()

        service = await get_monitored_service_by_slug(
            session,
            profile_id=api_key.profile_id,
            slug=source,
        )
        if (
            service is None
            or not service.active
            or (api_key.service_id is not None and api_key.service_id != service.id)
        ):
            raise _unauthorized()

        return api_key.profile_id, api_key.id


async def authenticate_webhook(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthenticatedWebhook:
    """Authenticate managed API keys or explicitly mapped legacy HMAC senders."""

    settings = cast(Settings, request.app.state.settings)
    source_values = request.headers.getlist("X-Watchtower-Service")
    managed_values = request.headers.getlist("X-Watchtower-API-Key")
    if len(source_values) != 1 or len(managed_values) > 1:
        raise _unauthorized()
    source = source_values[0]
    managed_token = managed_values[0] if managed_values else None

    if managed_token is not None:
        profile_id, api_key_id = await _authenticate_managed_key(
            session=session,
            source=source,
            token=managed_token,
        )
        await _consume_rate_limit(session, settings, f"managed:{api_key_id}")
        body = await read_limited_body(request, settings.max_webhook_body_bytes)
        return AuthenticatedWebhook(
            profile_id=profile_id,
            source=source,
            body=body,
            api_key_id=api_key_id,
            api_key_token=SecretStr(managed_token),
        )

    timestamp_values = request.headers.getlist("X-Watchtower-Timestamp")
    signature_values = request.headers.getlist("X-Watchtower-Signature")
    if len(timestamp_values) != 1 or len(signature_values) != 1:
        raise _unauthorized()
    timestamp = timestamp_values[0]
    signature = signature_values[0]
    try:
        validate_webhook_headers(
            service=source,
            timestamp_header=timestamp,
            signature_header=signature,
            tolerance_seconds=settings.webhook_signature_tolerance_seconds,
        )
    except WebhookAuthenticationError as exc:
        raise _unauthorized(exc) from exc

    configured_secret = settings.webhook_secrets.get(source)
    legacy_profile_id = settings.legacy_webhook_profiles.get(source)
    if configured_secret is None or legacy_profile_id is None:
        raise _unauthorized()

    body = await read_limited_body(request, settings.max_webhook_body_bytes)
    try:
        verify_webhook_signature(
            secret=configured_secret.get_secret_value(),
            service=source,
            timestamp_header=timestamp,
            signature_header=signature,
            body=body,
            tolerance_seconds=settings.webhook_signature_tolerance_seconds,
        )
    except WebhookAuthenticationError as exc:
        raise _unauthorized(exc) from exc

    await _consume_rate_limit(
        session,
        settings,
        f"legacy:{legacy_profile_id}:{source}",
    )
    return AuthenticatedWebhook(profile_id=legacy_profile_id, source=source, body=body)
