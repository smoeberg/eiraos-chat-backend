from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from eiraos.core.database import Base


class ProviderUsageRecord(Base):
    """Durable, non-secret accounting record for one provider execution."""

    __tablename__ = "provider_usage_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["chat_execution_id", "organization_id"],
            ["chat_executions.id", "chat_executions.organization_id"],
            name="fk_provider_usage_tenant_execution",
        ),
        UniqueConstraint(
            "chat_execution_id", "attempt", "operation", "usage_source",
            name="uq_provider_usage_execution_attempt_operation_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    execution_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    chat_execution_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("chat_executions.id"), nullable=True, index=True,
    )
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    organization_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False, default="reservation")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    usage_source: Mapped[str] = mapped_column(String(32), nullable=False, default="reservation")
    pricing_revision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False, default=0)
    actual_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    verification: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
