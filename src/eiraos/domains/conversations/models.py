from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey, ForeignKeyConstraint, UniqueConstraint, Index, text
from datetime import datetime
from eiraos.core.database import Base

class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_conversations_id_org"),
        ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_conversations_org"),
        ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["organization_members.user_id", "organization_members.organization_id"],
            name="fk_conversations_member",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    organization_id = Column(Integer, nullable=False, index=True)
    title = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))

class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("execution_id", "role", name="uq_messages_execution_role"),
        ForeignKeyConstraint(
            ["conversation_id", "organization_id"],
            ["conversations.id", "conversations.organization_id"],
            name="fk_messages_tenant_conversation",
        ),
        ForeignKeyConstraint(
            ["execution_id", "organization_id"],
            ["chat_executions.execution_id", "chat_executions.organization_id"],
            name="fk_messages_tenant_execution",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, nullable=False, index=True)
    organization_id = Column(Integer, nullable=False, index=True)
    execution_id = Column(String(64), ForeignKey("chat_executions.execution_id"), nullable=True, index=True)
    role = Column(String, nullable=False) # user, assistant, system
    content = Column(Text, nullable=False)
    bot_id = Column(Integer, nullable=True)
    status = Column(String, default="completed", nullable=False) # pending, streaming, completed, failed, cancelled
    ai_marked = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))


class ChatExecution(Base):
    """Durable ledger joining one request, its messages and accounting."""

    __tablename__ = "chat_executions"
    __table_args__ = (
        Index("ix_chat_executions_tenant_conversation", "organization_id", "conversation_id"),
        UniqueConstraint("execution_id", "organization_id", name="uq_chat_executions_execution_org"),
        UniqueConstraint("id", "organization_id", name="uq_chat_executions_id_org"),
        ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_chat_executions_org"),
        ForeignKeyConstraint(
            ["conversation_id", "organization_id"],
            ["conversations.id", "conversations.organization_id"],
            name="fk_chat_executions_tenant_conversation",
        ),
        ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["organization_members.user_id", "organization_members.organization_id"],
            name="fk_chat_executions_member",
        ),
        ForeignKeyConstraint(
            ["bot_id", "bot_organization_id"],
            ["bots.id", "bots.organization_id"],
            name="fk_chat_executions_bot_owner",
        ),
        ForeignKeyConstraint(
            ["idempotency_record_id", "organization_id", "user_id"],
            ["idempotency_records.id", "idempotency_records.organization_id", "idempotency_records.user_id"],
            name="fk_chat_executions_tenant_idempotency",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(String(64), nullable=False, unique=True, index=True)
    request_id = Column(String(128), nullable=False, index=True)
    conversation_id = Column(Integer, nullable=False, index=True)
    organization_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    bot_id = Column(Integer, nullable=False, index=True)
    bot_organization_id = Column(Integer, nullable=False, index=True)
    idempotency_record_id = Column(Integer, ForeignKey("idempotency_records.id", ondelete="SET NULL"),
                                   nullable=True, unique=True, index=True)
    user_message_id = Column(Integer, ForeignKey("messages.id"), nullable=True, unique=True)
    assistant_message_id = Column(Integer, ForeignKey("messages.id"), nullable=True, unique=True)
    provider = Column(String(64), nullable=False)
    model = Column(String(128), nullable=False)
    status = Column(String(16), nullable=False, default="prepared")
    attempt_count = Column(Integer, nullable=False, default=1)
    max_attempts = Column(Integer, nullable=False, default=3)
    last_failure_code = Column(String(32), nullable=True)
    failure_retryable = Column(Boolean, nullable=False, default=False)
    partial_response = Column(Boolean, nullable=False, default=False)
    recovered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
                        server_default=text("CURRENT_TIMESTAMP"))
    completed_at = Column(DateTime, nullable=True)
