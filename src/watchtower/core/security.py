"""Webhook authentication primitives."""

import hashlib
import hmac
import re
from datetime import UTC, datetime

_SIGNATURE_PATTERN = re.compile(r"^v1=[0-9a-f]{64}$")
_SERVICE_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_TIMESTAMP_PATTERN = re.compile(r"^[0-9]{1,12}$")
_AUTHENTICATION_ERROR = "Invalid webhook authentication"


class WebhookAuthenticationError(ValueError):
    """Raised when a signed webhook request cannot be authenticated."""


def compute_webhook_signature(
    *,
    secret: str,
    service: str,
    timestamp: str,
    body: bytes,
) -> str:
    """Return a version-one HMAC-SHA256 signature for a raw request body."""

    body_digest = hashlib.sha256(body).hexdigest()
    canonical = f"v1\n{timestamp}\n{service}\n{body_digest}".encode()
    digest = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
    return f"v1={digest}"


def validate_webhook_headers(
    *,
    service: str,
    timestamp_header: str,
    signature_header: str,
    now: datetime | None = None,
    tolerance_seconds: int = 300,
) -> None:
    """Reject malformed or stale authentication metadata without reading a body."""

    try:
        if not _SERVICE_PATTERN.fullmatch(service):
            raise WebhookAuthenticationError(_AUTHENTICATION_ERROR)
        if not _TIMESTAMP_PATTERN.fullmatch(timestamp_header):
            raise WebhookAuthenticationError(_AUTHENTICATION_ERROR)
        if not _SIGNATURE_PATTERN.fullmatch(signature_header):
            raise WebhookAuthenticationError(_AUTHENTICATION_ERROR)

        signed_at = datetime.fromtimestamp(int(timestamp_header), tz=UTC)
        current_time = now.astimezone(UTC) if now is not None else datetime.now(UTC)
        if abs((current_time - signed_at).total_seconds()) > tolerance_seconds:
            raise WebhookAuthenticationError(_AUTHENTICATION_ERROR)
    except (OverflowError, OSError, ValueError) as exc:
        if isinstance(exc, WebhookAuthenticationError):
            raise
        raise WebhookAuthenticationError(_AUTHENTICATION_ERROR) from exc


def verify_webhook_signature(
    *,
    secret: str,
    service: str,
    timestamp_header: str,
    signature_header: str,
    body: bytes,
    now: datetime | None = None,
    tolerance_seconds: int = 300,
) -> None:
    """Validate header freshness and HMAC body integrity."""

    if not secret:
        raise WebhookAuthenticationError(_AUTHENTICATION_ERROR)
    validate_webhook_headers(
        service=service,
        timestamp_header=timestamp_header,
        signature_header=signature_header,
        now=now,
        tolerance_seconds=tolerance_seconds,
    )
    expected = compute_webhook_signature(
        secret=secret,
        service=service,
        timestamp=timestamp_header,
        body=body,
    )
    if not hmac.compare_digest(expected, signature_header):
        raise WebhookAuthenticationError(_AUTHENTICATION_ERROR)
