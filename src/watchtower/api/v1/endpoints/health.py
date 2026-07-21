"""Operational health endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from watchtower.db.dependencies import get_db_session
from watchtower.schemas.health import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Report the API's basic status."""

    return HealthResponse(status="ok")


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    """Report process liveness without checking dependencies."""

    return HealthResponse(status="alive")


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def ready(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> HealthResponse | JSONResponse:
    """Report whether PostgreSQL can accept work."""

    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        payload = HealthResponse(status="not_ready").model_dump()
        return JSONResponse(payload, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return HealthResponse(status="ready")
