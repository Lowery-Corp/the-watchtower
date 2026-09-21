"""API-key machine source request contract tests."""

import pytest
from pydantic import ValidationError

from watchtower.schemas.api_key import ApiKeyCreate


def test_api_key_create_requires_machine_source_service() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ApiKeyCreate.model_validate({"name": "missing-source"})

    assert exc_info.value.errors()[0]["loc"] == ("service_id",)
    assert exc_info.value.errors()[0]["type"] == "missing"
