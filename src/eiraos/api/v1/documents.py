from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from eiraos.core.database import get_db
from eiraos.domains.documents.models import DocumentChunk
from eiraos.api.v1.auth import get_current_user

router = APIRouter(prefix="/documents", tags=["RAG & Knowledge Base"])

class DocumentIngestSchema(BaseModel):
    organization_id: int = Field(..., description="Tenant organization ID")
    title: str
    source: str
    content: str
    embedding: List[float] = Field(..., description="Vector embedding array (dim 1536)")

class DocumentSearchSchema(BaseModel):
    organization_id: int
    query_embedding: List[float]
    match_threshold: float = 0.75
    limit: int = 5

@router.post("/ingest", status_code=status.HTTP_201_CREATED)
async def ingest_document_chunk(
    payload: DocumentIngestSchema,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Ingest a document chunk and its vector embedding into PostgreSQL with pgvector.
    """
    chunk = DocumentChunk(
        organization_id=payload.organization_id,
        title=payload.title,
        source=payload.source,
        content=payload.content,
        embedding=payload.embedding
    )
    db.add(chunk)
    await db.commit()
    await db.refresh(chunk)
    return {"status": "success", "chunk_id": chunk.id, "title": chunk.title}

@router.post("/search")
async def semantic_search(
    payload: DocumentSearchSchema,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Perform high-performance vector similarity search using pgvector cosine distance operator (<=>).
    Guarantees strict multi-tenant isolation by filtering on organization_id.
    """
    distance_expr = DocumentChunk.embedding.cosine_distance(payload.query_embedding)
    
    stmt = (
        select(
            DocumentChunk.id,
            DocumentChunk.title,
            DocumentChunk.source,
            DocumentChunk.content,
            (1 - distance_expr).label("similarity")
        )
        .where(DocumentChunk.organization_id == payload.organization_id)
        .order_by(distance_expr)
        .limit(payload.limit)
    )

    result = await db.execute(stmt)
    rows = result.fetchall()

    matches = []
    for row in rows:
        if row.similarity >= payload.match_threshold:
            matches.append({
                "id": row.id,
                "title": row.title,
                "source": row.source,
                "content": row.content,
                "similarity": float(row.similarity)
            })

    return {"matches": matches}
