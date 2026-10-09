"""Transactional profile-key authentication and uptime read use case."""

from dataclasses import dataclass
from datetime import timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.core.api_keys import digest_profile_api_key, verify_profile_api_key
from watchtower.models.api_key import ApiKey
from watchtower.models.profile import Profile
from watchtower.repositories.api_keys import get_api_key_by_id, get_api_key_by_prefix
from watchtower.repositories.profile_uptime import list_profile_uptime
from watchtower.repositories.webhook_rate_limits import consume_webhook_rate_limit
from watchtower.schemas.profile_uptime import (
    ProfileUptimeIdentity,
    ProfileUptimeMonitor,
    ProfileUptimeResponse,
    ProfileUptimeService,
)

_DUMMY_PROFILE_KEY_DIGEST = digest_profile_api_key(
    "wtp_v1_aaaaaaaaaaaaaaaa.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
)


class ProfileUptimeAuthenticationError(ValueError):
    """The supplied profile key is not currently valid."""


class ProfileUptimeSuspendedError(PermissionError):
    """A valid profile key belongs to a suspended profile."""


@dataclass(frozen=True, slots=True)
class ProfileUptimeRateLimited:
    retry_after: int


async def _lock_profile(session: AsyncSession, profile_id: UUID) -> Profile | None:
    return cast(
        Profile | None,
        await session.scalar(
            select(Profile).where(Profile.id == profile_id).with_for_update()
        ),
    )


def _key_is_valid(api_key: ApiKey | None, token: str) -> bool:
    expected_digest = (
        api_key.secret_digest if api_key is not None else _DUMMY_PROFILE_KEY_DIGEST
    )
    verified = verify_profile_api_key(token, expected_digest)
    return bool(
        api_key is not None
        and verified
        and api_key.token_version == 1
        and api_key.credential_kind == "profile_uptime"
        and api_key.scopes == ["uptime:read"]
        and api_key.service_id is None
        and api_key.expires_at is None
        and api_key.revoked_at is None
    )


async def read_profile_uptime(
    session: AsyncSession,
    *,
    token: str,
    public_prefix: str,
    max_requests: int,
    window_seconds: int,
) -> ProfileUptimeResponse | ProfileUptimeRateLimited:
    """Authenticate, authorize, aggregate, and record use in one transaction.

    Reads and reissues both lock profile then key. The initial unlocked prefix read
    discovers the immutable profile ID only; all credential state is revalidated
    after both locks are held.
    """

    async with session.begin():
        candidate = await get_api_key_by_prefix(session, public_prefix=public_prefix)
        if not _key_is_valid(candidate, token):
            raise ProfileUptimeAuthenticationError("Invalid profile uptime authentication")
        assert candidate is not None

        profile = await _lock_profile(session, candidate.profile_id)
        locked_key = await get_api_key_by_id(session, api_key_id=candidate.id, for_update=True)
        if not _key_is_valid(locked_key, token):
            raise ProfileUptimeAuthenticationError("Invalid profile uptime authentication")
        assert locked_key is not None
        if profile is None or profile.id != locked_key.profile_id:
            raise ProfileUptimeAuthenticationError("Invalid profile uptime authentication")
        if profile.status != "active":
            raise ProfileUptimeSuspendedError("Profile is suspended")

        retry_after = await consume_webhook_rate_limit(
            session,
            identity=f"profile-uptime:{locked_key.id}",
            max_requests=max_requests,
            window_seconds=window_seconds,
        )
        if retry_after is not None:
            return ProfileUptimeRateLimited(retry_after=retry_after)

        generated_at = await session.scalar(select(func.statement_timestamp()))
        assert generated_at is not None
        views = await list_profile_uptime(
            session,
            profile_id=profile.id,
            window_start=generated_at - timedelta(hours=24),
            window_end=generated_at,
        )
        response = ProfileUptimeResponse(
            profile=ProfileUptimeIdentity(id=profile.id),
            generated_at=generated_at,
            services=[
                ProfileUptimeService(
                    id=view.service.id,
                    slug=view.service.slug,
                    display_name=view.service.display_name,
                    environment=view.service.environment,
                    active=view.service.active,
                    monitors=[
                        ProfileUptimeMonitor(
                            id=monitor_view.monitor.id,
                            url=monitor_view.monitor.url,
                            status=(
                                "pending"
                                if monitor_view.monitor.last_is_up is None
                                else "up"
                                if monitor_view.monitor.last_is_up
                                else "down"
                            ),
                            last_checked_at=monitor_view.monitor.last_checked_at,
                            status_code=monitor_view.monitor.last_status_code,
                            response_time_ms=monitor_view.monitor.last_response_time_ms,
                            uptime_24h_percent=monitor_view.uptime_24h_percent,
                        )
                        for monitor_view in view.monitors
                    ],
                )
                for view in views
            ],
        )
        locked_key.last_used_at = generated_at
        await session.flush()
        return response
