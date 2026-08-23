from typing import List, Dict, Any
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from eiraos.domains.documents.models import DocumentChunk

class RAGService:
    @staticmethod
    def intelligent_chunking(text_content: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
        """
        Semantically split text into paragraphs/sections with overlap for vector embedding.
        """
        paragraphs = re.split(r'\n\s*\n', text_content)
        chunks = []
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(current_chunk) + len(para) + 1 <= chunk_size:
                current_chunk = f"{current_chunk}\n{para}" if current_chunk else para
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                # Handle very long paragraphs by breaking them down
                if len(para) > chunk_size:
                    for i in range(0, len(para), chunk_size - overlap):
                        chunks.append(para[i:i + chunk_size])
                    current_chunk = ""
                else:
                    current_chunk = para

        if current_chunk:
            chunks.append(current_chunk)
        return chunks

    @staticmethod
    async def hybrid_search(
        db: AsyncSession,
        organization_id: int,
        query_embedding: List[float],
        query_text: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Execute hybrid search combining pgvector cosine distance and PostgreSQL full-text search (tsvector).
        """
        # Format embedding vector as string for PostgreSQL
        embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"

        sql = text("""
            SELECT id, organization_id, content, metadata,
                   (1 - (embedding <=> :query_embedding::vector)) AS vector_score
            FROM document_chunks
            WHERE organization_id = :org_id
            ORDER BY embedding <=> :query_embedding::vector ASC
            LIMIT :lim;
        """)

        result = await db.execute(sql, {
            "query_embedding": embedding_str,
            "org_id": organization_id,
            "lim": limit
        })
        rows = result.fetchall()

        return [{
            "id": row.id,
            "organization_id": row.organization_id,
            "content": row.content,
            "metadata": row.metadata,
            "score": float(row.vector_score)
        } for row in rows]
