from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://localhost/pawlocal"
    api_prefix: str = "/api/v1"
    cognito_issuer: str | None = None
    cognito_app_client_id: str | None = None
    cognito_resource_audience: str | None = None
    cognito_require_resource_audience: bool = False
    write_rate_limit_per_minute: int = 10
    telemetry_enabled: bool = False
    otlp_endpoint: str = "http://otel-collector:4318"
    demo_faults_enabled: bool = False

    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE, env_prefix="PAWLOCAL_", extra="ignore"
    )


settings = Settings()
