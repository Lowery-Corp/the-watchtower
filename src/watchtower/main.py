"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from watchtower import __version__
from watchtower.api.v1.api import router as api_v1_router
from watchtower.core.config import Settings, get_settings
from watchtower.core.logging import configure_logging
from watchtower.db.session import create_async_database_engine, create_session_factory
from watchtower.middleware.request_context import RequestContextMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a Watchtower API without connecting to external services."""

    configure_logging()
    resolved_settings = settings or get_settings()
    engine = create_async_database_engine(resolved_settings.database_url)
    session_factory = create_session_factory(resolved_settings.database_url, engine=engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title="The Watchtower",
        version=__version__,
        openapi_url="/api/v1/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.add_middleware(RequestContextMiddleware)
    app.include_router(api_v1_router)
    return app


app = create_app()
