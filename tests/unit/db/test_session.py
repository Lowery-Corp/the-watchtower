from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.db.session import create_session_factory


def test_session_factory_uses_async_sqlalchemy() -> None:
    factory = create_session_factory(
        "postgresql+asyncpg://watchtower:test@db:5432/watchtower_test"
    )

    assert factory.class_ is AsyncSession
