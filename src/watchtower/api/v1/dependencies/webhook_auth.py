"""FastAPI dependency for authenticated raw webhook requests."""

from dataclasses import dataclass
from secrets import token_urlsafe
from typing import cast

from fastapi import HTTPException, Request, status

from watchtower.core.config import Settings
from watchtower.core.rate_limit import FixedWindowRateLimiter
from watchtower.core.security import (
    WebhookAuthenticationError,
    validate_webhook_headers,
    verify_webhook_signature,
)

_GENERIC_AUTH_ERROR = "Invalid webhook authentication"
_DUMMY_SECRET = token_urlsafe(32)


@dataclass(frozen=True, slots=True)
class AuthenticatedWebhook:
    """Authenticated source identity paired with its exact signed bytes."""

    source: str
    body: bytes


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


async def authenticate_webhook(request: Request) -> AuthenticatedWebhook:
    """Authenticate a service using timestamped HMAC over the raw request body."""

    settings = cast(Settings, request.app.state.settings)
    source = request.headers.get("X-Watchtower-Service", "")
    timestamp = request.headers.get("X-Watchtower-Timestamp", "")
    signature = request.headers.get("X-Watchtower-Signature", "")
    try:
        validate_webhook_headers(
            service=source,
            timestamp_header=timestamp,
            signature_header=signature,
            tolerance_seconds=settings.webhook_signature_tolerance_seconds,
        )
    except WebhookAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_GENERIC_AUTH_ERROR,
        ) from exc

    body = await read_limited_body(request, settings.max_webhook_body_bytes)
    configured_secret = settings.webhook_secrets.get(source)
    secret = (
        configured_secret.get_secret_value()
        if configured_secret is not None
        else _DUMMY_SECRET
    )

    try:
        verify_webhook_signature(
            secret=secret,
            service=source,
            timestamp_header=timestamp,
            signature_header=signature,
            body=body,
            tolerance_seconds=settings.webhook_signature_tolerance_seconds,
        )
        if configured_secret is None:
            raise WebhookAuthenticationError(_GENERIC_AUTH_ERROR)
    except WebhookAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_GENERIC_AUTH_ERROR,
        ) from exc

    limiter = cast(FixedWindowRateLimiter, request.app.state.webhook_rate_limiter)
    retry_after = await limiter.consume(source)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Webhook rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    return AuthenticatedWebhook(source=source, body=body)
