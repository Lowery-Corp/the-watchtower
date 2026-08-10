from schemas.user import UserLogin, LoginResponse
from repositories.auth import login_user, get_user_from_token

async def login(user_login: UserLogin) -> dict[str, str | LoginResponse]:
    user_token: str = await login_user(user_login.username, user_login.password)
    assert user_token, "Token should not be None or empty"

    authorized_user = await get_user_from_token(user_token)
    assert authorized_user is not None, "Authorized user should not be None"

    user_response = LoginResponse(username=authorized_user.username)
    assert user_response.username, "Username should not be None or empty"

    return {"token": user_token, "user": user_response}

