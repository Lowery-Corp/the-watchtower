import os
from collections.abc import AsyncIterator
from typing import Annotated

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from watchtower.core.config import Settings
from watchtower.db.dependencies import get_db_session
from watchtower.main import create_app

DATABASE_URL = os.environ.get(
    "WATCHTOWER_DATABASE_URL",
    "postgresql+asyncpg://watchtower:watchtower@db:5432/watchtower_test",
)


class UnavailableSession:
    async def execute(self, statement: object) -> None:
        raise ConnectionError("database unavailable")


async def unavailable_session() -> AsyncIterator[UnavailableSession]:
    yield UnavailableSession()


async def test_application_database_url_controls_dependency_session_factory() -> None:
    database_url = "postgresql+asyncpg://custom-db:5432/application_database"
    app = create_app(Settings(environment="test", database_url=database_url))

    @app.get("/session-database-url")
    async def session_database_url(
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> dict[str, str]:
        assert isinstance(session.bind, AsyncEngine)
        return {"database_url": str(session.bind.url)}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/session-database-url")

    assert response.status_code == 200
    assert response.json() == {"database_url": database_url}


async def test_readiness_reports_database_failure_without_details() -> None:
    app = create_app(Settings(environment="test"))
    app.dependency_overrides[get_db_session] = unavailable_session
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health/ready")
        live_response = await client.get("/api/v1/health/live")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "service": "watchtower"}
    assert "database unavailable" not in response.text
    assert live_response.status_code == 200


@pytest.mark.integration
async def test_readiness_reports_success_with_application_database() -> None:
    app = create_app(Settings(environment="test", database_url=DATABASE_URL))
    transport = ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "service": "watchtower"}
