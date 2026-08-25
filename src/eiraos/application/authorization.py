"""F3-02 application authorization boundary."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eiraos.domains.governance.capabilities import (
    Capability,
    CapabilityDecision,
    Principal,
    PrincipalType,
    decide_role_capability,
)
from eiraos.domains.organizations.models import OrganizationMember


class AuthorizationDenied(Exception):
    """A fail-closed authorization rejection with a stable reason code."""

    def __init__(self, reason: str, capability: Capability | str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.capability = capability


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    user: Principal
    organization: Principal
    role: str
    decision: CapabilityDecision

    @property
    def user_id(self) -> int:
        return int(self.user.identifier)

    @property
    def organization_id(self) -> int:
        return self.organization.organization_id


class AuthorizationBoundary:
    """Resolve current membership and make one capability decision.

    JWT claims identify the requested user/tenant context, but never provide
    role authority. The current database membership is authoritative.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def authorize(
        self,
        *,
        identity: dict,
        capability: Capability | str,
        resource_organization_id: int | None = None,
    ) -> AuthorizationContext:
        user_id = identity.get("user_id")
        organization_id = identity.get("organization_id")
        if not isinstance(user_id, int) or user_id <= 0:
            raise AuthorizationDenied("invalid_identity", capability)
        if not isinstance(organization_id, int) or organization_id <= 0:
            raise AuthorizationDenied("invalid_tenant", capability)

        membership = (
            await self._db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.user_id == user_id,
                    OrganizationMember.organization_id == organization_id,
                )
            )
        ).scalars().first()
        if membership is None:
            raise AuthorizationDenied("membership_not_found", capability)

        resource_org = organization_id if resource_organization_id is None else resource_organization_id
        decision = decide_role_capability(
            role=membership.role or "",
            capability=capability,
            principal_organization_id=organization_id,
            resource_organization_id=resource_org,
        )
        if not decision.allowed:
            raise AuthorizationDenied(decision.reason, decision.capability)

        return AuthorizationContext(
            user=Principal(PrincipalType.USER, str(user_id), organization_id),
            organization=Principal(PrincipalType.ORGANIZATION, str(organization_id), organization_id),
            role=(membership.role or "").strip().lower(),
            decision=decision,
        )
