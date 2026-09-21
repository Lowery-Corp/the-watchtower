"""PostgreSQL integration coverage for normalized role permissions."""

import asyncio
import os
from collections.abc import AsyncIterator
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from watchtower.db.session import create_async_database_engine, create_session_factory
from watchtower.models.permission import PERMISSION_IDS, Permission
from watchtower.models.role import VIEWER_ROLE_ID, Role
from watchtower.models.role_permission import RolePermission

DATABASE_URL = os.environ["WATCHTOWER_DATABASE_URL"]
EXPECTED_NAMES = {
    "profiles.read",
    "profiles.manage",
    "applications.read",
    "applications.manage",
    "memberships.manage",
    "api_keys.read",
    "api_keys.manage",
    "events.read",
}
EXPECTED_MATRIX = {
    "watchtower_admin": EXPECTED_NAMES,
    "app_admin": {
        "applications.read",
        "applications.manage",
        "memberships.manage",
        "api_keys.read",
        "api_keys.manage",
        "events.read",
    },
    "viewer": {"applications.read", "events.read"},
}


async def _run_alembic(database_url: str, *arguments: str, succeeds: bool = True) -> str:
    environment = {**os.environ, "WATCHTOWER_DATABASE_URL": database_url}
    process = await asyncio.create_subprocess_exec(
        "alembic",
        *arguments,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    rendered = output.decode()
    if succeeds:
        assert process.returncode == 0, rendered
    else:
        assert process.returncode != 0, rendered
    return rendered


@pytest_asyncio.fixture(scope="module")
async def permission_database_url() -> AsyncIterator[str]:
    """Migrate a unique database on the disposable PostgreSQL instance."""

    source_url = make_url(DATABASE_URL)
    database_name = f"watchtower_permissions_{uuid4().hex}"
    admin_url = source_url.set(database="postgres")
    permission_url = source_url.set(database=database_name)
    admin_engine = create_async_engine(
        admin_url.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT"
    )
    async with admin_engine.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{database_name}"'))

    rendered_url = permission_url.render_as_string(hide_password=False)
    try:
        await _run_alembic(rendered_url, "upgrade", "0013_watchtower_roles")
        await _run_alembic(rendered_url, "upgrade", "head")
        yield rendered_url
    finally:
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        await admin_engine.dispose()


@pytest.mark.integration
async def test_exact_permissions_and_grant_matrix_are_seeded(
    permission_database_url: str,
) -> None:
    engine = create_async_database_engine(permission_database_url)
    factory = create_session_factory(permission_database_url, engine=engine)
    try:
        async with factory() as session:
            permissions: dict[str, UUID] = {
                name: permission_id
                for name, permission_id in (
                    await session.execute(select(Permission.name, Permission.id))
                ).tuples()
            }
            rows = (
                await session.execute(
                    select(Role.name, Permission.name)
                    .join(RolePermission, RolePermission.role_id == Role.id)
                    .join(Permission, Permission.id == RolePermission.permission_id)
                )
            ).all()
        matrix: dict[str, set[str]] = {role_name: set() for role_name in EXPECTED_MATRIX}
        for role_name, permission_name in rows:
            matrix[role_name].add(permission_name)
        assert permissions == PERMISSION_IDS
        assert set(permissions) == EXPECTED_NAMES
        assert matrix == EXPECTED_MATRIX
        assert all("ingest" not in name and "machine" not in name for name in permissions)
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_seed_ids_are_uuid5_deterministic(permission_database_url: str) -> None:
    engine = create_async_database_engine(permission_database_url)
    factory = create_session_factory(permission_database_url, engine=engine)
    try:
        async with factory() as session:
            permissions: dict[str, UUID] = {
                name: permission_id
                for name, permission_id in (
                    await session.execute(select(Permission.name, Permission.id))
                ).tuples()
            }
            grants = (
                await session.execute(
                    select(RolePermission.id, RolePermission.role_id, RolePermission.permission_id)
                )
            ).all()
        assert permissions == {
            name: uuid5(NAMESPACE_URL, f"https://watchtower.local/permissions/{name}")
            for name in EXPECTED_NAMES
        }
        assert {grant_id for grant_id, _, _ in grants} == {
            uuid5(
                NAMESPACE_URL,
                f"https://watchtower.local/role-permissions/{role_id}/{permission_id}",
            )
            for _, role_id, permission_id in grants
        }
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_permission_names_ids_and_role_grants_are_unique_and_null_free(
    permission_database_url: str,
) -> None:
    engine = create_async_database_engine(permission_database_url)
    factory = create_session_factory(permission_database_url, engine=engine)
    duplicate_id = PERMISSION_IDS["profiles.read"]
    try:
        for statement, parameters in (
            (
                text("INSERT INTO watchtower.permission (id, name) VALUES (:id, 'events.read')"),
                {"id": uuid4()},
            ),
            (
                text(
                    """INSERT INTO watchtower.permission (id, name)
                    VALUES (:id, 'profiles.manage')"""
                ),
                {"id": duplicate_id},
            ),
            (
                text(
                    "INSERT INTO watchtower.role_permission (id, role_id, permission_id) "
                    "VALUES (:id, :role_id, :permission_id)"
                ),
                {
                    "id": uuid4(),
                    "role_id": VIEWER_ROLE_ID,
                    "permission_id": PERMISSION_IDS["events.read"],
                },
            ),
            (
                text(
                    "INSERT INTO watchtower.role_permission (id, role_id, permission_id) "
                    "VALUES (:id, NULL, :permission_id)"
                ),
                {"id": uuid4(), "permission_id": PERMISSION_IDS["events.read"]},
            ),
            (
                text(
                    "INSERT INTO watchtower.role_permission (id, role_id, permission_id) "
                    "VALUES (:id, :role_id, NULL)"
                ),
                {"id": uuid4(), "role_id": VIEWER_ROLE_ID},
            ),
        ):
            async with factory() as session:
                with pytest.raises(IntegrityError):
                    async with session.begin():
                        await session.execute(statement, parameters)
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_database_rejects_arbitrary_permission_names(
    permission_database_url: str,
) -> None:
    engine = create_async_database_engine(permission_database_url)
    factory = create_session_factory(permission_database_url, engine=engine)
    try:
        async with factory() as session:
            with pytest.raises(IntegrityError):
                async with session.begin():
                    session.add(Permission(id=uuid4(), name="events.ingest"))
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_role_permission_foreign_keys_and_seed_deletes_are_restrictive(
    permission_database_url: str,
) -> None:
    engine = create_async_database_engine(permission_database_url)
    factory = create_session_factory(permission_database_url, engine=engine)
    try:
        for assignment in (
            RolePermission(role_id=uuid4(), permission_id=PERMISSION_IDS["events.read"]),
            RolePermission(role_id=VIEWER_ROLE_ID, permission_id=uuid4()),
        ):
            async with factory() as session:
                with pytest.raises(IntegrityError):
                    async with session.begin():
                        session.add(assignment)
        for statement in (
            delete(Role).where(Role.id == VIEWER_ROLE_ID),
            delete(Permission).where(Permission.id == PERMISSION_IDS["events.read"]),
        ):
            async with factory() as session:
                with pytest.raises(IntegrityError):
                    async with session.begin():
                        await session.execute(statement)
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_lookup_indexes_begin_with_each_foreign_key(
    permission_database_url: str,
) -> None:
    engine = create_async_database_engine(permission_database_url)
    try:
        async with engine.connect() as connection:
            index_columns = {
                name: tuple(columns)
                for name, columns in (
                    await connection.execute(
                        text(
                            "SELECT index_class.relname, "
                            "array_agg(attribute.attname ORDER BY key.ordinality) "
                            "FROM pg_index AS idx "
                            "JOIN pg_class AS table_class ON table_class.oid = idx.indrelid "
                            "JOIN pg_namespace AS namespace "
                            "ON namespace.oid = table_class.relnamespace "
                            "JOIN pg_class AS index_class ON index_class.oid = idx.indexrelid "
                            "JOIN unnest(idx.indkey) WITH ORDINALITY "
                            "AS key(attnum, ordinality) ON true "
                            "JOIN pg_attribute AS attribute "
                            "ON attribute.attrelid = table_class.oid "
                            "AND attribute.attnum = key.attnum "
                            "WHERE namespace.nspname = 'watchtower' "
                            "AND table_class.relname = 'role_permission' "
                            "GROUP BY index_class.relname"
                        )
                    )
                ).all()
            }
        assert index_columns["uq_role_permission_role_permission"][0] == "role_id"
        assert index_columns["ix_role_permission_permission_role"][0] == "permission_id"
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_downgrade_reupgrade_is_stable_and_isolated(permission_database_url: str) -> None:
    engine = create_async_database_engine(permission_database_url)
    factory = create_session_factory(permission_database_url, engine=engine)
    try:
        async with factory() as session:
            before: dict[str, UUID] = {
                name: permission_id
                for name, permission_id in (
                    await session.execute(select(Permission.name, Permission.id))
                ).tuples()
            }
    finally:
        await engine.dispose()

    await _run_alembic(permission_database_url, "downgrade", "0013_watchtower_roles")
    engine = create_async_database_engine(permission_database_url)
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
        assert {"role", "profile_role", "profile", "api_key", "event"} <= tables
        assert "permission" not in tables
        assert "role_permission" not in tables
    finally:
        await engine.dispose()

    await _run_alembic(permission_database_url, "upgrade", "head")
    engine = create_async_database_engine(permission_database_url)
    factory = create_session_factory(permission_database_url, engine=engine)
    try:
        async with factory() as session:
            after: dict[str, UUID] = {
                name: permission_id
                for name, permission_id in (
                    await session.execute(select(Permission.name, Permission.id))
                ).tuples()
            }
            grant_count = len((await session.scalars(select(RolePermission.id))).all())
        assert after == before
        assert grant_count == 16
    finally:
        await engine.dispose()
