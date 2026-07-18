from pytest import MonkeyPatch

from watchtower.core.config import Settings


def test_settings_read_watchtower_environment(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("WATCHTOWER_ENVIRONMENT", "test")
    monkeypatch.setenv(
        "WATCHTOWER_DATABASE_URL",
        "postgresql+asyncpg://watchtower:test@db:5432/watchtower_test",
    )

    settings = Settings()

    assert settings.environment == "test"
    assert settings.database_url.endswith("/watchtower_test")
