import os

import pytest
from sqlalchemy import text

from watchtower.db.session import create_async_database_engine, create_session_factory

DATABASE_URL = os.environ.get(
    "WATCHTOWER_DATABASE_URL",
    "postgresql+asyncpg://watchtower:watchtower@db:5432/watchtower_test",
)


@pytest.mark.integration
async def test_database_transaction_rolls_back() -> None:
    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)

    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS watchtower._transaction_probe "
                    "(id integer PRIMARY KEY)"
                )
            )
            await connection.execute(text("TRUNCATE watchtower._transaction_probe"))

        async with factory() as session:
            await session.execute(
                text("INSERT INTO watchtower._transaction_probe (id) VALUES (1)")
            )
            await session.rollback()

        async with factory() as session:
            count = await session.scalar(
                text("SELECT count(*) FROM watchtower._transaction_probe")
            )

        assert count == 0
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DROP TABLE IF EXISTS watchtower._transaction_probe")
            )
        await engine.dispose()
