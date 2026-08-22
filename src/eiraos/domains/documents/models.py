from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from pgvector.sqlalchemy import VECTOR
from eiraos.core.database import Base

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    source = Column(String(512), nullable=False)
    content = Column(Text, nullable=False)
    # OpenAI embedding dimension size is typically 1536 (text-embedding-3-small)
    embedding = Column(VECTOR(1536), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
