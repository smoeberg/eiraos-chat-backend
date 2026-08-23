import pytest
from eiraos.domains.documents.rag_service import RAGService


def test_intelligent_chunking():
    sample_text = (
        "Paragraph 1: Introduction to EiraOS.\n\n"
        "Paragraph 2: Architecture and Design.\n\n"
        "Paragraph 3: Production Deployment."
    )
    chunks = RAGService.intelligent_chunking(sample_text, chunk_size=100)
    assert len(chunks) > 0
    assert "EiraOS" in chunks[0]
