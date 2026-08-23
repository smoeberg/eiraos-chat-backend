from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from eiraos.core.database import get_db
from eiraos.api.v1.auth import get_current_user, get_current_active_organization
from eiraos.domains.documents.models import DocumentChunk
from eiraos.domains.documents.rag_service import RAGService
from eiraos.core.config import settings
import httpx

router = APIRouter(prefix="/documents", tags=["RAG & Documents"])

class DocumentIngestRequest(BaseModel):
    title: str
    content: str
    metadata: Optional[Dict[str, Any]] = None

class DocumentSearchRequest(BaseModel):
    query: str
    limit: int = 5

async def generate_embedding(text_content: str) -> List[float]:
    """Helper to generate text embedding via OpenAI API."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "text-embedding-ada-002", "input": text_content}
        )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]

@router.post("/ingest", status_code=status.HTTP_201_CREATED)
async def ingest_document(
    payload: DocumentIngestRequest,
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
    db: AsyncSession = Depends(get_db)
):
    """
    Ingest document, perform intelligent chunking, compute embeddings, and store in pgvector.
    """
    chunks = RAGService.intelligent_chunking(payload.content)
    stored_count = 0

    for chunk_text in chunks:
        try:
            embedding = await generate_embedding(chunk_text)
            chunk_db = DocumentChunk(
                organization_id=org_id,
                content=chunk_text,
                embedding=embedding,
                metadata={"title": payload.title, **(payload.metadata or {})}
            )
            db.add(chunk_db)
            stored_count += 1
        except Exception as e:
            # If embedding generation fails for a chunk, continue or log error
            continue

    await db.commit()
    return {"status": "success", "chunks_stored": stored_count, "title": payload.title}

@router.post("/search")
async def search_documents(
    payload: DocumentSearchRequest,
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
    db: AsyncSession = Depends(get_db)
):
    """
    Perform hybrid vector semantic search within the tenant's organization scope.
    """
    try:
        query_embedding = await generate_embedding(payload.query)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to generate query embedding: {str(e)}")

    results = await RAGService.hybrid_search(
        db=db,
        organization_id=org_id,
        query_embedding=query_embedding,
        query_text=payload.query,
        limit=payload.limit
    )

    return {"query": payload.query, "results": results}
