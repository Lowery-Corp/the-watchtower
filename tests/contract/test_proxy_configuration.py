"""Contract tests for the checked-in webhook edge controls."""

from pathlib import Path


def test_nginx_webhook_boundary_enforces_body_and_rate_limits() -> None:
    config = Path("deploy/nginx/default.conf").read_text(encoding="utf-8")

    assert (
        "limit_req_zone $binary_remote_addr zone=watchtower_webhooks:10m rate=60r/m;"
        in config
    )
    assert "client_max_body_size 256k;" in config
    assert "limit_req_status 429;" in config
    assert "location = /api/v1/webhooks/events {" in config
    assert "limit_req zone=watchtower_webhooks burst=20 nodelay;" in config
