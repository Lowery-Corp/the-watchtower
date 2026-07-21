"""Authenticated profile-owned API-key management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from watchtower.api.v1.dependencies.csrf import require_browser_origin
from watchtower.api.v1.dependencies.user_auth import CurrentProfile, get_current_profile
from watchtower.db.dependencies import get_db_session
from watchtower.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyRead, ApiKeyUpdate
from watchtower.services.api_keys import (
    ApiKeyConflictError,
    ApiKeyNotFoundError,
    get_profile_api_key,
    issue_api_key,
    list_profile_api_keys,
    revoke_api_key,
    update_profile_api_key,
)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


def _not_found(exc: ApiKeyNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")


@router.post(
    "",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_browser_origin)],
    responses={409: {"description": "Key name conflict"}},
)
async def create_owned_api_key(
    payload: ApiKeyCreate,
    response: Response,
    current: Annotated[CurrentProfile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiKeyCreated:
    """Create and display a profile-owned machine key exactly once."""

    try:
        api_key, token = await issue_api_key(
            session, profile_id=current.profile.id, payload=payload
        )
    except ApiKeyNotFoundError as exc:
        raise _not_found(exc) from exc
    except ApiKeyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="API key name already exists",
        ) from exc
    metadata = ApiKeyRead.model_validate(api_key)
    response.headers["Cache-Control"] = "no-store"
    return ApiKeyCreated(
        **metadata.model_dump(),
        api_key=token.get_secret_value(),
    )


@router.get("", response_model=list[ApiKeyRead])
async def list_owned_api_keys(
    current: Annotated[CurrentProfile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[ApiKeyRead]:
    """List safe metadata for the current profile's keys."""

    keys = await list_profile_api_keys(session, profile_id=current.profile.id)
    return [ApiKeyRead.model_validate(api_key) for api_key in keys]


@router.get("/{api_key_id}", response_model=ApiKeyRead)
async def get_owned_api_key(
    api_key_id: UUID,
    current: Annotated[CurrentProfile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiKeyRead:
    """Read one key's metadata without exposing the verifier."""

    try:
        api_key = await get_profile_api_key(
            session, profile_id=current.profile.id, api_key_id=api_key_id
        )
    except ApiKeyNotFoundError as exc:
        raise _not_found(exc) from exc
    return ApiKeyRead.model_validate(api_key)


@router.patch(
    "/{api_key_id}",
    response_model=ApiKeyRead,
    dependencies=[Depends(require_browser_origin)],
)
async def update_owned_api_key(
    api_key_id: UUID,
    payload: ApiKeyUpdate,
    current: Annotated[CurrentProfile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiKeyRead:
    """Update key metadata without exposing or rotating its secret."""

    try:
        api_key = await update_profile_api_key(
            session,
            profile_id=current.profile.id,
            api_key_id=api_key_id,
            payload=payload,
        )
    except ApiKeyNotFoundError as exc:
        raise _not_found(exc) from exc
    except ApiKeyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="API key update conflicts with existing restrictions",
        ) from exc
    return ApiKeyRead.model_validate(api_key)


@router.delete(
    "/{api_key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_browser_origin)],
)
async def delete_owned_api_key(
    api_key_id: UUID,
    current: Annotated[CurrentProfile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """Soft-revoke one key owned by the current profile."""

    try:
        await revoke_api_key(
            session, profile_id=current.profile.id, api_key_id=api_key_id
        )
    except ApiKeyNotFoundError as exc:
        raise _not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
