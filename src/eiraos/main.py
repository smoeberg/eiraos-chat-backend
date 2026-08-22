from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from eiraos.api.v1.router import api_router
from eiraos.core.middleware import SecurityHeadersMiddleware, TenantIsolationMiddleware, RequestTracingMiddleware
from eiraos.core.logging import setup_logging
from eiraos.core.exceptions import register_exception_handlers
import structlog

# Setup Structured JSON Logging
setup_logging()
logger = structlog.get_logger()

app = FastAPI(
    title="EiraOS Chat & AI Backend",
    version="1.0.0",
    description="Enterprise-grade AI, RAG, and Chat Backend for EiraOS",
    docs_url="/docs",
    redoc_url="/redoc"
)

# 0. Register RFC 7807 Exception Handlers
register_exception_handlers(app)

# 1. Middlewares (Order matters: RequestTracing first, then Security, then Tenant)
app.add_middleware(RequestTracingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(TenantIsolationMiddleware)

# 2. Strict CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://eiraos.ai", "https://*.eiraos.ai", "http://localhost:3000", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 3. Prometheus Metrics Instrumentation
Instrumentator().instrument(app).expose(app, endpoint="/metrics", tags=["System"])

# 4. Include API v1 Router
app.include_router(api_router, prefix="/api/v1")

@app.get("/health", tags=["System"])
async def health_check(request: Request):
    """System health check endpoint with tenant context verification."""
    org_id = getattr(request.state, "organization_id", None)
    logger.info("Health check requested", tenant_id=org_id)
    return {
        "status": "healthy",
        "service": "eiraos-chat-backend",
        "tenant_context": org_id
    }
