"""Version-one API router."""

from fastapi import APIRouter

from watchtower.api.v1.endpoints.api_keys import router as api_keys_router
from watchtower.api.v1.endpoints.auth import router as auth_router
from watchtower.api.v1.endpoints.health import router as health_router
from watchtower.api.v1.endpoints.profile_uptime import router as profile_uptime_router
from watchtower.api.v1.endpoints.services import router as services_router
from watchtower.api.v1.endpoints.uptime_monitors import router as uptime_monitors_router
from watchtower.api.v1.endpoints.webhooks import router as webhooks_router

router = APIRouter(prefix="/api/v1")
router.include_router(api_keys_router)
router.include_router(auth_router)
router.include_router(health_router)
router.include_router(profile_uptime_router)
router.include_router(services_router)
router.include_router(uptime_monitors_router)
router.include_router(webhooks_router)
