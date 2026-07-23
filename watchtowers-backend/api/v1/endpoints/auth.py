from fastapi import APIRouter, Response, Request, Cookie

from repositories.auth import (
    blacklist_token,
)
from schemas.user import AuthorizedUser, UserToken
from repositories.auth import get_user_from_token

router = APIRouter(tags=["auth"])


@router.post("/logout")
async def logout_route(response: Response, request: Request) -> dict[str, bool]:
    token = request.cookies.get("access_token")

    if token:
        # decode token, get jti, store in blacklist table/cache
        blacklist_status = await blacklist_token(token)
        print("Blacklist status:", blacklist_status)

        response.delete_cookie(
            key="access_token",
            path="/",
        )
        return {"ok": True}
    return {"ok": False}


@router.get("/me")
async def get_current_user_route(
    access_token: str | None = Cookie(default=None)
) -> dict[str, AuthorizedUser | str]:
    if not access_token:
        return {"message": "Needs to login first"}

    authorized_user = await get_user_from_token(token=access_token)

    if not authorized_user:
        return {"message": "Invalid or expired token"}

    return {
        "user": authorized_user,
    }
