"""Reversible PostgreSQL schema coverage for website uptime monitoring."""

import asyncio
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


async def _run_alembic(database_url: str, *arguments: str) -> None:
    process = await asyncio.create_subprocess_exec(
        "alembic",
        *arguments,
        env={**os.environ, "WATCHTOWER_DATABASE_URL": database_url},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    assert process.returncode == 0, output.decode()


@pytest_asyncio.fixture
async def uptime_migration_database() -> AsyncIterator[str]:
    source_url = make_url(os.environ["WATCHTOWER_DATABASE_URL"])
    database_name = f"watchtower_uptime_{uuid4().hex}"
    admin_url = source_url.set(database="postgres").render_as_string(hide_password=False)
    database_url = source_url.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    try:
        await _run_alembic(database_url, "upgrade", "head")
        yield database_url
    finally:
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": database_name},
            )
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        await admin_engine.dispose()


async def _assert_uptime_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            tables = set(
                await connection.scalars(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'watchtower'"
                    )
                )
            )
            constraints = set(
                await connection.scalars(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE connamespace = 'watchtower'::regnamespace "
                        "AND conrelid IN ('watchtower.website_monitor'::regclass, "
                        "'watchtower.website_monitor_check'::regclass)"
                    )
                )
            )
            indexes = set(
                await connection.scalars(
                    text(
                        "SELECT indexname FROM pg_indexes WHERE schemaname = 'watchtower' "
                        "AND tablename IN ('website_monitor', 'website_monitor_check')"
                    )
                )
            )
        assert {"website_monitor", "website_monitor_check"} <= tables
        assert {
            "pk_website_monitor",
            "fk_website_monitor_service",
            "uq_website_monitor_service_url",
            "ck_website_monitor_last_status_code",
            "ck_website_monitor_last_response_time",
            "pk_website_monitor_check",
            "fk_website_monitor_check_monitor",
            "ck_website_monitor_check_status_code",
            "ck_website_monitor_check_response_time",
        } <= constraints
        assert {
            "ix_website_monitor_due",
            "ix_website_monitor_service",
            "ix_website_monitor_check_monitor_checked",
            "ix_website_monitor_check_checked_at",
        } <= indexes
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_uptime_schema_upgrades_downgrades_and_reupgrades(
    uptime_migration_database: str,
) -> None:
    await _assert_uptime_schema(uptime_migration_database)

    await _run_alembic(
        uptime_migration_database, "downgrade", "0015_api_key_application_rbac"
    )
    engine = create_async_engine(uptime_migration_database)
    try:
        async with engine.connect() as connection:
            tables = set(
                await connection.scalars(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'watchtower'"
                    )
                )
            )
        assert "website_monitor" not in tables
        assert "website_monitor_check" not in tables
    finally:
        await engine.dispose()

    await _run_alembic(uptime_migration_database, "upgrade", "head")
    await _assert_uptime_schema(uptime_migration_database)
