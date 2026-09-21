"""Website monitor request contract tests."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from watchtower.schemas.website_monitor import WebsiteMonitorCreate


def test_create_requires_exactly_canonical_url_and_service_id() -> None:
    service_id = uuid4()
    payload = WebsiteMonitorCreate(
        url="HTTPS://Example.COM",
        service_id=service_id,
    )

    assert payload.model_dump() == {
        "url": "https://example.com/",
        "service_id": service_id,
    }
    with pytest.raises(ValidationError):
        WebsiteMonitorCreate.model_validate(
            {
                "url": "https://example.com",
                "service_id": service_id,
                "interval_seconds": 5,
            }
        )


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "https://user:password@example.com/",
        "https://example.com/path#fragment",
        "https://example.com:8443/",
        "http://localhost/",
        "http://service.localhost/",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://224.0.0.1/",
        "http://192.0.2.1/",
        "http://[::1]/",
        "http://[fc00::1]/",
    ],
)
def test_create_rejects_unsafe_or_nonwebsite_targets(url: str) -> None:
    with pytest.raises(ValidationError):
        WebsiteMonitorCreate(url=url, service_id=uuid4())
