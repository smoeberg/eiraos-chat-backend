from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, ForeignKeyConstraint,
    UniqueConstraint,
)
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from eiraos.core.database import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_documents_id_organization"),
    )

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(
        Integer,
        ForeignKey("organizations.id", name="fk_documents_organization", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title = Column(String, nullable=False)
    source = Column(String, nullable=True)
    mime_type = Column(String, nullable=True)
    status = Column(String, default="uploaded")
    owner = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "organization_id"],
            ["documents.id", "documents.organization_id"],
            name="fk_document_chunks_document_tenant",
            ondelete="CASCADE",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, index=True, nullable=False)
    document_id = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=True)
    metadata_ = Column("metadata", Text, nullable=True)  # JSON: visibility, order, title, ...
