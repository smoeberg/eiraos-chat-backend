"""RAG helpers: intelligent chunking and hybrid (vector + FTS) search."""
from __future__ import annotations

import re
from typing import List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


class RAGService:
    @staticmethod
    def intelligent_chunking(text_content: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
        paragraphs = re.split(r"\n\s*\n", text_content)
        chunks: list[str] = []
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
                if len(para) > chunk_size:
                    step = max(chunk_size - overlap, 1)
                    for i in range(0, len(para), step):
                        chunks.append(para[i : i + chunk_size])
                    current_chunk = ""
                else:
                    current_chunk = para
        if current_chunk:
            chunks.append(current_chunk)
        return chunks

    @staticmethod
    def _scope_clause(knowledge_scope: str) -> str:
        scope = (knowledge_scope or "organization").lower()
        if scope == "public":
            return """
              AND (
                metadata IS NULL
                OR (metadata::jsonb->>'visibility') IS NULL
                OR (metadata::jsonb->>'visibility') = 'public'
              )
            """
        if scope == "private":
            return """
              AND metadata IS NOT NULL
              AND (metadata::jsonb->>'visibility') = 'private'
            """
        if scope != "organization":
            return """
              AND metadata IS NOT NULL
              AND (metadata::jsonb->>'knowledge_scope') = :knowledge_scope
            """
        return ""

    @staticmethod
    async def hybrid_search(
        db: AsyncSession,
        organization_id: int,
        query_embedding: List[float],
        query_text: str,
        limit: int = 5,
        knowledge_scope: str = "organization",
    ) -> List[Dict[str, Any]]:
        """Hybrid retrieval with organization isolation and optional category scope."""
        embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"
        qtext = (query_text or "").strip()
        rrf_k = 60
        fetch_n = max(limit * 4, 20)
        scope_sql = RAGService._scope_clause(knowledge_scope)
        params = {
            "query_embedding": embedding_str,
            "org_id": organization_id,
            "lim": fetch_n,
            "knowledge_scope": knowledge_scope,
        }

        vector_sql = text(f"""
            SELECT id, organization_id, content, metadata,
                   (1 - (embedding <=> :query_embedding::vector)) AS vector_score
            FROM document_chunks
            WHERE organization_id = :org_id
            {scope_sql}
            ORDER BY embedding <=> :query_embedding::vector ASC
            LIMIT :lim
        """)
        vector_rows = (await db.execute(vector_sql, params)).fetchall()

        fts_rows = []
        if qtext:
            try:
                fts_sql = text(f"""
                    SELECT id, organization_id, content, metadata,
                           ts_rank(
                             to_tsvector('simple', coalesce(content, '')),
                             plainto_tsquery('simple', :qtext)
                           ) AS text_score
                    FROM document_chunks
                    WHERE organization_id = :org_id
                      AND to_tsvector('simple', coalesce(content, ''))
                          @@ plainto_tsquery('simple', :qtext)
                    {scope_sql}
                    ORDER BY text_score DESC
                    LIMIT :lim
                """)
                fts_params = dict(params)
                fts_params["qtext"] = qtext
                fts_rows = (await db.execute(fts_sql, fts_params)).fetchall()
            except Exception:
                fts_rows = []

        scores: dict[int, float] = {}
        docs: dict[int, Any] = {}
        for rank, row in enumerate(vector_rows):
            scores[row.id] = scores.get(row.id, 0.0) + 1.0 / (rrf_k + rank + 1)
            docs[row.id] = row
        for rank, row in enumerate(fts_rows):
            scores[row.id] = scores.get(row.id, 0.0) + 1.0 / (rrf_k + rank + 1)
            docs[row.id] = row

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
        return [
            {
                "id": row.id,
                "organization_id": row.organization_id,
                "content": row.content,
                "metadata": getattr(row, "metadata", None),
                "score": float(score),
            }
            for doc_id, score in ranked
            for row in [docs[doc_id]]
        ]
