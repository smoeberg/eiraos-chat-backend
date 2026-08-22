import pytest
from eiraos.domains.documents.services import RAGService

def test_intelligent_chunking():
    sample_text = "Paragraph 1: Introduction to EiraOS.\n\nParagraph 2: Architecture and Design.\n\nParagraph 3: Production Deployment."
    chunks = RAGService.intelligent_chunking(sample_text, max_chunk_size=100)
    assert len(chunks) > 0
    assert "EiraOS" in chunks[0]
