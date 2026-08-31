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



def test_uptime_worker_defaults_are_bounded_and_server_owned(monkeypatch: MonkeyPatch) -> None:
    for name in (
        "WATCHTOWER_UPTIME_CHECK_INTERVAL_SECONDS",
        "WATCHTOWER_UPTIME_CHECK_TIMEOUT_SECONDS",
        "WATCHTOWER_UPTIME_WORKER_BATCH_SIZE",
        "WATCHTOWER_UPTIME_WORKER_CONCURRENCY",
        "WATCHTOWER_UPTIME_HISTORY_RETENTION_DAYS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.uptime_check_interval_seconds == 60
    assert settings.uptime_check_timeout_seconds == 10.0
    assert settings.uptime_worker_batch_size == 50
    assert settings.uptime_worker_concurrency == 10
    assert settings.uptime_history_retention_days == 30
