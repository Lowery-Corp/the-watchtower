from fastapi import Cookie, HTTPException, status

from repositories.auth import (
    get_user_from_token,
)
from schemas.user import AuthorizedUser

def require_admin_user(current_user: AuthorizedUser) -> None:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden",
        )


async def get_current_user(
    access_token: str | None = Cookie(default=None),
) -> AuthorizedUser:
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    authorized_user = await get_user_from_token(token=access_token)

    if not authorized_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    return authorized_user