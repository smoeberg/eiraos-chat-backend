"""F3-05 durable governance evidence service."""

import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eiraos.application.authorization import AuthorizationContext
from eiraos.application.provider_execution_policy import ProviderExecutionPermit
from eiraos.domains.governance.models import GovernanceDecisionRecord


POLICY_NAME = "provider_execution"
POLICY_VERSION = "f3-04-v1"


class GovernanceAuditUnavailable(RuntimeError):
    pass


def request_fingerprint(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def permit_fingerprint(permit: ProviderExecutionPermit) -> str:
    material = json.dumps(asdict(permit), sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(material).hexdigest()


class GovernanceAuditTrail:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def record_provider_decision(
        self,
        *,
        request_id: str,
        request_hash: str,
        authorization: AuthorizationContext,
        bot_id: int,
        bot_organization_id: int,
        allowed: bool,
        reason: str,
        provider: str | None,
        model: str | None,
        permit: ProviderExecutionPermit | None,
    ) -> str:
        decision_id = uuid.uuid4().hex
        record = GovernanceDecisionRecord(
            decision_id=decision_id,
            request_id=request_id,
            request_hash=request_hash,
            organization_id=authorization.organization_id,
            user_id=authorization.user_id,
            role=authorization.role,
            policy=POLICY_NAME,
            policy_version=POLICY_VERSION,
            capability="provider:execute",
            allowed=allowed,
            reason=reason,
            resource_type="bot",
            resource_id=str(bot_id),
            resource_organization_id=bot_organization_id,
            provider=provider,
            model=model,
            permit_fingerprint=permit_fingerprint(permit) if permit else None,
            result_status="denied" if not allowed else None,
            response_status=403 if not allowed else None,
            finalized_at=datetime.utcnow() if not allowed else None,
        )
        try:
            self._db.add(record)
            await self._db.commit()
        except Exception as exc:
            await self._db.rollback()
            raise GovernanceAuditUnavailable("governance decision could not be persisted") from exc
        return decision_id

    async def record_result(
        self,
        decision_id: str,
        *,
        result_status: str,
        response_status: int,
        failure_code: str | None = None,
    ) -> None:
        try:
            record = (
                await self._db.execute(
                    select(GovernanceDecisionRecord)
                    .where(GovernanceDecisionRecord.decision_id == decision_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if record is None or not record.allowed:
                await self._db.rollback()
                raise GovernanceAuditUnavailable("governance decision result binding is invalid")
            if record.finalized_at is not None:
                await self._db.rollback()
                return
            record.result_status = result_status
            record.response_status = response_status
            record.failure_code = failure_code
            record.finalized_at = datetime.utcnow()
            await self._db.commit()
        except GovernanceAuditUnavailable:
            raise
        except Exception as exc:
            await self._db.rollback()
            raise GovernanceAuditUnavailable("governance result could not be persisted") from exc

