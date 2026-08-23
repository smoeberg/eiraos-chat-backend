from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import uuid
import structlog

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
    Pass-through middleware. Tenant context and authentication are strictly enforced
    via authoritative FastAPI dependencies (e.g. get_current_active_organization).
    """
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        return response

class RequestTracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
