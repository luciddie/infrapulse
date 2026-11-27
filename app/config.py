from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    postgres_password: SecretStr

    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "infrapulse"
    db_user: str = "infrapulse"

    monitoring_enabled: bool = False
    monitoring_interval: int = 60
    monitoring_workers: int = 4
    incident_failure_threshold: int = 3
    service_incident_failure_threshold: int = 3
    telegram_enabled: bool = False
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.db_user,
            password=self.postgres_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name
        )


settings = Settings()
