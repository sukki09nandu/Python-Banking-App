"""Database engine management and Secrets Manager integration."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class DatabaseConfigError(RuntimeError):
    """Raised when the app has no usable database configuration."""


class SecretCredentials:
    """Fetches DB credentials from AWS Secrets Manager and caches them briefly.

    RDS-managed master secrets rotate automatically, so credentials are injected
    on every *new* connection (see ``do_connect`` below) instead of being baked
    into the engine URL. A short cache keeps Secrets Manager calls low.
    """

    def __init__(self, secret_arn: str, region: str, ttl_seconds: int) -> None:
        self.secret_arn = secret_arn
        self.region = region
        self.ttl_seconds = ttl_seconds
        self._cached: dict | None = None
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    def get(self) -> dict:
        with self._lock:
            if self._cached is None or time.monotonic() - self._fetched_at > self.ttl_seconds:
                import boto3  # imported lazily so local runs/tests don't need AWS

                client = boto3.client("secretsmanager", region_name=self.region)
                value = client.get_secret_value(SecretId=self.secret_arn)
                self._cached = json.loads(value["SecretString"])
                self._fetched_at = time.monotonic()
                log.info("database credentials loaded from Secrets Manager")
            return self._cached

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None


def build_engine(settings: Settings) -> Engine:
    if settings.database_url:
        url = settings.database_url
        kwargs: dict = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        return create_engine(url, **kwargs)

    if not (settings.db_host and settings.db_secret_arn):
        raise DatabaseConfigError(
            "No database configuration: set DATABASE_URL, or DB_HOST and DB_SECRET_ARN"
        )

    creds = SecretCredentials(
        settings.db_secret_arn, settings.aws_region, settings.db_secret_cache_seconds
    )
    creds.get()  # fail fast with a clear error (e.g. AccessDenied) at first use

    url = URL.create(
        "postgresql+psycopg",
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
        query={"sslmode": settings.db_sslmode, "connect_timeout": "5"},
    )
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=1800, pool_size=5)

    @event.listens_for(engine, "do_connect")
    def _inject_credentials(dialect, conn_rec, cargs, cparams):  # noqa: ANN001
        secret = creds.get()
        cparams["user"] = secret["username"]
        cparams["password"] = secret["password"]

    @event.listens_for(engine, "handle_error")
    def _on_auth_error(ctx):  # noqa: ANN001
        if "password authentication failed" in str(ctx.original_exception):
            log.warning("database authentication failed; refreshing cached secret")
            creds.invalidate()

    return engine


class Database:
    """Lazily creates the engine so the pod can start (and report not-ready)
    even when the database or the secret is unreachable."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._engine: Engine | None = None
        self._sessionmaker: sessionmaker[Session] | None = None
        self._schema_ready = False
        self._lock = threading.Lock()

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            with self._lock:
                if self._engine is None:
                    engine = build_engine(self.settings)
                    self._sessionmaker = sessionmaker(engine, expire_on_commit=False)
                    self._engine = engine
        return self._engine

    def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        from app import models  # noqa: F401  (register tables)

        Base.metadata.create_all(self.engine)
        self._schema_ready = True
        log.info("database schema ready")

    def ping(self) -> None:
        with self.engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    def session(self) -> Session:
        self.ensure_schema()
        assert self._sessionmaker is not None
        return self._sessionmaker()

    def iter_session(self) -> Iterator[Session]:
        session = self.session()
        try:
            yield session
        finally:
            session.close()

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
