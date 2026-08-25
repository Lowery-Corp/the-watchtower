"""Migration coverage for application-scoped API keys."""

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


@dataclass(frozen=True)
class SeededMigrationDatabase:
    url: str
    owner_id: UUID
    creator_id: UUID
    service_id: UUID
    legacy_key_id: UUID


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


@pytest_asyncio.fixture
async def api_key_migration_database() -> AsyncIterator[SeededMigrationDatabase]:
    source_url = make_url(os.environ["WATCHTOWER_DATABASE_URL"])
    database_name = f"watchtower_api_key_slice_{uuid4().hex}"
    admin_url = source_url.set(database="postgres")
    database_url = source_url.set(database=database_name).render_as_string(hide_password=False)
    admin_engine = create_async_engine(
        admin_url.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT"
    )
    async with admin_engine.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{database_name}"'))

    owner_id, creator_id, service_id, legacy_key_id = (uuid4() for _ in range(4))
    try:
        await _run_alembic(database_url, "upgrade", "0014_watchtower_permissions")
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await _assert_pre_0015_schema(connection)
            for profile_id in (owner_id, creator_id):
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
                    "VALUES (:id, :profile_id, 'migration-source', 'Migration source', "
                    "'test', true, 'managed')"
                ),
                {"id": service_id, "profile_id": owner_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO watchtower.api_key "
                    "(id, profile_id, name, public_prefix, secret_digest, scopes, revoked_at) "
                    "VALUES (:id, :profile_id, 'legacy-revoked', 'legacy-prefix', "
                    ":digest, CAST('[\"events:write\"]' AS jsonb), now())"
                ),
                {"id": legacy_key_id, "profile_id": creator_id, "digest": b"l" * 32},
            )
        await engine.dispose()
        await _run_alembic(database_url, "upgrade", "head")
        yield SeededMigrationDatabase(database_url, owner_id, creator_id, service_id, legacy_key_id)
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


async def _api_key_catalog(
    connection: AsyncConnection,
) -> tuple[dict[str, RowMapping], dict[str, tuple[list[str], bool, bool, str | None]]]:
    constraint_rows = (
        (
            await connection.execute(
                text(
                    "SELECT c.conname, c.contype::text AS contype, "
                    "c.confdeltype::text AS confdeltype, "
                    "ARRAY(SELECT a.attname::text FROM unnest(c.conkey) WITH ORDINALITY "
                    "AS key(attnum, ordinal) JOIN pg_attribute AS a "
                    "ON a.attrelid = c.conrelid AND a.attnum = key.attnum "
                    "ORDER BY key.ordinal) AS local_columns, "
                    "ref_namespace.nspname::text AS referenced_schema, "
                    "ref_class.relname::text AS referenced_table, "
                    "ARRAY(SELECT a.attname::text FROM unnest(c.confkey) WITH ORDINALITY "
                    "AS key(attnum, ordinal) JOIN pg_attribute AS a "
                    "ON a.attrelid = c.confrelid AND a.attnum = key.attnum "
                    "ORDER BY key.ordinal) AS referenced_columns, "
                    "pg_get_expr(c.conbin, c.conrelid) AS check_expression "
                    "FROM pg_constraint AS c "
                    "LEFT JOIN pg_class AS ref_class ON ref_class.oid = c.confrelid "
                    "LEFT JOIN pg_namespace AS ref_namespace "
                    "ON ref_namespace.oid = ref_class.relnamespace "
                    "WHERE c.connamespace = 'watchtower'::regnamespace "
                    "AND c.conrelid = 'watchtower.api_key'::regclass"
                )
            )
        )
        .mappings()
        .all()
    )
    constraints: dict[str, RowMapping] = {row["conname"]: row for row in constraint_rows}
    index_rows = (
        (
            await connection.execute(
                text(
                    "SELECT index_class.relname AS index_name, idx.indisunique, idx.indisprimary, "
                    "ARRAY(SELECT attribute.attname::text FROM unnest(idx.indkey) WITH ORDINALITY "
                    "AS key(attnum, ordinal) JOIN pg_attribute AS attribute "
                    "ON attribute.attrelid = idx.indrelid AND attribute.attnum = key.attnum "
                    "ORDER BY key.ordinal) AS columns, "
                    "pg_get_expr(idx.indpred, idx.indrelid) AS predicate "
                    "FROM pg_index AS idx JOIN pg_class AS index_class "
                    "ON index_class.oid = idx.indexrelid "
                    "WHERE idx.indrelid = 'watchtower.api_key'::regclass"
                )
            )
        )
        .mappings()
        .all()
    )
    indexes: dict[str, tuple[list[str], bool, bool, str | None]] = {
        row["index_name"]: (
            list(row["columns"]),
            bool(row["indisunique"]),
            bool(row["indisprimary"]),
            row["predicate"],
        )
        for row in index_rows
    }
    return constraints, indexes


def _assert_fk(
    constraint: RowMapping,
    *,
    local_columns: list[str],
    referenced_table: str,
    referenced_columns: list[str],
) -> None:
    row = constraint
    assert row["contype"] == "f"
    assert row["local_columns"] == local_columns
    assert row["referenced_schema"] == "watchtower"
    assert row["referenced_table"] == referenced_table
    assert row["referenced_columns"] == referenced_columns
    assert row["confdeltype"] == "r"


def _normalize_check(expression: str) -> str:
    return "".join(character for character in expression if character not in " ()\n\t")


def _assert_retained_constraints(constraints: dict[str, RowMapping]) -> None:
    assert constraints["pk_api_key"]["contype"] == "p"
    assert constraints["pk_api_key"]["local_columns"] == ["id"]
    for name, columns in (
        ("uq_api_key_public_prefix", ["public_prefix"]),
        ("uq_api_key_secret_digest", ["secret_digest"]),
    ):
        assert constraints[name]["contype"] == "u"
        assert constraints[name]["local_columns"] == columns
    expected_checks = {
        "ck_api_key_secret_digest_length": "octet_lengthsecret_digest=32",
        "ck_api_key_scopes_array": "jsonb_typeofscopes='array'::text",
        "ck_api_key_expires_after_creation": "expires_atISNULLORexpires_at>created_at",
    }
    for name, expression in expected_checks.items():
        assert constraints[name]["contype"] == "c"
        assert _normalize_check(constraints[name]["check_expression"]) == expression


async def _assert_pre_0015_schema(connection: AsyncConnection) -> None:
    constraints, indexes = await _api_key_catalog(connection)
    assert set(constraints) == {
        "ck_api_key_expires_after_creation",
        "ck_api_key_scopes_array",
        "ck_api_key_secret_digest_length",
        "fk_api_key_profile",
        "fk_api_key_service_profile",
        "pk_api_key",
        "uq_api_key_profile_name",
        "uq_api_key_public_prefix",
        "uq_api_key_secret_digest",
    }
    _assert_retained_constraints(constraints)
    _assert_fk(
        constraints["fk_api_key_profile"],
        local_columns=["profile_id"],
        referenced_table="profile",
        referenced_columns=["id"],
    )
    _assert_fk(
        constraints["fk_api_key_service_profile"],
        local_columns=["service_id", "profile_id"],
        referenced_table="monitored_service",
        referenced_columns=["id", "profile_id"],
    )
    assert constraints["uq_api_key_profile_name"]["contype"] == "u"
    assert constraints["uq_api_key_profile_name"]["local_columns"] == [
        "profile_id",
        "name",
    ]
    assert indexes == {
        "ix_api_key_profile_revoked": (["profile_id", "revoked_at"], False, False, None),
        "pk_api_key": (["id"], True, True, None),
        "uq_api_key_profile_name": (["profile_id", "name"], True, False, None),
        "uq_api_key_public_prefix": (["public_prefix"], True, False, None),
        "uq_api_key_secret_digest": (["secret_digest"], True, False, None),
    }


async def _assert_post_0015_schema(connection: AsyncConnection) -> None:
    constraints, indexes = await _api_key_catalog(connection)
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
    _assert_retained_constraints(constraints)
    _assert_fk(
        constraints["fk_api_key_service"],
        local_columns=["service_id"],
        referenced_table="monitored_service",
        referenced_columns=["id"],
    )
    _assert_fk(
        constraints["fk_api_key_profile"],
        local_columns=["profile_id"],
        referenced_table="profile",
        referenced_columns=["id"],
    )
    assert constraints["uq_api_key_service_name"]["contype"] == "u"
    assert constraints["uq_api_key_service_name"]["local_columns"] == [
        "service_id",
        "name",
    ]
    service_or_revoked = constraints["ck_api_key_service_or_revoked"]
    assert service_or_revoked["contype"] == "c"
    normalized_check = _normalize_check(service_or_revoked["check_expression"])
    assert normalized_check == "service_idISNOTNULLORrevoked_atISNOTNULL"
    assert indexes == {
        "ix_api_key_profile": (["profile_id"], False, False, None),
        "ix_api_key_service_revoked": (["service_id", "revoked_at"], False, False, None),
        "pk_api_key": (["id"], True, True, None),
        "uq_api_key_public_prefix": (["public_prefix"], True, False, None),
        "uq_api_key_secret_digest": (["secret_digest"], True, False, None),
        "uq_api_key_service_name": (["service_id", "name"], True, False, None),
    }


@pytest.mark.integration
async def test_upgrade_preserves_revoked_unbound_and_enforces_new_shape(
    api_key_migration_database: SeededMigrationDatabase,
) -> None:
    fixture = api_key_migration_database
    engine = create_async_engine(fixture.url)
    try:
        async with engine.connect() as connection:
            legacy = (
                await connection.execute(
                    text("SELECT service_id, revoked_at FROM watchtower.api_key WHERE id = :id"),
                    {"id": fixture.legacy_key_id},
                )
            ).one()
            await _assert_post_0015_schema(connection)
        assert legacy.service_id is None
        assert legacy.revoked_at is not None

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO watchtower.api_key "
                    "(id, profile_id, service_id, name, public_prefix, secret_digest, scopes) "
                    "VALUES (:id, :profile_id, :service_id, 'shared', 'cross-prefix', "
                    ":digest, CAST('[\"events:write\"]' AS jsonb))"
                ),
                {
                    "id": uuid4(),
                    "profile_id": fixture.creator_id,
                    "service_id": fixture.service_id,
                    "digest": b"c" * 32,
                },
            )
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO watchtower.api_key "
                        "(id, profile_id, name, public_prefix, secret_digest, scopes) "
                        "VALUES (:id, :profile_id, 'active-unbound', 'active-prefix', "
                        ":digest, CAST('[\"events:write\"]' AS jsonb))"
                    ),
                    {
                        "id": uuid4(),
                        "profile_id": fixture.creator_id,
                        "digest": b"a" * 32,
                    },
                )
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_downgrade_rejects_cross_owner_then_reupgrades_without_losing_legacy(
    api_key_migration_database: SeededMigrationDatabase,
) -> None:
    fixture = api_key_migration_database
    cross_owner_id = uuid4()
    engine = create_async_engine(fixture.url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO watchtower.api_key "
                "(id, profile_id, service_id, name, public_prefix, secret_digest, scopes) "
                "VALUES (:id, :profile_id, :service_id, 'cross-owner', 'guard-prefix', "
                ":digest, CAST('[\"events:write\"]' AS jsonb))"
            ),
            {
                "id": cross_owner_id,
                "profile_id": fixture.creator_id,
                "service_id": fixture.service_id,
                "digest": b"g" * 32,
            },
        )
    await engine.dispose()

    output = await _run_alembic(
        fixture.url, "downgrade", "0014_watchtower_permissions", succeeds=False
    )
    assert "cross-owner API keys exist" in output

    engine = create_async_engine(fixture.url)
    async with engine.begin() as connection:
        await _assert_post_0015_schema(connection)
        await connection.execute(
            text("DELETE FROM watchtower.api_key WHERE id = :id"),
            {"id": cross_owner_id},
        )
    await engine.dispose()

    await _run_alembic(fixture.url, "downgrade", "0014_watchtower_permissions")
    await _run_alembic(fixture.url, "upgrade", "head")
    engine = create_async_engine(fixture.url)
    try:
        async with engine.connect() as connection:
            legacy_count = await connection.scalar(
                text("SELECT count(*) FROM watchtower.api_key WHERE id = :id"),
                {"id": fixture.legacy_key_id},
            )
            await _assert_post_0015_schema(connection)
        assert legacy_count == 1
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_downgrade_rejects_duplicate_creator_key_names(
    api_key_migration_database: SeededMigrationDatabase,
) -> None:
    fixture = api_key_migration_database
    second_service_id, first_key_id, second_key_id = (uuid4() for _ in range(3))
    engine = create_async_engine(fixture.url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO watchtower.monitored_service "
                "(id, profile_id, slug, display_name, environment, active, secret_key_id) "
                "VALUES (:id, :profile_id, 'downgrade-second', 'Downgrade second', "
                "'test', true, 'managed')"
            ),
            {"id": second_service_id, "profile_id": fixture.owner_id},
        )
        for key_id, service_id, prefix, digest in (
            (first_key_id, fixture.service_id, "duplicate-first", b"1" * 32),
            (second_key_id, second_service_id, "duplicate-second", b"2" * 32),
        ):
            await connection.execute(
                text(
                    "INSERT INTO watchtower.api_key "
                    "(id, profile_id, service_id, name, public_prefix, secret_digest, scopes) "
                    "VALUES (:id, :profile_id, :service_id, 'duplicate-on-downgrade', "
                    ":prefix, :digest, CAST('[\"events:write\"]' AS jsonb))"
                ),
                {
                    "id": key_id,
                    "profile_id": fixture.owner_id,
                    "service_id": service_id,
                    "prefix": prefix,
                    "digest": digest,
                },
            )
    await engine.dispose()

    output = await _run_alembic(
        fixture.url, "downgrade", "0014_watchtower_permissions", succeeds=False
    )
    assert "duplicate creator key names exist" in output

    engine = create_async_engine(fixture.url)
    async with engine.begin() as connection:
        await _assert_post_0015_schema(connection)
        await connection.execute(
            text("DELETE FROM watchtower.api_key WHERE id IN (:first_id, :second_id)"),
            {"first_id": first_key_id, "second_id": second_key_id},
        )
        await connection.execute(
            text("DELETE FROM watchtower.monitored_service WHERE id = :id"),
            {"id": second_service_id},
        )
    await engine.dispose()

    await _run_alembic(fixture.url, "downgrade", "0014_watchtower_permissions")
    await _run_alembic(fixture.url, "upgrade", "head")
    engine = create_async_engine(fixture.url)
    try:
        async with engine.connect() as connection:
            await _assert_post_0015_schema(connection)
    finally:
        await engine.dispose()
