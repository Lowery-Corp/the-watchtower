"""Security tests for managed machine API-key material."""

import base64

import pytest

from watchtower.core.api_keys import (
    ApiKeyFormatError,
    digest_api_key,
    generate_api_key,
    parse_api_key,
    verify_api_key,
)


def test_generated_key_has_public_prefix_and_256_bit_secret() -> None:
    generated = generate_api_key()
    parsed = parse_api_key(generated.token.get_secret_value())
    padded_secret = parsed.secret + "=" * (-len(parsed.secret) % 4)

    assert generated.public_prefix == parsed.public_prefix
    assert parsed.public_prefix
    assert len(base64.urlsafe_b64decode(padded_secret)) >= 32
    assert generated.token.get_secret_value().startswith("wtk_v1_")
    assert generated.token.get_secret_value() not in repr(generated)


def test_digest_verification_accepts_exact_token_only() -> None:
    generated = generate_api_key()
    token = generated.token.get_secret_value()
    digest = digest_api_key(token)

    assert verify_api_key(token, digest) is True
    assert verify_api_key(f"{token}x", digest) is False
    assert token.encode() not in digest


@pytest.mark.parametrize(
    "candidate",
    [
        "",
        "wtk_v1_missing-separator",
        "bad_prefix.secret",
        "wtk_v1_.secret",
        "wtk_v1_prefix.",
        "wtk_v1_prefix.secret.extra",
        "wtk_v1_prefix space.secret",
    ],
)
def test_parser_rejects_malformed_keys(candidate: str) -> None:
    with pytest.raises(ApiKeyFormatError):
        parse_api_key(candidate)
