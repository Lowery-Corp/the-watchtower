from pytest import MonkeyPatch

from watchtower.core.config import Settings


def test_default_auth_service_uses_required_https_origin(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("WATCHTOWER_AUTH_SERVICE_URL", raising=False)

    settings = Settings(_env_file=None)

    assert settings.auth_service_url == "https://dauth.johnmgrubbs.io"


def test_settings_read_watchtower_environment(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("WATCHTOWER_ENVIRONMENT", "test")
    monkeypatch.setenv(
        "WATCHTOWER_DATABASE_URL",
        "postgresql+asyncpg://watchtower:test@db:5432/watchtower_test",
    )

    settings = Settings()

    assert settings.environment == "test"
    assert settings.database_url.endswith("/watchtower_test")


def test_webhook_security_settings_are_typed(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv(
        "WATCHTOWER_WEBHOOK_SECRETS",
        '{"scrappy":"development-signing-secret"}',
    )
    monkeypatch.setenv("WATCHTOWER_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS", "120")
    monkeypatch.setenv("WATCHTOWER_MAX_WEBHOOK_BODY_BYTES", "1024")
    monkeypatch.setenv("WATCHTOWER_WEBHOOK_RATE_LIMIT_REQUESTS", "25")
    monkeypatch.setenv("WATCHTOWER_WEBHOOK_RATE_LIMIT_WINDOW_SECONDS", "30")

    settings = Settings()

    assert settings.webhook_secrets["scrappy"].get_secret_value() == (
        "development-signing-secret"
    )
    assert settings.webhook_signature_tolerance_seconds == 120
    assert settings.max_webhook_body_bytes == 1024
    assert settings.webhook_rate_limit_requests == 25
    assert settings.webhook_rate_limit_window_seconds == 30
