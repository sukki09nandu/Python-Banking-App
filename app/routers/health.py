"""Health endpoints.

/health/live  - process is up (liveness probe; never touches the DB)
/health/ready - DB reachable and schema ready (readiness probe)
/health       - same as ready, for humans and load balancers
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.schemas import HealthOut

router = APIRouter(tags=["health"])
log = logging.getLogger(__name__)


@router.get("/health/live", response_model=HealthOut)
def live(request: Request):
    s = request.app.state.settings
    return HealthOut(status="ok", version=s.app_version, environment=s.environment)


@router.get("/health/ready", response_model=HealthOut)
@router.get("/health", response_model=HealthOut)
def ready(request: Request):
    s = request.app.state.settings
    db = request.app.state.db
    try:
        db.ping()
        db.ensure_schema()
    except Exception as exc:  # noqa: BLE001 - report any failure as not ready
        log.error("readiness check failed: %s: %s", type(exc).__name__, exc)
        body = HealthOut(
            status="unavailable",
            version=s.app_version,
            environment=s.environment,
            database="unreachable",
            detail=type(exc).__name__,
        )
        return JSONResponse(status_code=503, content=body.model_dump())
    return HealthOut(status="ok", version=s.app_version, environment=s.environment, database="ok")
