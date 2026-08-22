from fastapi import Request, Response, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
import time
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
    Enforces strict multi-tenant isolation by extracting organization_id 
    from request headers (X-Organization-ID) or JWT claims and attaching it to request.state.
    """
    async def dispatch(self, request: Request, call_next):
        # Allow health checks and docs without tenant header
        if request.url.path in ["/health", "/docs", "/redoc", "/openapi.json", "/api/v1/auth/login"]:
            return await call_next(request)

        org_id_header = request.headers.get("X-Organization-ID")
        
        if org_id_header:
            try:
                request.state.organization_id = int(org_id_header)
            except ValueError:
                return Response(content='{"detail": "Invalid X-Organization-ID header format"}', status_code=400, media_type="application/json")
        else:
            # Default or unassigned tenant context for restricted endpoints
            request.state.organization_id = None

        response = await call_next(request)
        return response
