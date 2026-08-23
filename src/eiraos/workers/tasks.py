"""ARQ worker tasks — document ingestion lifecycle and cron jobs."""
from __future__ import annotations

import json
from urllib.parse import urlparse

import arq
import httpx
import structlog
from arq.connections import RedisSettings

from eiraos.core.config import settings
from eiraos.core.database import async_session_maker
from eiraos.domains.documents.models import Document, DocumentChunk
from eiraos.domains.documents.rag_service import RAGService

logger = structlog.get_logger()


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


async def _embed(text_content: str) -> list[float] | None:
    """Best-effort embedding; returns None if provider unavailable."""
    key = settings.OPENAI_API_KEY
    if not key or key in ("sk-placeholder", "replace-me"):
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={"model": "text-embedding-ada-002", "input": text_content},
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
    except Exception as e:
        logger.warning("worker_embed_failed", error_type=type(e).__name__)
        return None


async def process_document_ingestion(
    ctx, document_id: int, organization_id: int, content: str
):
    """Document lifecycle: queued -> processing -> ready | failed."""
    logger.info("document_ingestion_start", document_id=document_id, org_id=organization_id)

    async with async_session_maker() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            logger.warning("worker_document_not_found", document_id=document_id)
            return {"status": "not_found", "document_id": document_id}

        doc.status = "processing"
        await session.commit()

        try:
            chunks = RAGService.intelligent_chunking(content, chunk_size=500, overlap=50)
            created = 0
            embedded = 0
            for position, chunk_text in enumerate(chunks):
                emb = await _embed(chunk_text)
                meta = json.dumps({"order": position, "title": doc.title}, ensure_ascii=False)
                session.add(
                    DocumentChunk(
                        organization_id=organization_id,
                        document_id=document_id,
                        content=chunk_text,
                        embedding=emb,
                        metadata_=meta,
                    )
                )
                created += 1
                if emb is not None:
                    embedded += 1

            doc.status = "ready" if created > 0 else "failed"
            await session.commit()
            logger.info(
                "document_ingestion_complete",
                document_id=document_id,
                chunks=created,
                embedded=embedded,
                status=doc.status,
            )
            return {
                "status": doc.status,
                "document_id": document_id,
                "chunks": created,
                "embedded": embedded,
            }
        except Exception as e:
            logger.exception("document_ingestion_failed", document_id=document_id, error=str(e))
            doc.status = "failed"
            await session.commit()
            return {
                "status": "failed",
                "document_id": document_id,
                "error_type": type(e).__name__,
            }


async def aggregate_ai_usage_metrics(ctx):
    logger.info("usage_metrics_aggregation_skipped", reason="no_usage_table")
    return {"status": "skipped", "reason": "no_usage_table"}


class WorkerSettings:
    functions = [process_document_ingestion]
    cron_jobs = [
        arq.cron(aggregate_ai_usage_metrics, minute={0, 30}),
    ]
    redis_settings = _redis_settings()
