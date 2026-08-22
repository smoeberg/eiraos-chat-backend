from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from eiraos.core.database import get_db
from eiraos.domains.conversations.models import Conversation, Message
from eiraos.api.v1.auth import get_current_user

router = APIRouter(prefix="/conversations", tags=["Conversations & History"])

class ConversationCreateSchema(BaseModel):
    title: str = Field(default="Ny Samtale")
    organization_id: int

class MessageCreateSchema(BaseModel):
    role: str = Field(..., description="user, assistant, or system")
    content: str
    bot_id: Optional[int] = None
    ai_marked: bool = Field(default=False, description="EU AI Act compliance marker")

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreateSchema,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Create a new chat conversation for the authenticated user."""
    conv = Conversation(
        user_id=1,
        organization_id=payload.organization_id,
        title=payload.title
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return {"id": conv.id, "title": conv.title, "created_at": conv.created_at}

@router.get("")
async def list_conversations(
    organization_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List all conversations for the tenant organization."""
    stmt = select(Conversation).where(Conversation.organization_id == organization_id).order_by(Conversation.updated_at.desc())
    result = await db.execute(stmt)
    conversations = result.scalars().all()
    return [{"id": c.id, "title": c.title, "created_at": c.created_at, "updated_at": c.updated_at} for c in conversations]

@router.post("/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
async def add_message_to_conversation(
    conversation_id: int,
    payload: MessageCreateSchema,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Append a message (user or assistant) to a conversation history."""
    conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
    conv_res = await db.execute(conv_stmt)
    conv = conv_res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg = Message(
        conversation_id=conversation_id,
        role=payload.role,
        content=payload.content,
        bot_id=payload.bot_id,
        ai_marked=payload.ai_marked
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return {"id": msg.id, "role": msg.role, "content": msg.content, "created_at": msg.created_at}

@router.get("/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Retrieve full message history for a specific conversation."""
    stmt = select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.asc())
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return [{"id": m.id, "role": m.role, "content": m.content, "bot_id": m.bot_id, "ai_marked": m.ai_marked, "created_at": m.created_at} for m in messages]
