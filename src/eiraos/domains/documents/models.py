from sqlalchemy import Column, Integer, String, Text, DateTime, text
from pgvector.sqlalchemy import VECTOR
from datetime import datetime
from eiraos.core.database import Base
from sqlalchemy.dialects.postgresql import JSONB

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, nullable=False, index=True)
    content = Column(Text, nullable=False)
    embedding = Column(VECTOR(1536), nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=True, default={})
    created_at = Column(DateTime, default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))
