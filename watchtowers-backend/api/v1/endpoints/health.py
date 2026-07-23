from fastapi import APIRouter

router = APIRouter(tags=["auth"])

@router.post("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "message": "The API is healthy and running."}
