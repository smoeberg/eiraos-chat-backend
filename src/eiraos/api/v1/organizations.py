from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from eiraos.core.database import get_db
from eiraos.domains.organizations.models import Organization, OrganizationMember
from eiraos.api.v1.auth import get_current_user, require_permission

router = APIRouter(prefix="/organizations", tags=["Organizations & Multi-Tenancy"])

class OrganizationCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    slug: str

class OrganizationResponseSchema(BaseModel):
    id: int
    name: str
    slug: str

@router.post("", status_code=status.HTTP_201_CREATED, response_model=OrganizationResponseSchema)
async def create_organization(
    payload: OrganizationCreateSchema,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Create a new tenant organization and enroll the creator as owner."""
    org = Organization(name=payload.name, slug=payload.slug)
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(
        organization_id=org.id,
        user_id=current_user["user_id"],
        role="owner",
    ))
    await db.commit()
    await db.refresh(org)
    return {"id": org.id, "name": org.name, "slug": org.slug}

@router.get("", response_model=List[OrganizationResponseSchema], dependencies=[Depends(require_permission("organization:read"))])
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List the tenant organizations the current user belongs to."""
    stmt = (
        select(Organization)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(OrganizationMember.user_id == current_user["user_id"])
    )
    result = await db.execute(stmt)
    orgs = result.scalars().all()
    return [{"id": o.id, "name": o.name, "slug": o.slug} for o in orgs]
