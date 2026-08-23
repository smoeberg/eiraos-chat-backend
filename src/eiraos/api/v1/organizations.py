from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from eiraos.core.database import get_db
from eiraos.domains.organizations.models import Organization, OrganizationMember
from eiraos.api.v1.auth import get_current_user

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
    """Create a new tenant organization."""
    org = Organization(name=payload.name, slug=payload.slug)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return {"id": org.id, "name": org.name, "slug": org.slug}

@router.get("", response_model=List[OrganizationResponseSchema])
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List tenant organizations."""
    stmt = select(Organization)
    result = await db.execute(stmt)
    orgs = result.scalars().all()
    return [{"id": o.id, "name": o.name, "slug": o.slug} for o in orgs]
