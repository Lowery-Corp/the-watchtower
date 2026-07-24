from fastapi import APIRouter, Depends

from schemas.user import AuthorizedUser
from schemas.webhook import Event

from auth.dependencies import get_current_user

router = APIRouter(tags=["webhook"])


@router.get("", summary="Logging endpoint", description="Send logs to this api endpoint.")
async def webhook(
    event: Event,
    current_user: AuthorizedUser = Depends(get_current_user),
) -> dict[str, str]:
    topic_id = event.topic_id
    payload = event.payload
    print(current_user, flush=True)
    print(f"Topic ID: {topic_id}, Payload: {payload}", flush=True)
    return {"status": "ok"}
