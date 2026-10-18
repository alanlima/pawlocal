from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://localhost/pawlocal"
    database_host: str | None = None
    database_port: int = 5432
    database_name: str | None = None
    database_user: str | None = None
    database_password: str | None = None
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

    @property
    def sqlalchemy_url(self) -> URL:
        """Build a URL from discrete Compose fields when provided, escaping credentials safely."""
        if self.database_host:
            return URL.create(
                "postgresql+psycopg",
                username=self.database_user,
                password=self.database_password,
                host=self.database_host,
                port=self.database_port,
                database=self.database_name,
            )
        return make_url(self.database_url)


settings = Settings()
