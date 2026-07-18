"""Version-one API router."""

from fastapi import APIRouter

from watchtower.api.v1.endpoints.health import router as health_router
from watchtower.api.v1.endpoints.webhooks import router as webhooks_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(webhooks_router)
