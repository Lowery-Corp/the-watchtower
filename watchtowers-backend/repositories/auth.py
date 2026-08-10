import uuid
from typing import Any

from httpxC.http_client import http_client, make_request
from schemas.user import AuthorizedUser
from core.config import settings
from core.retry import build_http_retry


@build_http_retry(attempts=2)
async def login_user(username: str, password: str) -> str:
    auth_endpoint: str = f"{settings.auth_api_url}/api/v1/auth/login"
    response = await http_client.post(
        auth_endpoint,
        json={
            "email": username,
            "password": password,
            "internal": True
        },
    )
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    token: str = data.get("token", "")

    if token == "":
        raise ValueError("Token not found in response data")

    return token


@build_http_retry(attempts=2)
async def get_user_from_token(token: str) -> AuthorizedUser | None:
    auth_endpoint = f"{settings.auth_api_url}/api/v1/auth/me"
    headers = {"token": token}
    response = await make_request("POST", auth_endpoint, headers=headers)
    response.raise_for_status()
    data = response.json()

    if not data or "id" not in data or "username" not in data:
        return None
    return AuthorizedUser(
        id=uuid.UUID(data.get("id", "")),
        username=data.get("username", ""),
        is_admin=data.get("is_admin", False),
    )


@build_http_retry(attempts=2)
async def blacklist_token(token: str) -> bool:
    auth_endpoint: str = f"{settings.auth_api_url}/api/v1/auth/logout"
    response = await http_client.post(
        auth_endpoint,
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code == 200:
        return True
    return False
