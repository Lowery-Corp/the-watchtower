"""Security tests for version-one webhook signatures."""

import hmac
from datetime import UTC, datetime, timedelta

import pytest

from watchtower.core.security import (
    WebhookAuthenticationError,
    compute_webhook_signature,
    verify_webhook_signature,
)

NOW = datetime(2026, 7, 18, 20, 0, tzinfo=UTC)
TIMESTAMP = str(int(NOW.timestamp()))
BODY = b'{"event_id":"0c34b762-04f9-4df5-80a0-7ff773d7e13d"}'
SECRET = "correct-horse-battery-staple"
SERVICE = "scrappy"


def signature(*, body: bytes = BODY, secret: str = SECRET) -> str:
    return compute_webhook_signature(
        secret=secret,
        service=SERVICE,
        timestamp=TIMESTAMP,
        body=body,
    )


def test_valid_signature_is_accepted() -> None:
    verify_webhook_signature(
        secret=SECRET,
        service=SERVICE,
        timestamp_header=TIMESTAMP,
        signature_header=signature(),
        body=BODY,
        now=NOW,
        tolerance_seconds=300,
    )


@pytest.mark.parametrize(
    ("secret", "body", "timestamp", "signature_header"),
    [
        ("wrong-secret", BODY, TIMESTAMP, signature()),
        (SECRET, b'{"altered":true}', TIMESTAMP, signature()),
        (SECRET, BODY, "not-a-timestamp", signature()),
        (SECRET, BODY, TIMESTAMP, "sha256=not-versioned"),
        (SECRET, BODY, TIMESTAMP, "v1=not-hex"),
    ],
)
def test_invalid_authentication_uses_one_generic_error(
    secret: str,
    body: bytes,
    timestamp: str,
    signature_header: str,
) -> None:
    with pytest.raises(WebhookAuthenticationError, match="Invalid webhook authentication"):
        verify_webhook_signature(
            secret=secret,
            service=SERVICE,
            timestamp_header=timestamp,
            signature_header=signature_header,
            body=body,
            now=NOW,
            tolerance_seconds=300,
        )


def test_stale_signature_is_rejected() -> None:
    stale_now = NOW + timedelta(seconds=301)

    with pytest.raises(WebhookAuthenticationError, match="Invalid webhook authentication"):
        verify_webhook_signature(
            secret=SECRET,
            service=SERVICE,
            timestamp_header=TIMESTAMP,
            signature_header=signature(),
            body=BODY,
            now=stale_now,
            tolerance_seconds=300,
        )


def test_signature_comparison_is_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    original = hmac.compare_digest

    def recording_compare_digest(left: str, right: str) -> bool:
        calls.append((left, right))
        return original(left, right)

    monkeypatch.setattr(hmac, "compare_digest", recording_compare_digest)

    verify_webhook_signature(
        secret=SECRET,
        service=SERVICE,
        timestamp_header=TIMESTAMP,
        signature_header=signature(),
        body=BODY,
        now=NOW,
        tolerance_seconds=300,
    )

    assert len(calls) == 1
