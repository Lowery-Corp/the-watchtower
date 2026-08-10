from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str
    auth_api_url: str
    offload_api_url: str
    internal_api_username: str
    internal_api_password: str
    celery_broker_url: str
    celery_result_backend: str
    rabbitmq_default_user: str
    rabbitmq_default_pass: str
    allowed_origins: list[str] = []
    cookie_key: str

    internal_cookie: str | None = None

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()