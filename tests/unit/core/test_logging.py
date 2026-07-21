import json

from pytest import CaptureFixture

from watchtower.core.logging import configure_logging, get_logger


def test_structured_logging_emits_json(capsys: CaptureFixture[str]) -> None:
    configure_logging()

    get_logger("watchtower.test").info("health_checked", status="ok")

    record = json.loads(capsys.readouterr().out)
    assert record["event"] == "health_checked"
    assert record["status"] == "ok"
    assert record["level"] == "info"
    assert record["logger"] == "watchtower.test"
    assert record["timestamp"].endswith("Z")
