from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, text
from datetime import datetime
from eiraos.core.database import Base

class Bot(Base):
    __tablename__ = "bots"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, nullable=False, index=True, server_default="1")
    name = Column(String, nullable=False)
    provider = Column(String, nullable=False, default="openai")
    model = Column(String, nullable=False, default="gpt-4o")
    description = Column(Text, nullable=True)
    api_key = Column(String, nullable=True)
    is_public = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))
