import structlog
import asyncio
import arq

logger = structlog.get_logger()

async def process_document_ingestion(ctx, document_id: int, organization_id: int, content: str):
    """
    Background worker task: splits large documents into chunks, 
    computes embeddings, and stores them in pgvector.
    """
    logger.info("Starting document ingestion background task", document_id=document_id, org_id=organization_id)
    
    # Simulate heavy embedding & chunking process
    await asyncio.sleep(2)
    
    logger.info("Document ingestion background task completed successfully", document_id=document_id)
    return {"status": "success", "document_id": document_id}

async def aggregate_ai_usage_metrics(ctx):
    """
    Background worker cron task: aggregates token usage and costs per tenant.
    """
    logger.info("Running scheduled AI usage metrics aggregation")
    await asyncio.sleep(1)
    return {"status": "aggregated"}

class WorkerSettings:
    functions = [process_document_ingestion]
    cron_jobs = [
        arq.cron(aggregate_ai_usage_metrics, minute={0, 30}) # Run every 30 mins
    ]
    redis_settings = arq.connections.RedisSettings(host="localhost", port=6379)
