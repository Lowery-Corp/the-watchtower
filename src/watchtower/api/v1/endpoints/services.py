"""Authenticated profile-scoped monitored-service management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from watchtower.api.v1.dependencies.csrf import require_browser_origin
from watchtower.api.v1.dependencies.user_auth import CurrentProfile, get_current_profile
from watchtower.db.dependencies import get_db_session
from watchtower.schemas.application_membership import (
    ApplicationMembershipRead,
    ApplicationMembershipSet,
)
from watchtower.schemas.monitored_service import (
    MonitoredServiceCreate,
    MonitoredServiceRead,
    MonitoredServiceUpdate,
)
from watchtower.services.application_memberships import (
    ApplicationAccessDeniedError as MembershipAccessDeniedError,
)
from watchtower.services.application_memberships import (
    ApplicationNotFoundError,
    LastApplicationAdminError,
    ProfileNotFoundError,
    list_application_memberships,
    remove_application_membership,
    set_application_membership,
)
from watchtower.services.monitored_services import (
    ApplicationAccessDeniedError,
    MonitoredServiceConflictError,
    MonitoredServiceNotFoundError,
    create_service,
    deactivate_service,
    get_service,
    list_services,
    update_service,
)

router = APIRouter(
    prefix="/services",
    tags=["services"],
    responses={403: {"description": "Application access denied"}},
)


@router.post(
    "",
    response_model=MonitoredServiceRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_browser_origin)],
    responses={
        401: {"description": "Authentication required"},
        409: {"description": "Slug conflict"},
    },
)
async def create_owned_service(
    payload: MonitoredServiceCreate,
    current: Annotated[CurrentProfile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MonitoredServiceRead:
    """Create an event-source identity in the current profile."""

    try:
        service = await create_service(session, profile_id=current.profile.id, payload=payload)
    except MonitoredServiceConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Service slug already exists",
        ) from exc
    return MonitoredServiceRead.model_validate(service)


@router.get("", response_model=list[MonitoredServiceRead])
async def list_owned_services(
    current: Annotated[CurrentProfile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[MonitoredServiceRead]:
    """List only the current profile's services."""

    services = await list_services(session, profile_id=current.profile.id)
    return [MonitoredServiceRead.model_validate(service) for service in services]


@router.get(
    "/{service_id}/memberships",
    response_model=list[ApplicationMembershipRead],
    responses={404: {"description": "Application not found"}},
)
async def list_service_memberships(
    service_id: UUID,
    current: Annotated[CurrentProfile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[ApplicationMembershipRead]:
    """List human memberships when the caller can manage the application."""

    try:
        memberships = await list_application_memberships(
            session,
            actor_profile_id=current.profile.id,
            application_id=service_id,
        )
    except MembershipAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Application access denied",
        ) from exc
    except ApplicationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        ) from exc
    return [ApplicationMembershipRead.model_validate(membership) for membership in memberships]


@router.put(
    "/{service_id}/memberships/{profile_id}",
    response_model=ApplicationMembershipRead,
    dependencies=[Depends(require_browser_origin)],
    responses={
        404: {"description": "Application or profile not found"},
        409: {"description": "Application must retain an app_admin"},
    },
)
async def set_service_membership(
    service_id: UUID,
    profile_id: UUID,
    payload: ApplicationMembershipSet,
    current: Annotated[CurrentProfile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApplicationMembershipRead:
    """Set one local profile's complete application-scoped role."""

    try:
        membership = await set_application_membership(
            session,
            actor_profile_id=current.profile.id,
            application_id=service_id,
            target_profile_id=profile_id,
            role=payload.role,
        )
    except MembershipAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Application access denied",
        ) from exc
    except ApplicationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        ) from exc
    except ProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        ) from exc
    except LastApplicationAdminError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Application must retain an app_admin",
        ) from exc
    return ApplicationMembershipRead.model_validate(membership)


@router.delete(
    "/{service_id}/memberships/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_browser_origin)],
    responses={
        404: {"description": "Application or profile not found"},
        409: {"description": "Application must retain an app_admin"},
    },
)
async def delete_service_membership(
    service_id: UUID,
    profile_id: UUID,
    current: Annotated[CurrentProfile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """Remove one local profile's application membership."""

    try:
        await remove_application_membership(
            session,
            actor_profile_id=current.profile.id,
            application_id=service_id,
            target_profile_id=profile_id,
        )
    except MembershipAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Application access denied",
        ) from exc
    except ApplicationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        ) from exc
    except ProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        ) from exc
    except LastApplicationAdminError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Application must retain an app_admin",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{service_id}", response_model=MonitoredServiceRead)
async def get_owned_service(
    service_id: UUID,
    current: Annotated[CurrentProfile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MonitoredServiceRead:
    """Read one service without revealing other tenants' resources."""

    try:
        service = await get_service(session, profile_id=current.profile.id, service_id=service_id)
    except ApplicationAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Application access denied",
        ) from exc
    except MonitoredServiceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Service not found"
        ) from exc
    return MonitoredServiceRead.model_validate(service)


@router.patch(
    "/{service_id}",
    response_model=MonitoredServiceRead,
    dependencies=[Depends(require_browser_origin)],
)
async def update_owned_service(
    service_id: UUID,
    payload: MonitoredServiceUpdate,
    current: Annotated[CurrentProfile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MonitoredServiceRead:
    """Update one service owned by the current profile."""

    try:
        service = await update_service(
            session,
            profile_id=current.profile.id,
            service_id=service_id,
            payload=payload,
        )
    except ApplicationAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Application access denied",
        ) from exc
    except MonitoredServiceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Service not found"
        ) from exc
    return MonitoredServiceRead.model_validate(service)


@router.delete(
    "/{service_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_browser_origin)],
)
async def delete_owned_service(
    service_id: UUID,
    current: Annotated[CurrentProfile, Depends(get_current_profile)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """Deactivate one service while retaining its historical events."""

    try:
        await deactivate_service(session, profile_id=current.profile.id, service_id=service_id)
    except ApplicationAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Application access denied",
        ) from exc
    except MonitoredServiceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Service not found"
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
