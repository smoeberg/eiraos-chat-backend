"""ARQ worker tasks — document ingestion lifecycle and cron jobs."""
from __future__ import annotations

import json
import arq
import httpx
import structlog
from arq.connections import RedisSettings
from sqlalchemy import select

from eiraos.core.config import settings
from eiraos.core.database import async_session_maker
from eiraos.domains.documents.models import Document, DocumentChunk
from eiraos.domains.documents.rag_service import RAGService
from eiraos.workers.redis_config import redis_settings_from_url

logger = structlog.get_logger()


def _redis_settings() -> RedisSettings:
    return redis_settings_from_url(settings.REDIS_URL)


async def _embed(text_content: str) -> list[float] | None:
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
    except Exception:
        logger.warning("worker_embed_failed", error_type="provider_error")
        return None


async def process_document_ingestion(
    ctx, document_id: int, organization_id: int, content: str,
    knowledge_scope: str = "organization",
):
    """Document lifecycle: queued -> processing -> ready | failed."""
    logger.info("document_ingestion_start", document_id=document_id, org_id=organization_id)
    async with async_session_maker() as session:
        doc = (await session.execute(
            select(Document).where(
                Document.id == document_id,
                Document.organization_id == organization_id,
            ).with_for_update()
        )).scalar_one_or_none()
        if doc is None:
            logger.warning(
                "worker_document_not_found_or_tenant_mismatch",
                document_id=document_id,
                org_id=organization_id,
            )
            return {"status": "not_found", "document_id": document_id}
        if doc.status == "ready":
            logger.info(
                "document_ingestion_already_ready",
                document_id=document_id,
                org_id=organization_id,
            )
            return {"status": "ready", "document_id": document_id, "replayed": True}
        doc.status = "processing"
        await session.commit()
        try:
            chunks = RAGService.intelligent_chunking(content, chunk_size=500, overlap=50)
            created = 0
            embedded = 0
            for position, chunk_text in enumerate(chunks):
                emb = await _embed(chunk_text)
                meta = json.dumps({
                    "order": position,
                    "title": doc.title,
                    "knowledge_scope": knowledge_scope,
                }, ensure_ascii=False)
                session.add(DocumentChunk(
                    organization_id=organization_id,
                    document_id=document_id,
                    content=chunk_text,
                    embedding=emb,
                    metadata_=meta,
                ))
                created += 1
                if emb is not None:
                    embedded += 1
            doc.status = "ready" if created > 0 else "failed"
            await session.commit()
            return {"status": doc.status, "document_id": document_id, "chunks": created, "embedded": embedded}
        except Exception as e:
            logger.exception("document_ingestion_failed", document_id=document_id, error_type=type(e).__name__)
            doc.status = "failed"
            await session.commit()
            return {"status": "failed", "document_id": document_id, "error_type": type(e).__name__}


async def cleanup_expired_idempotency(ctx):
    from eiraos.core.idempotency import cleanup_expired_records
    async with async_session_maker() as session:
        deleted = await cleanup_expired_records(session, limit=2000)
    logger.info("idempotency_cleanup", deleted=deleted)
    return {"status": "ok", "deleted": deleted}


async def aggregate_ai_usage_metrics(ctx):
    logger.info("usage_metrics_aggregation_skipped", reason="no_usage_table")
    return {"status": "skipped", "reason": "no_usage_table"}


class WorkerSettings:
    functions = [process_document_ingestion, cleanup_expired_idempotency]
    cron_jobs = [
        arq.cron(aggregate_ai_usage_metrics, minute={0, 30}),
        arq.cron(cleanup_expired_idempotency, minute={15}),
    ]
    redis_settings = _redis_settings()
