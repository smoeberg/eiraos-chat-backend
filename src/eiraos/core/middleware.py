from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import uuid
import structlog
import jwt
from eiraos.core.config import settings

logger = structlog.get_logger()

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

class TenantIsolationMiddleware(BaseHTTPMiddleware):
    """
    Enforces multi-tenant isolation by extracting verified organization context from JWT.
    Header fallback is completely removed to prevent IDOR and header spoofing.
    """
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ["/health", "/docs", "/redoc", "/openapi.json", "/metrics", "/api/v1/auth/login", "/api/v1/auth/register"]:
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        token_org_id = None
        if auth_header and auth_header.startswith("Bearer "):
            try:
                token = auth_header.split(" ")[1]
                payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
                token_org_id = payload.get("organization_id")
            except Exception:
                pass

        if token_org_id:
            request.state.organization_id = int(token_org_id)
        else:
            request.state.organization_id = None

        response = await call_next(request)
        return response

class RequestTracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
