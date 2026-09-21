"""Fail-closed adapter for the external authentication service."""

from typing import Any

import httpx
from pydantic import SecretStr, ValidationError

from watchtower.schemas.auth import AuthenticatedSession, AuthenticatedUser


class AuthServiceError(RuntimeError):
    """Base class for sanitized external-auth failures."""


class AuthServiceUnauthorized(AuthServiceError):
    """The supplied credentials or token are not valid."""


class AuthServiceUnavailable(AuthServiceError):
    """The external auth service could not complete the request."""


class AuthServiceRateLimited(AuthServiceError):
    """The external auth service rejected the request budget."""

    def __init__(self, retry_after: int | None = None) -> None:
        super().__init__("Authentication service rate limited")
        self.retry_after = retry_after


class AuthServiceProtocolError(AuthServiceError):
    """The external auth service returned an unexpected contract."""


class AuthServiceClient:
    """Typed async client around the external auth-service contract."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http_client = http_client

    async def login(self, *, email: str, password: str) -> AuthenticatedSession:
        response = await self._request(
            "POST",
            "/api/v1/auth/login",
            json={"email": email, "password": password, "internal": True},
        )
        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise AuthServiceUnauthorized("Authentication failed")
        self._raise_for_availability(response)
        data = self._json_object(response)
        if "token" not in data:
            message = str(data.get("message", "")).lower()
            if "invalid" in message or "password" in message:
                raise AuthServiceUnauthorized("Authentication failed")
            raise AuthServiceProtocolError("Unexpected authentication response")
        try:
            user = AuthenticatedUser.model_validate(data)
            token = SecretStr(str(data["token"]))
        except (ValidationError, TypeError, ValueError) as exc:
            raise AuthServiceProtocolError("Unexpected authentication response") from exc
        if not token.get_secret_value():
            raise AuthServiceProtocolError("Unexpected authentication response")
        return AuthenticatedSession(user=user, token=token)

    async def get_current_user(self, token: str) -> AuthenticatedUser:
        response = await self._request(
            "POST",
            "/api/v1/auth/me",
            headers={"token": token},
        )
        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise AuthServiceUnauthorized("Authentication failed")
        self._raise_for_availability(response)
        try:
            return AuthenticatedUser.model_validate(self._json_object(response))
        except ValidationError as exc:
            raise AuthServiceProtocolError("Unexpected authentication response") from exc

    async def logout(self, token: str) -> None:
        response = await self._request(
            "POST",
            "/api/v1/auth/logout",
            headers=self._bearer_headers(token),
        )
        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise AuthServiceUnauthorized("Authentication failed")
        self._raise_for_availability(response)

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._http_client.request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AuthServiceUnavailable("Authentication service unavailable") from exc

    @staticmethod
    def _raise_for_availability(response: httpx.Response) -> None:
        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            raw_retry_after = response.headers.get("Retry-After", "")
            retry_after = int(raw_retry_after) if raw_retry_after.isdigit() else None
            raise AuthServiceRateLimited(retry_after)
        if response.status_code >= 500:
            raise AuthServiceUnavailable("Authentication service unavailable")
        if response.is_error:
            raise AuthServiceProtocolError("Unexpected authentication response")

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise AuthServiceProtocolError("Unexpected authentication response") from exc
        if not isinstance(data, dict):
            raise AuthServiceProtocolError("Unexpected authentication response")
        return data

    @staticmethod
    def _bearer_headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}
