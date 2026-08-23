from sqlalchemy import Column, Integer, String, DateTime, Text, Float, text
from pgvector.sqlalchemy import Vector
from datetime import datetime
from eiraos.core.database import Base

class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, nullable=False, index=True)
    title = Column(String, nullable=False)
    source = Column(String, nullable=False)
    mime_type = Column(String, nullable=False, default="text/plain")
    status = Column(String, nullable=False, default="uploaded") # uploaded | processing | embedded | ready | failed | deleted
    last_modified = Column(DateTime, default=datetime.utcnow)
    owner = Column(Integer, nullable=False)
    project = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, nullable=False, index=True)
    document_id = Column(Integer, nullable=False, index=True)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=True)
    metadata_ = Column(Text, nullable=True) # JSON serialized metadata
    created_at = Column(DateTime, default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))
