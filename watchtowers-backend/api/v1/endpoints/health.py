from fastapi import APIRouter

router = APIRouter(tags=["health"])

@router.get("", summary="Health Check Endpoint", description="Check the health status of the API.")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
