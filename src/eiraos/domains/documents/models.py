from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from eiraos.core.database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, index=True, nullable=False)
    title = Column(String, nullable=False)
    source = Column(String, nullable=True)
    mime_type = Column(String, nullable=True)
    status = Column(String, default="uploaded")
    owner = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, index=True, nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=True)
    metadata_ = Column("metadata", Text, nullable=True)  # JSON: visibility, order, title, ...
