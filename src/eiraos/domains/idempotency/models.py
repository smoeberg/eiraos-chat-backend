from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, text, UniqueConstraint, Index
from eiraos.core.database import Base


class IdempotencyRecord(Base):
    """Persistent atomic idempotency ledger with lease fencing."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "user_id", "key",
            name="uq_idempotency_org_user_key",
        ),
        UniqueConstraint(
            "id", "organization_id", "user_id",
            name="uq_idempotency_id_org_user",
        ),
        Index("ix_idempotency_expires_at", "expires_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    key = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default="processing")
    response_status = Column(Integer, nullable=True)
    response_reference = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    expires_at = Column(DateTime(timezone=True), nullable=True)
    lease_until = Column(DateTime(timezone=True), nullable=True)
    lease_token = Column(String(64), nullable=True)
