"""Runtime configuration, read from environment variables (Kubernetes ConfigMap).

Credentials are never read from this file or the ConfigMap. In AWS the app only
receives the *ARN* of the Secrets Manager secret and fetches the username and
password at runtime using its IAM role (EKS Pod Identity).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_name: str = "banking-api"
    app_version: str = __version__
    environment: str = "local"
    log_level: str = "INFO"

    # Option 1 (local/dev/tests only): a complete SQLAlchemy URL.
    database_url: str | None = None

    # Option 2 (AWS): host details from ConfigMap + credentials from Secrets Manager.
    db_host: str | None = None
    db_port: int = 5432
    db_name: str = "banking"
    db_sslmode: str = "require"
    db_secret_arn: str | None = None
    db_secret_cache_seconds: int = 300
    aws_region: str = "us-east-1"

    seed_demo_data: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
