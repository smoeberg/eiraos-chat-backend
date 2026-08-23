from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, text
from datetime import datetime
from eiraos.core.database import Base

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    organization_id = Column(Integer, nullable=False, index=True, server_default="1")
    title = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, nullable=False, index=True)
    role = Column(String, nullable=False) # user, assistant, system
    content = Column(Text, nullable=False)
    bot_id = Column(Integer, nullable=True)
    ai_marked = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))
