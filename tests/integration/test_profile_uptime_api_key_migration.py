"""Lifecycle coverage for the profile uptime API-key migration."""

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import RowMapping, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

PARENT_REVISION = "0016_uptime_monitoring"
PROFILE_UPTIME_REVISION = "0017_profile_uptime_keys"


@dataclass(frozen=True)
class ProfileUptimeMigrationDatabase:
    url: str
    profile_id: UUID
    service_id: UUID
    bound_key_id: UUID
    revoked_key_id: UUID


async def _run_alembic(database_url: str, *arguments: str, succeeds: bool = True) -> str:
    process = await asyncio.create_subprocess_exec(
        "alembic",
        *arguments,
        env={**os.environ, "WATCHTOWER_DATABASE_URL": database_url},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    rendered = output.decode()
    assert (process.returncode == 0) is succeeds, rendered
    return rendered


async def _catalog(
    connection: AsyncConnection,
) -> tuple[dict[str, RowMapping], dict[str, RowMapping], dict[str, RowMapping]]:
    columns = {
        row["column_name"]: row
        for row in (
            await connection.execute(
                text(
                    "SELECT column_name, data_type, udt_name, is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'watchtower' AND table_name = 'api_key'"
                )
            )
        ).mappings()
    }
    constraints = {
        row["conname"]: row
        for row in (
            await connection.execute(
                text(
                    "SELECT conname, contype::text AS contype, "
                    "pg_get_constraintdef(oid, true) AS definition "
                    "FROM pg_constraint WHERE conrelid = 'watchtower.api_key'::regclass"
                )
            )
        ).mappings()
    }
    indexes = {
        row["indexname"]: row
        for row in (
            await connection.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname = 'watchtower' AND tablename = 'api_key'"
                )
            )
        ).mappings()
    }
    return columns, constraints, indexes


def _assert_parent_schema(
    columns: dict[str, RowMapping],
    constraints: dict[str, RowMapping],
    indexes: dict[str, RowMapping],
) -> None:
    assert set(columns) == {
        "id",
        "profile_id",
        "name",
        "token_version",
        "public_prefix",
        "secret_digest",
        "scopes",
        "service_id",
        "created_at",
        "expires_at",
        "last_used_at",
        "revoked_at",
    }
    assert columns["service_id"]["is_nullable"] == "YES"
    assert columns["token_version"]["column_default"] == "1"
    assert set(constraints) == {
        "ck_api_key_expires_after_creation",
        "ck_api_key_scopes_array",
        "ck_api_key_secret_digest_length",
        "ck_api_key_service_or_revoked",
        "fk_api_key_profile",
        "fk_api_key_service",
        "pk_api_key",
        "uq_api_key_public_prefix",
        "uq_api_key_secret_digest",
        "uq_api_key_service_name",
    }
    assert set(indexes) == {
        "ix_api_key_profile",
        "ix_api_key_service_revoked",
        "pk_api_key",
        "uq_api_key_public_prefix",
        "uq_api_key_secret_digest",
        "uq_api_key_service_name",
    }
    assert constraints["ck_api_key_service_or_revoked"]["definition"] == (
        "CHECK (service_id IS NOT NULL OR revoked_at IS NOT NULL)"
    )


def _assert_profile_uptime_schema(
    columns: dict[str, RowMapping],
    constraints: dict[str, RowMapping],
    indexes: dict[str, RowMapping],
) -> None:
    kind = columns["credential_kind"]
    assert (kind["data_type"], kind["udt_name"], kind["is_nullable"]) == (
        "character varying",
        "varchar",
        "NO",
    )
    assert kind["column_default"] == "'service_ingestion'::character varying"
    rotated = columns["rotated_at"]
    assert (rotated["data_type"], rotated["udt_name"], rotated["is_nullable"]) == (
        "timestamp with time zone",
        "timestamptz",
        "YES",
    )
    assert rotated["column_default"] is None
    assert set(constraints) == {
        "ck_api_key_credential_kind",
        "ck_api_key_expires_after_creation",
        "ck_api_key_kind_binding",
        "ck_api_key_kind_scopes",
        "ck_api_key_scopes_array",
        "ck_api_key_secret_digest_length",
        "fk_api_key_profile",
        "fk_api_key_service",
        "pk_api_key",
        "uq_api_key_public_prefix",
        "uq_api_key_secret_digest",
        "uq_api_key_service_name",
    }
    for name in (
        "ck_api_key_credential_kind",
        "ck_api_key_kind_binding",
        "ck_api_key_kind_scopes",
    ):
        assert constraints[name]["contype"] == "c"
    credential_definition = constraints["ck_api_key_credential_kind"]["definition"]
    assert "service_ingestion" in credential_definition
    assert "profile_uptime" in credential_definition
    binding_definition = constraints["ck_api_key_kind_binding"]["definition"]
    assert "service_id IS NOT NULL OR revoked_at IS NOT NULL" in binding_definition
    assert "service_id IS NULL" in binding_definition
    assert "expires_at IS NULL" in binding_definition
    assert "revoked_at IS NULL" in binding_definition
    scopes_definition = constraints["ck_api_key_kind_scopes"]["definition"]
    assert "events:write" in scopes_definition
    assert "uptime:read" in scopes_definition
    assert set(indexes) == {
        "ix_api_key_profile",
        "ix_api_key_service_revoked",
        "pk_api_key",
        "uq_api_key_profile_uptime",
        "uq_api_key_public_prefix",
        "uq_api_key_secret_digest",
        "uq_api_key_service_name",
    }
    uptime_index = indexes["uq_api_key_profile_uptime"]["indexdef"]
    assert "UNIQUE INDEX" in uptime_index
    assert "USING btree (profile_id)" in uptime_index
    assert "credential_kind" in uptime_index
    assert "profile_uptime" in uptime_index


async def _assert_revision(connection: AsyncConnection, revision: str) -> None:
    assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == revision


@pytest_asyncio.fixture
async def profile_uptime_migration_database() -> AsyncIterator[ProfileUptimeMigrationDatabase]:
    source_url = make_url(os.environ["WATCHTOWER_DATABASE_URL"])
    database_name = f"wt_profile_uptime_{uuid4().hex[:20]}"
    admin_url = source_url.set(database="postgres").render_as_string(hide_password=False)
    database_url = source_url.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{database_name}"'))

    profile_id, service_id, bound_key_id, revoked_key_id = (uuid4() for _ in range(4))
    try:
        await _run_alembic(database_url, "upgrade", PARENT_REVISION)
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await _assert_revision(connection, PARENT_REVISION)
            _assert_parent_schema(*await _catalog(connection))
            await connection.execute(
                text(
                    "INSERT INTO watchtower.profile (id, auth_user_id, display_name) "
                    "VALUES (:id, :auth_user_id, 'migration fixture')"
                ),
                {"id": profile_id, "auth_user_id": uuid4()},
            )
            await connection.execute(
                text(
                    "INSERT INTO watchtower.monitored_service "
                    "(id, profile_id, slug, display_name, environment, active, secret_key_id) "
                    "VALUES (:id, :profile_id, 'migration-service', 'Migration service', "
                    "'test', true, 'managed')"
                ),
                {"id": service_id, "profile_id": profile_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO watchtower.api_key "
                    "(id, profile_id, service_id, name, public_prefix, secret_digest, scopes) "
                    "VALUES (:id, :profile_id, :service_id, 'bound fixture', 'bound-fixture', "
                    ":digest, CAST(:scopes AS jsonb))"
                ),
                {
                    "id": bound_key_id,
                    "profile_id": profile_id,
                    "service_id": service_id,
                    "digest": b"b" * 32,
                    "scopes": '["events:write"]',
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO watchtower.api_key "
                    "(id, profile_id, name, public_prefix, secret_digest, scopes, revoked_at) "
                    "VALUES (:id, :profile_id, 'revoked fixture', 'revoked-fixture', "
                    ":digest, CAST(:scopes AS jsonb), now())"
                ),
                {
                    "id": revoked_key_id,
                    "profile_id": profile_id,
                    "digest": b"r" * 32,
                    "scopes": '["events:write"]',
                },
            )
        await engine.dispose()
        await _run_alembic(database_url, "upgrade", PROFILE_UPTIME_REVISION)
        yield ProfileUptimeMigrationDatabase(
            database_url, profile_id, service_id, bound_key_id, revoked_key_id
        )
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


@pytest.mark.integration
async def test_0016_to_0017_backfills_service_keys_and_matches_exact_catalog(
    profile_uptime_migration_database: ProfileUptimeMigrationDatabase,
) -> None:
    fixture = profile_uptime_migration_database
    engine = create_async_engine(fixture.url)
    try:
        async with engine.connect() as connection:
            await _assert_revision(connection, PROFILE_UPTIME_REVISION)
            _assert_profile_uptime_schema(*await _catalog(connection))
            rows = (
                await connection.execute(
                    text(
                        "SELECT id, credential_kind, rotated_at FROM watchtower.api_key "
                        "WHERE id IN (:bound_id, :revoked_id) ORDER BY id"
                    ),
                    {"bound_id": fixture.bound_key_id, "revoked_id": fixture.revoked_key_id},
                )
            ).mappings()
            assert {
                (row["id"], row["credential_kind"], row["rotated_at"]) for row in rows
            } == {
                (fixture.bound_key_id, "service_ingestion", None),
                (fixture.revoked_key_id, "service_ingestion", None),
            }
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("kind", "service_binding", "scopes", "expires", "revoked"),
    [
        ("unknown", True, '["events:write"]', False, False),
        ("profile_uptime", True, '["uptime:read"]', False, False),
        ("profile_uptime", False, '["uptime:read"]', True, False),
        ("profile_uptime", False, '["uptime:read"]', False, True),
        ("profile_uptime", False, '["events:write"]', False, False),
        ("service_ingestion", True, '["uptime:read"]', False, False),
        ("service_ingestion", False, '["events:write"]', False, False),
    ],
)
async def test_0017_rejects_invalid_kind_binding_and_scope_combinations(
    profile_uptime_migration_database: ProfileUptimeMigrationDatabase,
    kind: str,
    service_binding: bool,
    scopes: str,
    expires: bool,
    revoked: bool,
) -> None:
    fixture = profile_uptime_migration_database
    engine = create_async_engine(fixture.url)
    try:
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO watchtower.api_key "
                        "(id, profile_id, service_id, name, credential_kind, public_prefix, "
                        "secret_digest, scopes, expires_at, revoked_at) VALUES "
                        "(:id, :profile_id, :service_id, 'invalid fixture', :kind, :prefix, "
                        ":digest, CAST(:scopes AS jsonb), "
                        "CASE WHEN :expires THEN now() + interval '1 day' END, "
                        "CASE WHEN :revoked THEN now() END)"
                    ),
                    {
                        "id": uuid4(),
                        "profile_id": fixture.profile_id,
                        "service_id": fixture.service_id if service_binding else None,
                        "kind": kind,
                        "prefix": uuid4().hex,
                        "digest": uuid4().bytes + uuid4().bytes,
                        "scopes": scopes,
                        "expires": expires,
                        "revoked": revoked,
                    },
                )
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_0017_guarded_downgrade_rolls_back_then_cleanly_downgrades_and_reupgrades(
    profile_uptime_migration_database: ProfileUptimeMigrationDatabase,
) -> None:
    fixture = profile_uptime_migration_database
    uptime_key_id = uuid4()
    engine = create_async_engine(fixture.url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO watchtower.api_key "
                "(id, profile_id, name, credential_kind, public_prefix, secret_digest, scopes) "
                "VALUES (:id, :profile_id, 'Profile uptime API', 'profile_uptime', :prefix, "
                ":digest, CAST(:scopes AS jsonb))"
            ),
            {
                "id": uptime_key_id,
                "profile_id": fixture.profile_id,
                "prefix": "uptime-guard-key",
                "digest": b"u" * 32,
                "scopes": '["uptime:read"]',
            },
        )
    await engine.dispose()

    output = await _run_alembic(
        fixture.url, "downgrade", PARENT_REVISION, succeeds=False
    )
    assert "Cannot downgrade while profile uptime API keys exist" in output

    engine = create_async_engine(fixture.url)
    async with engine.begin() as connection:
        await _assert_revision(connection, PROFILE_UPTIME_REVISION)
        _assert_profile_uptime_schema(*await _catalog(connection))
        assert await connection.scalar(
            text("SELECT count(*) FROM watchtower.api_key WHERE id = :id"),
            {"id": uptime_key_id},
        ) == 1
        await connection.execute(
            text("DELETE FROM watchtower.api_key WHERE id = :id"), {"id": uptime_key_id}
        )
    await engine.dispose()

    await _run_alembic(fixture.url, "downgrade", PARENT_REVISION)
    engine = create_async_engine(fixture.url)
    async with engine.connect() as connection:
        await _assert_revision(connection, PARENT_REVISION)
        _assert_parent_schema(*await _catalog(connection))
        assert await connection.scalar(
            text("SELECT count(*) FROM watchtower.api_key WHERE id IN (:bound_id, :revoked_id)"),
            {"bound_id": fixture.bound_key_id, "revoked_id": fixture.revoked_key_id},
        ) == 2
    await engine.dispose()

    await _run_alembic(fixture.url, "upgrade", PROFILE_UPTIME_REVISION)
    engine = create_async_engine(fixture.url)
    try:
        async with engine.connect() as connection:
            await _assert_revision(connection, PROFILE_UPTIME_REVISION)
            _assert_profile_uptime_schema(*await _catalog(connection))
            assert set(
                await connection.scalars(
                    text(
                        "SELECT credential_kind FROM watchtower.api_key "
                        "WHERE id IN (:bound_id, :revoked_id)"
                    ),
                    {"bound_id": fixture.bound_key_id, "revoked_id": fixture.revoked_key_id},
                )
            ) == {"service_ingestion"}
    finally:
        await engine.dispose()
