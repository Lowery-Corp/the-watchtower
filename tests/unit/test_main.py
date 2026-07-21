import json
from unittest.mock import AsyncMock

import structlog
from fastapi import FastAPI
from pytest import CaptureFixture, MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncEngine

from watchtower.core.logging import get_logger
from watchtower.main import create_app


def test_create_app_exposes_watchtower_metadata() -> None:
    app = create_app()

    assert isinstance(app, FastAPI)
    assert app.title == "The Watchtower"
    assert app.version == "0.1.0"
    assert app.openapi_url == "/api/v1/openapi.json"


def test_create_app_configures_structured_logging(capsys: CaptureFixture[str]) -> None:
    structlog.reset_defaults()

    create_app()
    get_logger("watchtower.test").info("app_created")

    record = json.loads(capsys.readouterr().out)
    assert record["event"] == "app_created"
    assert record["logger"] == "watchtower.test"


async def test_application_disposes_owned_engine_on_shutdown(
    monkeypatch: MonkeyPatch,
) -> None:
    app = create_app()
    dispose = AsyncMock()
    monkeypatch.setattr(AsyncEngine, "dispose", dispose)

    async with app.router.lifespan_context(app):
        pass

    dispose.assert_awaited_once_with()
