"""FastAPI application entrypoint: `uvicorn app.main:app`."""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse

from app.config import Settings, get_settings
from app.db import Database
from app.routers import accounts, customers, health, transactions


class JsonFormatter(logging.Formatter):
    """One JSON object per line - easy to query in CloudWatch Logs Insights."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    logging.getLogger("uvicorn.access").disabled = True  # replaced by our access log


log = logging.getLogger("app")
STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db: Database = app.state.db
        try:
            db.ensure_schema()
            if settings.seed_demo_data:
                from app.seed import seed

                seed(db)
        except Exception as exc:  # noqa: BLE001
            # Stay up so liveness passes and readiness reports the problem.
            log.error("database initialisation failed: %s: %s", type(exc).__name__, exc)
        log.info(
            "started %s %s (%s)", settings.app_name, settings.app_version, settings.environment
        )
        yield
        db.dispose()

    app = FastAPI(
        title="Banking API",
        version=settings.app_version,
        description="Sample banking transaction API. Synthetic data only.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.db = Database(settings)

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["x-request-id"] = request_id
            return response
        finally:
            # Never log request bodies (they may contain customer data).
            route = request.scope.get("route")
            log.info(
                "request",
                extra={
                    "extra_fields": {
                        "request_id": request_id,
                        "method": request.method,
                        "path": getattr(route, "path", request.url.path),
                        "status": status_code,
                        "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    }
                },
            )

    @app.get("/", include_in_schema=False)
    def root():
        # Browsers landing on the bare host go to the web UI.
        return RedirectResponse(url="/ui")

    @app.get("/ui", include_in_schema=False)
    def ui():
        return FileResponse(STATIC_DIR / "index.html")

    app.include_router(health.router)
    app.include_router(customers.router)
    app.include_router(accounts.router)
    app.include_router(transactions.router)
    return app


app = create_app()
