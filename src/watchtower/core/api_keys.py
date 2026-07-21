"""Generation and verification of high-entropy managed API keys."""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field

from pydantic import SecretStr

_API_KEY_PATTERN = re.compile(
    r"^wtk_v1_(?P<prefix>[A-Za-z0-9_-]{16})\.(?P<secret>[A-Za-z0-9_-]{43})$"
)
_DIGEST_DOMAIN = b"watchtower-api-key:v1\0"


class ApiKeyFormatError(ValueError):
    """The candidate does not match the bounded managed-key format."""


@dataclass(frozen=True, slots=True)
class ParsedApiKey:
    """Structurally valid key components; the secret is omitted from repr."""

    public_prefix: str
    secret: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class GeneratedApiKey:
    """One-time plaintext API key and its safe lookup prefix."""

    public_prefix: str
    token: SecretStr


def generate_api_key() -> GeneratedApiKey:
    """Create a key with a 96-bit lookup prefix and 256-bit secret."""

    public_prefix = secrets.token_urlsafe(12)
    secret = secrets.token_urlsafe(32)
    return GeneratedApiKey(
        public_prefix=public_prefix,
        token=SecretStr(f"wtk_v1_{public_prefix}.{secret}"),
    )


def parse_api_key(candidate: str) -> ParsedApiKey:
    """Reject malformed keys before database lookup or body consumption."""

    match = _API_KEY_PATTERN.fullmatch(candidate)
    if match is None:
        raise ApiKeyFormatError("Invalid API key format")
    return ParsedApiKey(
        public_prefix=match.group("prefix"),
        secret=match.group("secret"),
    )


def digest_api_key(token: str) -> bytes:
    """Return the deterministic SHA-256 verifier for a random 256-bit token."""

    return hashlib.sha256(_DIGEST_DOMAIN + token.encode("ascii")).digest()


def verify_api_key(candidate: str, expected_digest: bytes) -> bool:
    """Compare a candidate verifier in constant time."""

    return hmac.compare_digest(digest_api_key(candidate), expected_digest)
