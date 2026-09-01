"""Async SQLAlchemy engine and session factories."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_async_database_engine(
    database_url: str,
    *,
    pool_size: int | None = None,
    max_overflow: int | None = None,
) -> AsyncEngine:
    """Create a lazy async engine; no connection is made here."""

    pool_options: dict[str, int] = {}
    if pool_size is not None:
        pool_options["pool_size"] = pool_size
    if max_overflow is not None:
        pool_options["max_overflow"] = max_overflow
    return create_async_engine(database_url, pool_pre_ping=True, **pool_options)


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
