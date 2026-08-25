from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, text

from eiraos.core.database import Base


class MemoryRecord(Base):
    __tablename__ = "memory_records"
    __table_args__ = (
        CheckConstraint(
            "memory_class IN ('persistent_memory', 'user_org_knowledge')",
            name="ck_memory_records_durable_class",
        ),
        CheckConstraint(
            "(scope_kind = 'user' AND owner_user_id IS NOT NULL) OR "
            "(scope_kind = 'organization' AND owner_user_id IS NULL)",
            name="ck_memory_records_scope_owner",
        ),
        ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_memory_records_org"),
        ForeignKeyConstraint(
            ["actor_user_id", "organization_id"],
            ["organization_members.user_id", "organization_members.organization_id"],
            name="fk_memory_records_actor_member",
        ),
        ForeignKeyConstraint(
            ["owner_user_id", "organization_id"],
            ["organization_members.user_id", "organization_members.organization_id"],
            name="fk_memory_records_owner_member",
        ),
        Index("ix_memory_records_tenant_scope", "organization_id", "scope_kind", "owner_user_id"),
    )

    id = Column(Integer, primary_key=True)
    item_id = Column(String(64), nullable=False, unique=True, index=True)
    organization_id = Column(Integer, nullable=False, index=True)
    owner_user_id = Column(Integer, nullable=True, index=True)
    actor_user_id = Column(Integer, nullable=False)
    memory_class = Column(String(32), nullable=False)
    scope_kind = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    provenance_json = Column(Text, nullable=False)
    source_message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    source_memory_item_id = Column(String(64), ForeignKey("memory_records.item_id"), nullable=True)
    reason = Column(String(500), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))
    deleted_at = Column(DateTime, nullable=True)