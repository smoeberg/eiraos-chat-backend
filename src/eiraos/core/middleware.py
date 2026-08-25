from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import re
import uuid
import structlog

logger = structlog.get_logger()
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
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
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if _REQUEST_ID.fullmatch(supplied) else str(uuid.uuid4())
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)

        try:
            response: Response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            structlog.contextvars.clear_contextvars()


class RequestBodyLoggingMiddleware(BaseHTTPMiddleware):
    """Capture the raw request body and stash it for idempotency hashing.

    Idempotency (``core.idempotency._body_digest``) digests
    ``request.state.cached_body`` to detect payload replays. Without this
    middleware, that attribute never gets set and idempotency crashes.
    """

    async def dispatch(self, request: Request, call_next):
        from eiraos.core.config import settings

        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                declared_size = int(declared)
            except ValueError:
                return self._problem(request, 400, "Invalid Content-Length")
            if declared_size < 0:
                return self._problem(request, 400, "Invalid Content-Length")
            if declared_size > settings.MAX_REQUEST_BODY_BYTES:
                return self._problem(request, 413, "Request body too large")
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > settings.MAX_REQUEST_BODY_BYTES:
                return self._problem(request, 413, "Request body too large")
        body = bytes(chunks)
        request.state.cached_body = body
        # Rebuild the stream so downstream readers still see the original body.
        sent = False
        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = receive
        request._stream_consumed = False
        response: Response = await call_next(request)
        return response

    @staticmethod
    def _problem(request: Request, status_code: int, detail: str) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={
            "type": "about:blank",
            "title": "Bad Request" if status_code == 400 else "Payload Too Large",
            "status": status_code,
            "detail": detail,
            "instance": request.url.path,
        })
