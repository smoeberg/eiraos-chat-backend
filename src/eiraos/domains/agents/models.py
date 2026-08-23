from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, text
from datetime import datetime
from eiraos.core.database import Base

class Bot(Base):
    __tablename__ = "bots"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    provider = Column(String, nullable=False, default="openai")
    model = Column(String, nullable=False, default="gpt-4o")
    system_prompt = Column(Text, nullable=True)
    
    # Granular visibility & security scopes
    bot_visibility = Column(String, nullable=False, default="private") # private | organization | public
    knowledge_visibility = Column(String, nullable=False, default="organization") # private | organization | public
    credential_scope = Column(String, nullable=False, default="organization") # organization | platform
    tool_scope = Column(String, nullable=False, default="standard") # restricted | standard | elevated
    
    # Secret reference instead of raw plaintext key
    secret_reference = Column(String, nullable=True)
    is_public = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))
