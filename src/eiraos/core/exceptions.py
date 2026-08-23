from fastapi import Request, status, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from slowapi.errors import RateLimitExceeded
import structlog

logger = structlog.get_logger()

class EiraOSException(Exception):
    def __init__(self, title: str, detail: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        self.title = title
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)

def register_exception_handlers(app):
    """Register RFC 7807 compliant problem details exception handlers."""

    @app.exception_handler(EiraOSException)
    async def eiraos_exception_handler(request: Request, exc: EiraOSException):
        logger.error("EiraOS Domain Exception", title=exc.title, detail=exc.detail, path=request.url.path)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": f"https://api.eiraos.ai/errors/{exc.status_code}",
                "title": exc.title,
                "status": exc.status_code,
                "detail": exc.detail,
                "instance": request.url.path
            }
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        logger.warning("HTTP Exception", status_code=exc.status_code, detail=exc.detail, path=request.url.path)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": f"https://api.eiraos.ai/errors/{exc.status_code}",
                "title": "HTTP Error",
                "status": exc.status_code,
                "detail": str(exc.detail),
                "instance": request.url.path
            }
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        logger.warning("Rate limit exceeded", path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": "60"},
            content={
                "type": "https://api.eiraos.ai/errors/429",
                "title": "Too Many Requests",
                "status": 429,
                "detail": "Rate limit exceeded. Please retry after a short pause.",
                "instance": request.url.path
            }
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning("Validation Error", errors=exc.errors(), path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "type": "https://api.eiraos.ai/errors/422",
                "title": "Validation Error",
                "status": 422,
                "detail": "The request payload contains invalid fields.",
                "errors": exc.errors(),
                "instance": request.url.path
            }
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_exception_handler(request: Request, exc: SQLAlchemyError):
        logger.error("Database Error", error=str(exc), path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "type": "https://api.eiraos.ai/errors/500",
                "title": "Database Error",
                "status": 500,
                "detail": "An internal database error occurred while processing the request.",
                "instance": request.url.path
            }
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled Internal Exception", error=str(exc), path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "type": "https://api.eiraos.ai/errors/500",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "An unexpected internal server error occurred.",
                "instance": request.url.path
            }
        )
