from uuid import UUID

from httpx import ASGITransport, AsyncClient, Response

from watchtower.core.config import Settings
from watchtower.main import create_app


async def request(path: str, request_id: str | None = None) -> Response:
    app = create_app(Settings(environment="test"))
    transport = ASGITransport(app=app)
    headers = {"X-Request-ID": request_id} if request_id else None
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


async def test_health_reports_service_status() -> None:
    response = await request("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "watchtower"}


async def test_liveness_does_not_require_external_dependencies() -> None:
    response = await request("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive", "service": "watchtower"}


async def test_response_generates_request_id() -> None:
    response = await request("/api/v1/health")

    UUID(response.headers["X-Request-ID"])


async def test_response_preserves_valid_request_id() -> None:
    response = await request(
        "/api/v1/health",
        request_id="deploy-2026.07.18:abc_123",
    )

    assert response.headers["X-Request-ID"] == "deploy-2026.07.18:abc_123"


async def test_response_replaces_invalid_request_id() -> None:
    response = await request(
        "/api/v1/health",
        request_id="contains spaces",
    )

    assert response.headers["X-Request-ID"] != "contains spaces"
    UUID(response.headers["X-Request-ID"])


async def test_unhandled_exception_response_has_request_id_without_details() -> None:
    app = create_app(Settings(environment="test"))

    @app.get("/raises")
    async def raises() -> None:
        raise RuntimeError("sensitive exception details")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/raises")

    assert response.status_code == 500
    UUID(response.headers["X-Request-ID"])
    assert "sensitive exception details" not in response.text
