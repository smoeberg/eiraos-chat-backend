from typing import List, Optional, Dict, Any
import json
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from eiraos.core.database import get_db
from eiraos.api.v1.auth import get_current_user, get_current_active_organization
from eiraos.domains.documents.models import DocumentChunk
from eiraos.domains.documents.rag_service import RAGService
from eiraos.core.config import settings
from eiraos.core import idempotency
from eiraos.core.exceptions import EiraOSException
import httpx

logger = structlog.get_logger()

router = APIRouter(prefix="/documents", tags=["RAG & Documents"])

# Hardening (Sprint 4): bounded payloads so RAG pipeline can't be abused by
# unbounded content/uploads or runaway query/result sizes.
MAX_DOCUMENT_CHARS = 200_000
MAX_TITLE_CHARS = 500
MAX_SEARCH_QUERY_CHARS = 2_000
MAX_SEARCH_LIMIT = 50


class DocumentIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(..., min_length=1, max_length=MAX_TITLE_CHARS)
    content: str = Field(..., min_length=1, max_length=MAX_DOCUMENT_CHARS)
    metadata: Optional[Dict[str, Any]] = None


class DocumentSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=MAX_SEARCH_QUERY_CHARS)
    limit: int = Field(default=5, ge=1, le=MAX_SEARCH_LIMIT)


async def generate_embedding(text_content: str) -> List[float]:
    """Returns an embedding vector; never surfaces upstream internals to callers."""
    if (
        not settings.OPENAI_API_KEY
        or settings.OPENAI_API_KEY == "sk-placeholder"
        or settings.OPENAI_API_KEY == "replace-me"
    ):
        raise EiraOSException(
            title="Embedding not configured",
            detail="The embedding provider is not configured on this deployment.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"model": "text-embedding-ada-002", "input": text_content},
            )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]
    except (httpx.HTTPError, KeyError, ValueError):
        # Do not leak upstream body/details/exception text to the client.
        raise EiraOSException(
            title="Embedding failed",
            detail="The embedding provider could not process this request.",
            status_code=status.HTTP_502_BAD_GATEWAY,
        )


@router.post("/ingest", status_code=status.HTTP_201_CREATED)
async def ingest_document(
    payload: DocumentIngestRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
    db: AsyncSession = Depends(get_db),
):
    # Idempotency: a client retrying the same ingest with the same key is not
    # re-embedded (prevents duplicate chunks + avoidable provider cost).
    idem_key = idempotency.enforce_idempotency(request)
    try:
        outcome = await idempotency.begin_idempotency(
            db, request, f"doc:ingest:{idem_key}"
        )
    except HTTPException:
        raise
    if outcome == "completed":
        return {"status": "duplicate", "chunks_stored": 0, "title": payload.title}

    chunks = RAGService.intelligent_chunking(payload.content)
    stored_count = 0
    failed_count = 0

    for chunk_text in chunks:
        try:
            embedding = await generate_embedding(chunk_text)
        except EiraOSException:
            failed_count += 1
            logger.warning("embedding_chunk_rejected", org_id=org_id)
            continue
        except Exception as e:  # noqa: BLE001 - isolate per-chunk surprises
            failed_count += 1
            logger.warning(
                "embedding_chunk_unexpected",
                org_id=org_id,
                error_type=type(e).__name__,
            )
            continue

        chunk_db = DocumentChunk(
            organization_id=org_id,
            content=chunk_text,
            embedding=embedding,
            metadata_={"title": payload.title, **(payload.metadata or {})},
        )
        db.add(chunk_db)
        stored_count += 1

    await db.commit()
    await idempotency.complete_idempotency(
        db,
        request,
        f"doc:ingest:{idem_key}",
        status.HTTP_201_CREATED,
        json.dumps({"stored": stored_count, "failed": failed_count}),
    )

    if chunks and stored_count == 0:
        # All chunks failed to embed: don't report a hollow success.
        raise EiraOSException(
            title="Document indexing failed",
            detail="No chunks could be embedded by the provider.",
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    return {
        "status": "success" if failed_count == 0 else "partial",
        "chunks_stored": stored_count,
        "chunks_failed": failed_count,
        "title": payload.title,
    }


@router.post("/search")
async def search_documents(
    payload: DocumentSearchRequest,
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
    db: AsyncSession = Depends(get_db),
):
    try:
        query_embedding = await generate_embedding(payload.query)
    except EiraOSException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    results = await RAGService.hybrid_search(
        db=db,
        organization_id=org_id,
        query_embedding=query_embedding,
        query_text=payload.query,
        limit=payload.limit,
    )
    return {"query": payload.query, "results": results}
