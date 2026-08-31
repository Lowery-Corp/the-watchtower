"""Contract tests for the direct Compose frontend and API topology."""

from pathlib import Path


def test_compose_publishes_frontend_and_api_without_nginx() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    test_dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    frontend_dockerfile = Path("watchtowersHouse/Dockerfile").read_text(encoding="utf-8")
    frontend_server = Path("watchtowersHouse/server.mjs").read_text(encoding="utf-8")
    vite_config = Path("watchtowersHouse/vite.config.js").read_text(encoding="utf-8")

    assert "  proxy:" not in compose
    assert "nginx" not in compose.lower()
    assert '${WATCHTOWER_FRONTEND_PORT:-5174}:5173' in compose
    assert '127.0.0.1:${WATCHTOWER_API_PORT:-8001}:8000' in compose
    assert '127.0.0.1:${WATCHTOWER_POSTGRES_PORT:-5433}:5432' in compose
    assert "WATCHTOWER_MAX_REQUEST_BODY_BYTES" in compose
    assert '\n      - "${WATCHTOWER_API_PORT:-8001}:8000"' not in compose
    assert frontend_dockerfile.count("FROM node:24-alpine@sha256:") == 2
    assert "FROM node:20-alpine" not in frontend_dockerfile
    assert "nginx" not in frontend_dockerfile.lower()
    assert 'CMD ["node", "server.mjs"]' in frontend_dockerfile
    assert "COPY deploy/" not in test_dockerfile
    assert 'target: "http://api:8000"' in vite_config
    assert 'allowedHosts: ["dwatchtower.johnmgrubbs.io"]' in vite_config
    assert '"dwatchtower.johnmgrubbs.io"' in frontend_server
    assert '"Content-Security-Policy"' in frontend_server
    assert "connect-src 'self'" in frontend_server
    assert "ws:" not in frontend_server
    assert '"X-Frame-Options": "DENY"' in frontend_server
    assert '"X-Content-Type-Options": "nosniff"' in frontend_server
    assert '"Referrer-Policy": "no-referrer"' in frontend_server
    assert '"Permissions-Policy"' in frontend_server
    assert "https://dwatchtower.johnmgrubbs.io" in compose
    assert not Path("deploy/nginx/default.conf").exists()



def test_compose_runs_private_uptime_worker_after_migrations() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")
    assert "  uptime-worker:" in compose
    section = compose.split("  uptime-worker:", 1)[1].split("\n  frontend:", 1)[0]
    assert 'command: ["python", "-m", "watchtower.workers.uptime"]' in section
    assert "restart: unless-stopped" in section
    assert "stop_grace_period: 20s" in section
    assert "migrate:" in section
    assert "condition: service_completed_successfully" in section
    assert "ports:" not in section
    assert "WATCHTOWER_UPTIME_CHECK_INTERVAL_SECONDS" in section
    assert "WATCHTOWER_UPTIME_CHECK_TIMEOUT_SECONDS" in section
