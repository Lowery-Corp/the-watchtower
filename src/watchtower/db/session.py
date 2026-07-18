"""Async SQLAlchemy engine and session factories."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_async_database_engine(database_url: str) -> AsyncEngine:
    """Create a lazy async engine; no connection is made here."""

    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(
    database_url: str,
    *,
    engine: AsyncEngine | None = None,
) -> async_sessionmaker[AsyncSession]:
    """Create an AsyncSession factory with caller-owned transactions."""

    bound_engine = engine or create_async_database_engine(database_url)
    return async_sessionmaker(
        bind=bound_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
