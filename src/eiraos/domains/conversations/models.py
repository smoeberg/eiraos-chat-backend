from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey, UniqueConstraint, Index, text
from datetime import datetime
from eiraos.core.database import Base

class Conversation(Base):
    __tablename__ = "conversations"

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
    )

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, nullable=False, index=True)
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
    )

    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(String(64), nullable=False, unique=True, index=True)
    request_id = Column(String(128), nullable=False, index=True)
    conversation_id = Column(Integer, nullable=False, index=True)
    organization_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    bot_id = Column(Integer, nullable=False, index=True)
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
