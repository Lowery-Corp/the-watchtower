"""Contract tests for the version-one inbound event envelope."""

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from watchtower.schemas.event import EventEnvelope


def valid_event() -> dict[str, object]:
    """Return the smallest representative version-one event."""

    return {
        "spec_version": "1.0",
        "event_id": "0c34b762-04f9-4df5-80a0-7ff773d7e13d",
        "event_type": "service.heartbeat",
        "source": "scrappy",
        "subject": "api-1",
        "occurred_at": "2026-07-18T20:00:00Z",
        "severity": "info",
        "environment": "production",
        "correlation_id": "trace-123",
        "data": {"status": "healthy", "latency_ms": 12},
    }


def test_valid_event_is_normalized_and_preserves_extensions() -> None:
    payload = valid_event()
    payload["trace_vendor"] = "example"

    event = EventEnvelope.model_validate(payload)
    serialized = event.model_dump(mode="json")

    assert event.event_id == UUID("0c34b762-04f9-4df5-80a0-7ff773d7e13d")
    assert event.occurred_at == datetime(2026, 7, 18, 20, 0, tzinfo=UTC)
    assert serialized["trace_vendor"] == "example"
    assert serialized["data"] == {"status": "healthy", "latency_ms": 12}


def test_non_utc_rfc3339_offset_is_normalized_to_utc() -> None:
    payload = valid_event()
    payload["occurred_at"] = "2026-07-18T22:00:00+02:00"

    event = EventEnvelope.model_validate(payload)

    assert event.occurred_at == datetime(2026, 7, 18, 20, 0, tzinfo=UTC)


def test_unsupported_spec_version_is_rejected() -> None:
    payload = valid_event()
    payload["spec_version"] = "2.0"

    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload)


def test_naive_occurred_at_is_rejected() -> None:
    payload = valid_event()
    payload["occurred_at"] = "2026-07-18T20:00:00"

    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload)


def test_occurred_at_rejects_numeric_json_values() -> None:
    payload = valid_event()
    payload["occurred_at"] = 1_784_404_800

    with pytest.raises(ValidationError):
        EventEnvelope.model_validate_json(json.dumps(payload))


def test_occurred_at_rejects_numeric_strings() -> None:
    payload = valid_event()
    payload["occurred_at"] = "1784404800"

    with pytest.raises(ValidationError):
        EventEnvelope.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_json_numbers_are_rejected(constant: str) -> None:
    raw = json.dumps(valid_event()).replace(
        '"data": {"status": "healthy", "latency_ms": 12}',
        f'"data": {{"value": {constant}}}',
    )

    with pytest.raises(ValidationError):
        EventEnvelope.model_validate_json(raw)


def test_non_finite_extension_number_is_rejected() -> None:
    raw = json.dumps(valid_event())[:-1] + ', "extension": {"value": NaN}}'

    with pytest.raises(ValidationError):
        EventEnvelope.model_validate_json(raw)


def test_data_must_be_a_json_object() -> None:
    payload = valid_event()
    payload["data"] = ["not", "an", "object"]

    with pytest.raises(ValidationError):
        EventEnvelope.model_validate(payload)
