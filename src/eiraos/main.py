from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from prometheus_fastapi_instrumentator import Instrumentator
import structlog
import time
import redis.asyncio as aioredis
from sqlalchemy import text

from eiraos.core.config import settings
from eiraos.core.ratelimit import limiter
from eiraos.core.database import AsyncSessionLocal
from eiraos.api.v1.router import api_router
from eiraos.core.exceptions import EiraOSException
from eiraos.core.middleware import SecurityHeadersMiddleware, TenantIsolationMiddleware, RequestTracingMiddleware

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ]
)
logger = structlog.get_logger()

app = FastAPI(
    title="EiraOS Enterprise Chat Backend",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
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

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(TenantIsolationMiddleware)
app.add_middleware(RequestTracingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://app.eiraos.ai", "https://admin.eiraos.ai", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

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

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

@app.get("/health/live", tags=["System"])
async def health_live():
    return {"status": "alive"}

@app.get("/health/ready", tags=["System"])
async def health_ready():
    health_status = {"status": "healthy", "database": "disconnected", "redis": "disconnected"}
    
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            health_status["database"] = "connected"
    except Exception as e:
        logger.error("health_check_database_failed", error=str(e))
        health_status["status"] = "degraded"
        health_status["database"] = "unavailable"

    try:
        redis_client = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
        await redis_client.ping()
        await redis_client.close()
        health_status["redis"] = "connected"
    except Exception as e:
        logger.error("health_check_redis_failed", error=str(e))
        health_status["status"] = "degraded"
        health_status["redis"] = "unavailable"

    status_code = status.HTTP_200_OK if health_status["status"] == "healthy" else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content=health_status)

@app.get("/health", tags=["System"])
async def health_check():
    return await health_ready()

@app.get("/", tags=["System"])
async def root():
    return {"system": "EiraOS Chat Backend", "version": "1.0.0", "status": "active", "docs": "/docs"}
