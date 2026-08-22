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
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ["/health", "/docs", "/redoc", "/openapi.json", "/metrics", "/api/v1/auth/login"]:
            return await call_next(request)

        org_id_header = request.headers.get("X-Organization-ID")
        if org_id_header:
            try:
                request.state.organization_id = int(org_id_header)
            except ValueError:
                return Response(content='{"detail": "Invalid X-Organization-ID header format"}', status_code=400, media_type="application/json")
        else:
            request.state.organization_id = None

        response = await call_next(request)
        return response

class RequestTracingMiddleware(BaseHTTPMiddleware):
    """Injects a unique X-Request-ID into every request/response and binds it to structured logs."""
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        
        # Bind request_id to structlog context
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
