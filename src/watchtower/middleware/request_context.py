"""Request correlation middleware."""

import re
from contextvars import ContextVar
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}")
request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestContextMiddleware:
    """Assign a safe request ID and return it on every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied = Headers(scope=scope).get(REQUEST_ID_HEADER, "")
        request_id = supplied if _REQUEST_ID_PATTERN.fullmatch(supplied) else str(uuid4())
        token = request_id_context.set(request_id)
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            if not response_started:
                response = PlainTextResponse("Internal Server Error", status_code=500)
                await response(scope, receive, send_with_request_id)
            raise
        finally:
            request_id_context.reset(token)
