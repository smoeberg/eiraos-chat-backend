from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from eiraos.core.database import get_db
from eiraos.domains.agents.models import Bot
from eiraos.api.v1.auth import get_current_user

router = APIRouter(prefix="/bots", tags=["AI Agents & Bots"])

class BotCreateSchema(BaseModel):
    bot_key: str = Field(..., description="Unique slug/key for the bot")
    provider: str = Field(default="openai", description="openai, anthropic, azure, etc.")
    name: str
    endpoint: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")
    api_key: Optional[str] = None
    system_prompt: Optional[str] = None
    is_public: bool = Field(default=True)

class BotResponseSchema(BaseModel):
    id: int
    bot_key: str
    provider: str
    name: str
    model: str
    is_public: bool

@router.post("", status_code=status.HTTP_201_CREATED, response_model=BotResponseSchema)
async def create_bot(
    payload: BotCreateSchema,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Register a new AI bot/agent configuration."""
    bot = Bot(
        bot_key=payload.bot_key,
        provider=payload.provider,
        name=payload.name,
        endpoint=payload.endpoint,
        model=payload.model,
        api_key=payload.api_key,
        system_prompt=payload.system_prompt,
        is_public=payload.is_public
    )
    db.add(bot)
    await db.commit()
    await db.refresh(bot)
    return {
        "id": bot.id,
        "bot_key": bot.bot_key,
        "provider": bot.provider,
        "name": bot.name,
        "model": bot.model,
        "is_public": bot.is_public
    }

@router.get("", response_model=List[BotResponseSchema])
async def list_bots(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List all available AI bots and agents."""
    stmt = select(Bot)
    result = await db.execute(stmt)
    bots = result.scalars().all()
    return [
        {
            "id": b.id,
            "bot_key": b.bot_key,
            "provider": b.provider,
            "name": b.name,
            "model": b.model,
            "is_public": b.is_public
        }
        for b in bots
    ]
