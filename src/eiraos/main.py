from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from prometheus_fastapi_instrumentator import Instrumentator
import structlog
import time
import redis.asyncio as aioredis
from sqlalchemy import text

from eiraos.core.config import settings
from eiraos.core.database import AsyncSessionLocal
from eiraos.api.v1.router import api_router
from eiraos.core.exceptions import EiraOSException

# Configure structured JSON logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ]
)
logger = structlog.get_logger()

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
app = FastAPI(
    title="EiraOS Enterprise Chat Backend",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request Tracing & Structured Logging Middleware
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_sec=round(duration, 4)
    )
    return response

# Global Exception Handlers
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

# Include API v1 Router
app.include_router(api_router, prefix=settings.API_V1_STR)

# Prometheus instrumentation
Instrumentator().instrument(app).expose(app, endpoint="/metrics")

@app.get("/health", tags=["System"])
async def health_check():
    """
    Robust system health check verifying PostgreSQL and Redis connectivity.
    """
    health_status = {"status": "healthy", "database": "disconnected", "redis": "disconnected"}
    
    # Check PostgreSQL
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            health_status["database"] = "connected"
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["database_error"] = str(e)

    # Check Redis
    try:
        redis_client = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
        await redis_client.ping()
        await redis_client.close()
        health_status["redis"] = "connected"
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["redis_error"] = str(e)

    status_code = status.HTTP_200_OK if health_status["status"] == "healthy" else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=status_code, content=health_status)

@app.get("/", tags=["System"])
async def root():
    return {"system": "EiraOS Chat Backend", "version": "1.0.0", "status": "active", "docs": "/docs"}
