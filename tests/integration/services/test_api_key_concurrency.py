"""Deterministic PostgreSQL concurrency coverage for application API keys."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from pytest import MonkeyPatch
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from watchtower.db.session import create_async_database_engine, create_session_factory
from watchtower.models.api_key import ApiKey
from watchtower.models.event import Event
from watchtower.models.monitored_service import MonitoredService
from watchtower.models.outbox_message import OutboxMessage
from watchtower.models.profile import Profile
from watchtower.models.profile_role import ProfileRole
from watchtower.models.role import APP_ADMIN_ROLE_ID
from watchtower.schemas.api_key import ApiKeyCreate, ApiKeyUpdate
from watchtower.schemas.event import EventEnvelope
from watchtower.services import api_keys as api_key_service
from watchtower.services import application_memberships as membership_service
from watchtower.services import event_ingestion as ingestion_service
from watchtower.services.api_keys import ApplicationAccessDeniedError
from watchtower.services.event_ingestion import ManagedKeyAuthenticationError

DATABASE_URL = os.environ.get(
    "WATCHTOWER_DATABASE_URL",
    "postgresql+asyncpg://watchtower:watchtower@db:5432/watchtower_test",
)


@dataclass(frozen=True, slots=True)
class ApplicationFixture:
    owner_id: UUID
    actor_id: UUID
    service_id: UUID
    slug: str


@asynccontextmanager
async def application_fixture(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[ApplicationFixture]:
    owner = Profile(id=uuid4(), auth_user_id=uuid4(), display_name="Concurrency owner")
    actor = Profile(id=uuid4(), auth_user_id=uuid4(), display_name="Concurrency actor")
    service = MonitoredService(
        profile_id=owner.id,
        slug=f"key-race-{uuid4().hex}",
        display_name="API key race",
        environment="test",
        secret_key_id="managed",
    )
    async with factory() as session:
        async with session.begin():
            session.add_all([owner, actor])
            await session.flush()
            session.add(service)
            await session.flush()
            session.add_all(
                [
                    ProfileRole(
                        profile_id=profile_id,
                        role_id=APP_ADMIN_ROLE_ID,
                        role_scope_kind="application",
                        application_id=service.id,
                        granted_by_profile_id=owner.id,
                    )
                    for profile_id in (owner.id, actor.id)
                ]
            )

    fixture = ApplicationFixture(owner.id, actor.id, service.id, service.slug)
    try:
        yield fixture
    finally:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    delete(OutboxMessage).where(OutboxMessage.service_id == fixture.service_id)
                )
                await session.execute(delete(Event).where(Event.service_id == fixture.service_id))
                await session.execute(delete(ApiKey).where(ApiKey.service_id == fixture.service_id))
                await session.execute(
                    delete(ProfileRole).where(ProfileRole.application_id == fixture.service_id)
                )
                await session.execute(
                    delete(MonitoredService).where(MonitoredService.id == fixture.service_id)
                )
                await session.execute(
                    delete(Profile).where(Profile.id.in_([fixture.owner_id, fixture.actor_id]))
                )


async def issue_fixture_key(
    factory: async_sessionmaker[AsyncSession], fixture: ApplicationFixture, *, name: str
) -> tuple[UUID, SecretStr]:
    async with factory() as session:
        api_key, token = await api_key_service.issue_api_key(
            session,
            profile_id=fixture.actor_id,
            payload=ApiKeyCreate(name=name, service_id=fixture.service_id),
        )
    return api_key.id, token


Mutation = Literal["create", "update", "revoke"]


@pytest.mark.integration
@pytest.mark.parametrize("mutation", ["create", "update", "revoke"])
async def test_membership_removal_wins_before_api_key_mutation_authorization(
    monkeypatch: MonkeyPatch, mutation: Mutation
) -> None:
    """The shared application row lock makes removal-before-authorization decisive."""

    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    removal_holds_application_lock = asyncio.Event()
    allow_removal_to_commit = asyncio.Event()
    mutation_reached_application_lock = asyncio.Event()

    try:
        async with application_fixture(factory) as fixture:
            existing_key_id: UUID | None = None
            if mutation != "create":
                existing_key_id, _ = await issue_fixture_key(
                    factory, fixture, name=f"before-{mutation}"
                )

            original_require_manager = membership_service._require_membership_manager
            original_lock_application = api_key_service._lock_application

            async def pause_removal_after_lock(
                session: AsyncSession, *, profile_id: UUID, application_id: UUID
            ) -> None:
                await original_require_manager(
                    session,
                    profile_id=profile_id,
                    application_id=application_id,
                )
                removal_holds_application_lock.set()
                await allow_removal_to_commit.wait()

            async def observe_mutation_lock(
                session: AsyncSession, *, application_id: UUID
            ) -> MonitoredService | None:
                mutation_reached_application_lock.set()
                return await original_lock_application(session, application_id=application_id)

            monkeypatch.setattr(
                membership_service, "_require_membership_manager", pause_removal_after_lock
            )
            monkeypatch.setattr(api_key_service, "_lock_application", observe_mutation_lock)

            async def remove_actor() -> None:
                async with factory() as session:
                    await membership_service.remove_application_membership(
                        session,
                        actor_profile_id=fixture.owner_id,
                        application_id=fixture.service_id,
                        target_profile_id=fixture.actor_id,
                    )

            async def mutate_key() -> ApplicationAccessDeniedError | None:
                try:
                    async with factory() as session:
                        if mutation == "create":
                            await api_key_service.issue_api_key(
                                session,
                                profile_id=fixture.actor_id,
                                payload=ApiKeyCreate(
                                    name="removed-actor-create",
                                    service_id=fixture.service_id,
                                ),
                            )
                        elif mutation == "update":
                            assert existing_key_id is not None
                            await api_key_service.update_profile_api_key(
                                session,
                                profile_id=fixture.actor_id,
                                api_key_id=existing_key_id,
                                payload=ApiKeyUpdate(name="removed-actor-update"),
                            )
                        else:
                            assert existing_key_id is not None
                            await api_key_service.revoke_api_key(
                                session,
                                profile_id=fixture.actor_id,
                                api_key_id=existing_key_id,
                            )
                except ApplicationAccessDeniedError as exc:
                    return exc
                return None

            removal_task = asyncio.create_task(remove_actor())
            await removal_holds_application_lock.wait()
            mutation_task = asyncio.create_task(mutate_key())
            await mutation_reached_application_lock.wait()
            allow_removal_to_commit.set()
            await removal_task
            denial = await mutation_task

            assert isinstance(denial, ApplicationAccessDeniedError)
            assert str(denial) == "Application access denied"
            async with factory() as session:
                key_count = await session.scalar(
                    select(func.count())
                    .select_from(ApiKey)
                    .where(ApiKey.service_id == fixture.service_id)
                )
                persisted = (
                    await session.get(ApiKey, existing_key_id)
                    if existing_key_id is not None
                    else None
                )
            assert key_count == (0 if mutation == "create" else 1)
            if mutation == "update":
                assert persisted is not None
                assert persisted.name == "before-update"
            if mutation == "revoke":
                assert persisted is not None
                assert persisted.revoked_at is None
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_revocation_winning_key_lock_rejects_waiting_ingestion(
    monkeypatch: MonkeyPatch,
) -> None:
    """No event can commit after revocation owns and commits the key-row lock first."""

    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    revocation_holds_key_lock = asyncio.Event()
    allow_revocation_to_commit = asyncio.Event()
    ingestion_reached_application_lock = asyncio.Event()

    try:
        async with application_fixture(factory) as fixture:
            key_id, token = await issue_fixture_key(factory, fixture, name="revoke-wins")
            original_require_permission = api_key_service._require_permission
            original_get_service = ingestion_service.__dict__["get_monitored_service_by_slug"]

            async def pause_revocation_after_key_lock(
                session: AsyncSession,
                *,
                profile_id: UUID,
                application_id: UUID,
                permission_name: str,
            ) -> None:
                await original_require_permission(
                    session,
                    profile_id=profile_id,
                    application_id=application_id,
                    permission_name=permission_name,
                )
                revocation_holds_key_lock.set()
                await allow_revocation_to_commit.wait()

            async def observe_ingestion_application_lock(
                session: AsyncSession,
                *,
                profile_id: UUID,
                slug: str,
                for_update: bool = False,
            ) -> MonitoredService | None:
                if for_update:
                    ingestion_reached_application_lock.set()
                service: MonitoredService | None = await original_get_service(
                    session,
                    profile_id=profile_id,
                    slug=slug,
                    for_update=for_update,
                )
                return service

            monkeypatch.setattr(
                api_key_service, "_require_permission", pause_revocation_after_key_lock
            )
            monkeypatch.setattr(
                ingestion_service,
                "get_monitored_service_by_slug",
                observe_ingestion_application_lock,
            )

            async def revoke() -> None:
                async with factory() as session:
                    await api_key_service.revoke_api_key(
                        session, profile_id=fixture.actor_id, api_key_id=key_id
                    )

            async def ingest() -> ManagedKeyAuthenticationError | None:
                try:
                    async with factory() as session:
                        await ingestion_service.ingest_event(
                            session,
                            profile_id=fixture.owner_id,
                            authenticated_source=fixture.slug,
                            envelope=EventEnvelope.model_validate(
                                {
                                    "spec_version": "1.0",
                                    "event_id": str(uuid4()),
                                    "event_type": "service.heartbeat",
                                    "source": fixture.slug,
                                    "occurred_at": "2026-08-25T00:00:00Z",
                                    "severity": "info",
                                    "environment": "test",
                                    "data": {"status": "healthy"},
                                }
                            ),
                            request_id="revocation-wins",
                            api_key_id=key_id,
                            api_key_token=token,
                        )
                except ManagedKeyAuthenticationError as exc:
                    return exc
                return None

            revoke_task = asyncio.create_task(revoke())
            await revocation_holds_key_lock.wait()
            ingestion_task = asyncio.create_task(ingest())
            await ingestion_reached_application_lock.wait()
            allow_revocation_to_commit.set()
            await revoke_task
            denial = await ingestion_task

            assert isinstance(denial, ManagedKeyAuthenticationError)
            assert str(denial) == "Managed key is no longer valid"
            async with factory() as session:
                event_count = await session.scalar(
                    select(func.count())
                    .select_from(Event)
                    .where(Event.service_id == fixture.service_id)
                )
            assert event_count == 0
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_ingestion_winning_application_lock_commits_before_waiting_revocation(
    monkeypatch: MonkeyPatch,
) -> None:
    """An accepted event linearizes before revocation waiting on its application lock."""

    engine = create_async_database_engine(DATABASE_URL)
    factory = create_session_factory(DATABASE_URL, engine=engine)
    ingestion_holds_application_lock = asyncio.Event()
    allow_ingestion_to_commit = asyncio.Event()
    revocation_reached_application_lock = asyncio.Event()

    try:
        async with application_fixture(factory) as fixture:
            key_id, token = await issue_fixture_key(factory, fixture, name="ingestion-wins")
            original_get_service = ingestion_service.__dict__["get_monitored_service_by_slug"]
            original_lock_application = api_key_service._lock_application

            async def pause_ingestion_after_application_lock(
                session: AsyncSession,
                *,
                profile_id: UUID,
                slug: str,
                for_update: bool = False,
            ) -> MonitoredService | None:
                service: MonitoredService | None = await original_get_service(
                    session,
                    profile_id=profile_id,
                    slug=slug,
                    for_update=for_update,
                )
                if for_update:
                    ingestion_holds_application_lock.set()
                    await allow_ingestion_to_commit.wait()
                return service

            async def observe_revocation_application_lock(
                session: AsyncSession, *, application_id: UUID
            ) -> MonitoredService | None:
                revocation_reached_application_lock.set()
                return await original_lock_application(session, application_id=application_id)

            monkeypatch.setattr(
                ingestion_service,
                "get_monitored_service_by_slug",
                pause_ingestion_after_application_lock,
            )
            monkeypatch.setattr(
                api_key_service, "_lock_application", observe_revocation_application_lock
            )

            async def ingest() -> ingestion_service.IngestionOutcome:
                async with factory() as session:
                    return await ingestion_service.ingest_event(
                        session,
                        profile_id=fixture.owner_id,
                        authenticated_source=fixture.slug,
                        envelope=EventEnvelope.model_validate(
                            {
                                "spec_version": "1.0",
                                "event_id": str(uuid4()),
                                "event_type": "service.heartbeat",
                                "source": fixture.slug,
                                "occurred_at": "2026-08-25T00:00:00Z",
                                "severity": "info",
                                "environment": "test",
                                "data": {"status": "healthy"},
                            }
                        ),
                        request_id="ingestion-wins",
                        api_key_id=key_id,
                        api_key_token=token,
                    )

            async def revoke() -> None:
                async with factory() as session:
                    await api_key_service.revoke_api_key(
                        session, profile_id=fixture.actor_id, api_key_id=key_id
                    )

            ingestion_task = asyncio.create_task(ingest())
            await ingestion_holds_application_lock.wait()
            revocation_task = asyncio.create_task(revoke())
            await revocation_reached_application_lock.wait()
            allow_ingestion_to_commit.set()
            outcome = await ingestion_task
            await revocation_task

            assert outcome.status == "accepted"
            async with factory() as session:
                persisted_key = await session.get(ApiKey, key_id)
                persisted_event = await session.get(Event, outcome.event_id)
            assert persisted_key is not None
            assert persisted_key.revoked_at is not None
            assert persisted_event is not None
    finally:
        await engine.dispose()
