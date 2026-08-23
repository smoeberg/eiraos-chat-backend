"""RAG document ingest (async job) and hybrid search."""
from __future__ import annotations

from typing import List, Optional, Dict, Any
import json

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog
import httpx

from eiraos.core.database import get_db
from eiraos.api.v1.auth import (
    get_current_user,
    get_current_active_organization,
    require_permission,
)
from eiraos.domains.documents.models import Document, DocumentChunk
from eiraos.domains.documents.rag_service import RAGService
from eiraos.core.config import settings
from eiraos.core import idempotency
from eiraos.core.exceptions import EiraOSException
from eiraos.workers.client import enqueue_document_ingestion

logger = structlog.get_logger()

router = APIRouter(prefix="/documents", tags=["RAG & Documents"])

MAX_DOCUMENT_CHARS = 200_000
MAX_TITLE_CHARS = 500
MAX_SEARCH_QUERY_CHARS = 2_000
MAX_SEARCH_LIMIT = 50


class DocumentIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(..., min_length=1, max_length=MAX_TITLE_CHARS)
    content: str = Field(..., min_length=1, max_length=MAX_DOCUMENT_CHARS)
    metadata: Optional[Dict[str, Any]] = None
    allow_sync_fallback: bool = False


class DocumentSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(..., min_length=1, max_length=MAX_SEARCH_QUERY_CHARS)
    limit: int = Field(default=5, ge=1, le=MAX_SEARCH_LIMIT)


class DocumentStatusResponse(BaseModel):
    id: int
    title: str
    status: str
    organization_id: int


async def generate_embedding(text_content: str) -> List[float]:
    if (
        not settings.OPENAI_API_KEY
        or settings.OPENAI_API_KEY in ("sk-placeholder", "replace-me")
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
        return response.json()["data"][0]["embedding"]
    except (httpx.HTTPError, KeyError, ValueError):
        raise EiraOSException(
            title="Embedding failed",
            detail="The embedding provider could not process this request.",
            status_code=status.HTTP_502_BAD_GATEWAY,
        )


@router.post(
    "/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permission("document:upload"))],
)
async def ingest_document(
    payload: DocumentIngestRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
    db: AsyncSession = Depends(get_db),
):
    """Accept document, persist Document(status=queued), enqueue ARQ job."""
    raw_key = request.headers.get("Idempotency-Key") or ""
    idem_key = raw_key.strip() or None
    ledger_key = f"doc:ingest:{idem_key}" if idem_key else None

    lease_token = None
    if ledger_key:
        outcome = await idempotency.begin_idempotency(db, request, ledger_key)
        if outcome.status == "completed" or outcome == "completed":
            cached = await idempotency.read_cached_response(db, request, ledger_key)
            if cached:
                try:
                    return json.loads(cached)
                except json.JSONDecodeError:
                    pass
            return {"status": "duplicate", "document_id": None, "title": payload.title}
        lease_token = outcome.lease_token

    doc = Document(
        organization_id=org_id,
        title=payload.title,
        source=(payload.metadata or {}).get("source", "api"),
        mime_type=(payload.metadata or {}).get("mime_type", "text/plain"),
        status="queued",
        owner=current_user["user_id"],
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    job_id = await enqueue_document_ingestion(
        document_id=doc.id,
        organization_id=org_id,
        content=payload.content,
    )

    if job_id is None and payload.allow_sync_fallback:
        doc.status = "processing"
        await db.commit()
        chunks = RAGService.intelligent_chunking(payload.content)
        stored = 0
        for i, chunk_text in enumerate(chunks):
            try:
                emb = await generate_embedding(chunk_text)
            except Exception:
                emb = None
            db.add(
                DocumentChunk(
                    organization_id=org_id,
                    document_id=doc.id,
                    content=chunk_text,
                    embedding=emb,
                    metadata_=json.dumps(
                        {"order": i, "title": payload.title}, ensure_ascii=False
                    ),
                )
            )
            stored += 1
        doc.status = "ready" if stored else "failed"
        await db.commit()
        body = {
            "status": doc.status,
            "document_id": doc.id,
            "job_id": None,
            "mode": "sync_fallback",
            "chunks_stored": stored,
            "title": payload.title,
        }
    elif job_id is None:
        doc.status = "failed"
        await db.commit()
        raise EiraOSException(
            title="Job queue unavailable",
            detail="Document was accepted but the background worker queue is unreachable.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    else:
        body = {
            "status": "queued",
            "document_id": doc.id,
            "job_id": job_id,
            "mode": "async",
            "title": payload.title,
        }

    if ledger_key:
        await idempotency.complete_idempotency(
            db,
            request,
            ledger_key,
            status.HTTP_202_ACCEPTED,
            json.dumps(body),
            lease_token=lease_token,
        )
    return body


@router.get(
    "/{document_id}",
    response_model=DocumentStatusResponse,
    dependencies=[Depends(require_permission("document:read"))],
)
async def get_document_status(
    document_id: int,
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
    db: AsyncSession = Depends(get_db),
):
    doc = (
        await db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.organization_id == org_id,
            )
        )
    ).scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": doc.id,
        "title": doc.title,
        "status": doc.status,
        "organization_id": doc.organization_id,
    }


@router.post(
    "/search",
    dependencies=[Depends(require_permission("document:read"))],
)
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
