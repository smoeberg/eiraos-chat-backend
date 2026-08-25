"""ARQ job queue client — Redis settings from application config."""
from __future__ import annotations

from urllib.parse import urlparse

from arq import create_pool
from arq.connections import RedisSettings, ArqRedis
import structlog

from eiraos.core.config import settings

logger = structlog.get_logger()

_pool: ArqRedis | None = None


def _redis_settings() -> RedisSettings:
    url = (settings.REDIS_URL or "").strip()
    if not url:
        return RedisSettings(host="localhost", port=6379)
    parsed = urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int((parsed.path or "/0").lstrip("/") or 0),
        password=parsed.password,
    )


async def get_arq_pool() -> ArqRedis | None:
    """Return a shared ARQ Redis pool, or None if Redis is unavailable."""
    global _pool
    if _pool is not None:
        return _pool
    try:
        _pool = await create_pool(_redis_settings())
        return _pool
    except Exception as e:
        logger.error("Failed to connect to Redis for background jobs", error=str(e))
        return None


async def enqueue_document_ingestion(
    document_id: int,
    organization_id: int,
    content: str,
    knowledge_scope: str = "organization",
) -> str | None:
    """Enqueue document processing. Returns job id or None if queue unavailable."""
    pool = await get_arq_pool()
    if pool is None:
        return None
    job = await pool.enqueue_job(
        "process_document_ingestion",
        document_id,
        organization_id,
        content,
        knowledge_scope,
        _job_id=f"document-ingest:{organization_id}:{document_id}",
    )
    return job.job_id if job else None
