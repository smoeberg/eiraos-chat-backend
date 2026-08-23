import re
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from eiraos.core.database import get_db
from eiraos.api.v1.auth import get_current_user, get_current_active_organization, require_permission
from eiraos.domains.agents.models import Bot

router = APIRouter(prefix="/bots", tags=["AI Bots & Agents"])


class BotCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    provider: str = "openai"
    model: str = "gpt-4o"
    description: Optional[str] = None
    bot_visibility: str = "organization"
    knowledge_visibility: str = "organization"
    is_public: bool = False

    @field_validator("is_public")
    @classmethod
    def _public_must_match_visibility(cls, is_public: bool, info):
        vis = info.data.get("bot_visibility", "organization")
        if is_public and vis != "public":
            raise ValueError("is_public=True requires bot_visibility='public'")
        if not is_public and vis == "public":
            raise ValueError("bot_visibility='public' requires is_public=True")
        return is_public

class BotResponseSchema(BaseModel):
    id: int
    organization_id: int
    title: str
    provider: str
    model: str
    description: Optional[str] = None
    bot_visibility: str
    is_public: bool
    created_at: str

    class Config:
        from_attributes = True

@router.post("", response_model=BotResponseSchema, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("bot:create"))])
async def create_bot(
    payload: BotCreateSchema,
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
    db: AsyncSession = Depends(get_db)
):
    bot = Bot(
        organization_id=org_id,
        title=payload.title,
        provider=payload.provider,
        model=payload.model,
        description=payload.description,
        bot_visibility=payload.bot_visibility,
        knowledge_visibility=payload.knowledge_visibility,
        is_public=payload.is_public
    )
    db.add(bot)
    await db.commit()
    await db.refresh(bot)
    return {
        "id": bot.id,
        "organization_id": bot.organization_id,
        "title": bot.title,
        "provider": bot.provider,
        "model": bot.model,
        "description": bot.description,
        "bot_visibility": bot.bot_visibility,
        "is_public": bot.is_public,
        "created_at": str(bot.created_at)
    }

@router.get("", response_model=List[BotResponseSchema], dependencies=[Depends(require_permission("bot:read"))])
async def list_bots(
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
    db: AsyncSession = Depends(get_db)
):
    # Public bots are reachable across orgs; private/org bots are scoped.
    stmt = select(Bot).where(
        (Bot.organization_id == org_id)
        | (Bot.is_public == True)
        | (Bot.bot_visibility == "public")
    )
    result = await db.execute(stmt)
    bots = result.scalars().all()
    return [{
        "id": b.id,
        "organization_id": b.organization_id,
        "title": b.title,
        "provider": b.provider,
        "model": b.model,
        "description": b.description,
        "bot_visibility": b.bot_visibility,
        "is_public": b.is_public,
        "created_at": str(b.created_at)
    } for b in bots]
