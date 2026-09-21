"""Atomic PostgreSQL persistence for shared webhook request budgets."""

from typing import cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_STALE_ROW_RETENTION_SECONDS = 86_400
_STALE_ROW_PRUNE_BATCH = 100

_ACQUIRE_IDENTITY_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))")

_CONSUME_RATE_LIMIT = text(
    """
    WITH consumed AS (
        INSERT INTO watchtower.webhook_rate_limit (
            identity,
            window_started_at,
            request_count
        )
        VALUES (:identity, statement_timestamp(), 1)
        ON CONFLICT (identity) DO UPDATE
        SET
            window_started_at = CASE
                WHEN watchtower.webhook_rate_limit.window_started_at
                    + make_interval(secs => CAST(:window_seconds AS integer))
                    <= statement_timestamp()
                THEN statement_timestamp()
                ELSE watchtower.webhook_rate_limit.window_started_at
            END,
            request_count = CASE
                WHEN watchtower.webhook_rate_limit.window_started_at
                    + make_interval(secs => CAST(:window_seconds AS integer))
                    <= statement_timestamp()
                THEN 1
                ELSE LEAST(
                    watchtower.webhook_rate_limit.request_count + 1,
                    CAST(:max_requests AS integer) + 1
                )
            END
        RETURNING request_count, window_started_at
    )
    SELECT CASE
        WHEN request_count <= CAST(:max_requests AS integer) THEN NULL
        ELSE GREATEST(
            1,
            CEIL(
                EXTRACT(
                    EPOCH FROM (
                        window_started_at
                        + make_interval(secs => CAST(:window_seconds AS integer))
                        - statement_timestamp()
                    )
                )
            )::integer
        )
    END AS retry_after
    FROM consumed
    """
)

_PRUNE_STALE_RATE_LIMITS = text(
    """
    WITH candidates AS MATERIALIZED (
        SELECT identity
        FROM watchtower.webhook_rate_limit
        WHERE window_started_at
            < statement_timestamp()
                - make_interval(secs => CAST(:retention_seconds AS integer))
        ORDER BY window_started_at
        LIMIT :prune_batch
    ),
    locked AS MATERIALIZED (
        SELECT identity
        FROM candidates
        WHERE pg_try_advisory_xact_lock(hashtextextended(identity, 0))
    )
    DELETE FROM watchtower.webhook_rate_limit AS rate_limit
    USING locked
    WHERE rate_limit.identity = locked.identity
      AND rate_limit.window_started_at
          < statement_timestamp()
              - make_interval(secs => CAST(:retention_seconds AS integer))
    """
)


async def consume_webhook_rate_limit(
    session: AsyncSession,
    *,
    identity: str,
    max_requests: int,
    window_seconds: int,
) -> int | None:
    """Atomically consume one shared fixed-window request slot without committing."""

    # Serialize one identity before sampling statement_timestamp(). PostgreSQL's
    # statement timestamp is fixed at statement start, so relying on the UPSERT's
    # row-conflict wait alone can carry a pre-wait timestamp across a window edge.
    await session.execute(_ACQUIRE_IDENTITY_LOCK, {"identity": identity})
    retry_after = await session.scalar(
        _CONSUME_RATE_LIMIT,
        {
            "identity": identity,
            "max_requests": max_requests,
            "window_seconds": window_seconds,
        },
    )
    await session.execute(
        _PRUNE_STALE_RATE_LIMITS,
        {
            "retention_seconds": max(
                _STALE_ROW_RETENTION_SECONDS,
                window_seconds * 2,
            ),
            "prune_batch": _STALE_ROW_PRUNE_BATCH,
        },
    )
    return cast(int | None, retry_after)
