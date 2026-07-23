from httpx import ConnectTimeout, HTTPError

from httpxC.http_client import http_client
from schemas.user import UserToken, AuthorizedUser
from core.config import settings
from core.retry import build_http_retry


@build_http_retry(attempts=2)
async def login_user(username: str, password: str) -> UserToken | bool:
    auth_endpoint: str = f"{settings.auth_api_url}/api/v1/auth/login"
    response = await http_client.post(
        auth_endpoint,
        json={"email": username, "password": password},
    )
    response.raise_for_status()
    data = response.json()

    user_token = UserToken(
        token=data.get("token", "fake-token"),
    )

    return user_token


@build_http_retry(attempts=2)
async def get_user_from_token(token: str) -> AuthorizedUser | None:
    auth_endpoint = f"{settings.auth_api_url}/api/v1/auth/me"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        response = await http_client.get(auth_endpoint, headers=headers)

        if response.status_code == 401:
            return None

        response.raise_for_status()
        data = response.json()

        return AuthorizedUser(
            id=str(data.get("id", "")),
            username=data.get("username", ""),
            email=data.get("email", ""),
            is_admin=data.get("is_admin", False),
        )
    except ConnectTimeout:
        return None
    except HTTPError:
        return None


async def blacklist_token(token: str) -> bool:
    auth_endpoint: str = f"{settings.auth_api_url}/api/v1/auth/logout"
    response = await http_client.post(
        auth_endpoint,
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code == 200:
        return True
    return False


@build_http_retry(attempts=2)
async def internal_api_login() -> bool:
    user_token: UserToken | bool = await login_user(
        settings.internal_api_username,
        settings.internal_api_password,
    )
    if type(user_token) is bool:
        return user_token

    settings.internal_cookie = user_token.token
    return True
