import structlog
import arq

from eiraos.core.database import async_session_maker
from eiraos.domains.documents.models import Document, DocumentChunk
from eiraos.domains.documents.rag_service import RAGService

logger = structlog.get_logger()


async def process_document_ingestion(ctx, document_id: int, organization_id: int, content: str):
    """
    Background worker task: chunks the document content and persists the chunks.

    Uses the same intelligent_chunking producer as the sync ingestion path, so
    embeddings/vector search operate on identical chunk boundaries.
    """
    logger.info("Starting document ingestion background task", document_id=document_id, org_id=organization_id)

    chunks = RAGService.intelligent_chunking(content, chunk_size=500, overlap=50)
    logger.info("document chunked", document_id=document_id, chunk_count=len(chunks))

    created = 0
    async with async_session_maker() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            logger.warning("worker document not found", document_id=document_id)
            return {"status": "not_found", "document_id": document_id}
        doc.status = "embedded"
        for position, chunk_text in enumerate(chunks):
            session.add(DocumentChunk(
                organization_id=organization_id,
                document_id=document_id,
                content=chunk_text,
                metadata_='{"order": %d}' % position,
            ))
            created += 1
        await session.commit()

    logger.info("document ingestion complete", document_id=document_id, chunks_persisted=created)
    return {"status": "success", "document_id": document_id, "chunks": created}


async def aggregate_ai_usage_metrics(ctx):
    """
    Placeholder cron job.

    There is currently no usage/ledger table in the schema to aggregate, so this
    is intentionally a no-op until a usage model is added. It exists to keep the
    arq schedule declarative; it never fabricates aggregate results.
    """
    logger.info("usage metrics aggregation skipped: no usage table wired yet")
    return {"status": "skipped", "reason": "no_usage_table"}


class WorkerSettings:
    functions = [process_document_ingestion]
    cron_jobs = [
        arq.cron(aggregate_ai_usage_metrics, minute={0, 30})  # Run every 30 mins
    ]
    redis_settings = arq.connections.RedisSettings(host="localhost", port=6379)
