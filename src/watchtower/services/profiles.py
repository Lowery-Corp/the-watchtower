"""Profile provisioning use case with an explicit transaction boundary."""

from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.models.profile import Profile
from watchtower.repositories.profiles import get_or_create_profile
from watchtower.schemas.auth import AuthenticatedUser


class ProfileAccessDeniedError(Exception):
    """The external identity has no active local Watchtower access."""


async def provision_profile_for_user(
    session: AsyncSession,
    user: AuthenticatedUser,
) -> Profile:
    """Provision one profile for a validated external identity atomically."""

    async with session.begin():
        profile = await get_or_create_profile(
            session,
            auth_user_id=user.id,
            display_name=user.username,
        )
    if profile.status != "active":
        raise ProfileAccessDeniedError
    return profile
