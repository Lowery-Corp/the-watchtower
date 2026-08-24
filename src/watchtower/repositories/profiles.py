"""Profile persistence operations."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.models.profile import Profile


async def get_or_create_profile(
    session: AsyncSession,
    *,
    auth_user_id: UUID,
    display_name: str | None,
) -> Profile:
    """Return one profile per auth user without committing the transaction."""

    statement = (
        insert(Profile)
        .values(auth_user_id=auth_user_id, display_name=display_name)
        .on_conflict_do_nothing(index_elements=[Profile.auth_user_id])
        .returning(Profile)
    )
    created = (await session.execute(statement)).scalar_one_or_none()
    if created is not None:
        return created

    existing = await session.scalar(select(Profile).where(Profile.auth_user_id == auth_user_id))
    if existing is None:
        raise RuntimeError("Profile provisioning did not produce a profile")
    return existing


async def get_profile_by_auth_user_id(
    session: AsyncSession,
    auth_user_id: UUID,
) -> Profile | None:
    """Return a Watchtower profile by external auth identity."""

    return (
        await session.scalars(select(Profile).where(Profile.auth_user_id == auth_user_id))
    ).one_or_none()
