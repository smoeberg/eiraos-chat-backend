from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey, UniqueConstraint, text
from datetime import datetime
from eiraos.core.database import Base

class Bot(Base):
    __tablename__ = "bots"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_bots_id_org"),
    )

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id", name="fk_bots_org"), nullable=False, index=True,
    )
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
    # Secret reference instead of raw plaintext key
    secret_reference = Column(String, nullable=True)
    is_public = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))

    @classmethod
    def visibility(cls, bot: "Bot") -> str:
        """Single source of truth for bot visibility.

        Reconciles the legacy boolean `is_public` with the modern string
        `bot_visibility` so the two columns can never silently diverge.
        """
        if bot.is_public:
            return "public"
        return bot.bot_visibility or "private"
