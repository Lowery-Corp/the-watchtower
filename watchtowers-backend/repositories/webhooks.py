from httpx import ConnectTimeout, HTTPError

from httpxC.http_client import http_client
from schemas.user import UserToken, AuthorizedUser
from core.config import settings
from core.retry import build_http_retry



@build_http_retry(attempts=2)
async def send_hook_to_worker(event) -> UserToken | bool:
    auth_endpoint: str = f"{settings.offload_api_url}/api/v1/auth/login"
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

