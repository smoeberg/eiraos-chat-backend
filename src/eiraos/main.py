import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, Response
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from prometheus_fastapi_instrumentator import Instrumentator
import structlog
import time
import prometheus_client
import redis.asyncio as aioredis
from sqlalchemy import text

from eiraos.core.config import settings
from eiraos.core.ratelimit import limiter
from eiraos.core.database import AsyncSessionLocal, engine
from eiraos.api.v1.router import api_router
from eiraos.api.v1.auth import get_current_active_organization, get_current_user
from eiraos.core.exceptions import EiraOSException
from eiraos.core.middleware import SecurityHeadersMiddleware, TenantIsolationMiddleware, RequestTracingMiddleware, RequestBodyLoggingMiddleware
from eiraos.core.logging import setup_logging

setup_logging()
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(
    title="EiraOS Enterprise Chat Backend",
    version="1.0.0",
    docs_url=None if settings.APP_ENV == "production" else "/docs",
    redoc_url=None if settings.APP_ENV == "production" else "/redoc",
    lifespan=lifespan,
)

app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "type": "about:blank",
            "title": "Rate Limit Exceeded",
            "status": 429,
            "detail": "Too many requests. Please slow down.",
            "instance": request.url.path
        }
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "type": "about:blank",
            "title": "Validation Error",
            "status": 422,
            "detail": "Request validation failed",
            "errors": exc.errors(),
            "instance": request.url.path
        }
    )

app.add_middleware(TenantIsolationMiddleware)
app.add_middleware(RequestBodyLoggingMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.trusted_hosts))

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Request-ID",
        "Idempotency-Key",
    ],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestTracingMiddleware)

@app.exception_handler(EiraOSException)
async def eiraos_exception_handler(request: Request, exc: EiraOSException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "type": "about:blank",
            "title": exc.title,
            "status": exc.status_code,
            "detail": exc.detail,
            "instance": request.url.path
        }
    )

app.include_router(api_router, prefix=settings.API_V1_STR)

Instrumentator().instrument(app)


@app.get("/metrics", include_in_schema=False)
async def metrics(
    _current_user: dict = Depends(get_current_user),
    _organization_id: int = Depends(get_current_active_organization),
):
    return Response(
        content=prometheus_client.generate_latest(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )

@app.get("/health/live", tags=["System"])
async def health_live():
    return {"status": "alive"}

@app.get("/health/ready", tags=["System"])
async def health_ready():
    health_status = {"status": "healthy", "database": "disconnected", "redis": "disconnected"}
    _probe_timeout = 2.0

    try:
        async with AsyncSessionLocal() as session:
            await asyncio.wait_for(
                session.execute(text("SELECT 1")), timeout=_probe_timeout
            )
            health_status["database"] = "connected"
    except Exception as exc:
        logger.error("health_check_database_failed", error_type=type(exc).__name__)
        health_status["status"] = "degraded"
        health_status["database"] = "unavailable"

    if not settings.REDIS_URL:
        health_status["redis"] = "disabled"
    else:
        redis_client = None
        try:
            redis_client = aioredis.from_url(
                settings.REDIS_URL, encoding="utf-8", decode_responses=True
            )
            await asyncio.wait_for(redis_client.ping(), timeout=_probe_timeout)
            health_status["redis"] = "connected"
        except Exception as exc:
            logger.error("health_check_redis_failed", error_type=type(exc).__name__)
            health_status["status"] = "degraded"
            health_status["redis"] = "unavailable"
        finally:
            if redis_client is not None:
                await redis_client.aclose()

    status_code = (
        status.HTTP_200_OK
        if health_status["status"] == "healthy"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(status_code=status_code, content=health_status)

@app.get("/health", tags=["System"])
async def health_check():
    return await health_ready()

@app.get("/", tags=["System"])
async def root():
    return {
        "system": "EiraOS Chat Backend", "version": "1.0.0",
        "status": "active",
        "docs": None if settings.APP_ENV == "production" else "/docs",
    }
