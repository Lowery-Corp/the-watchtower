from httpx import ConnectTimeout, HTTPError, ReadTimeout, RequestError, Response
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


def should_retry_http_exception(exc: BaseException) -> bool:
    if isinstance(exc, (ConnectTimeout, ReadTimeout, RequestError)):
        return True

    if isinstance(exc, HTTPError):
        response: Response | None = getattr(exc, "response", None)
        if response is None:
            return True
        return response.status_code in {500, 502, 503, 504}

    return False


def build_http_retry(attempts: int = 3):
    return retry(
        retry=retry_if_exception(should_retry_http_exception),
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
