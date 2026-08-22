from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from eiraos.api.v1.router import api_router
from eiraos.core.middleware import SecurityHeadersMiddleware, TenantIsolationMiddleware
import time

app = FastAPI(
    title="EiraOS Chat & AI Backend",
    version="1.0.0",
    description="Enterprise-grade AI, RAG, and Chat Backend for EiraOS",
    docs_url="/docs",
    redoc_url="/redoc"
)

# 1. Security & Tenant Middlewares
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

# 3. Include API v1 Router
app.include_router(api_router, prefix="/api/v1")

@app.get("/health", tags=["System"])
async def health_check(request: Request):
    """System health check endpoint with tenant context verification."""
    org_id = getattr(request.state, "organization_id", None)
    return {
        "status": "healthy",
        "service": "eiraos-chat-backend",
        "tenant_context": org_id
    }
