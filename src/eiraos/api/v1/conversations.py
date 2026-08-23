from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from eiraos.core.database import get_db
from eiraos.api.v1.auth import get_current_user, get_current_active_organization
from eiraos.domains.conversations.models import Conversation, Message

router = APIRouter(prefix="/conversations", tags=["Conversations & History"])

class ConversationCreate(BaseModel):
    title: str

class ConversationResponse(BaseModel):
    id: int
    user_id: int
    organization_id: int
    title: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True

class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    ai_marked: bool
    created_at: str

    class Config:
        from_attributes = True

@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
    db: AsyncSession = Depends(get_db)
):
    conv = Conversation(
        user_id=current_user["user_id"],
        organization_id=org_id,
        title=payload.title
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return {
        "id": conv.id,
        "user_id": conv.user_id,
        "organization_id": conv.organization_id,
        "title": conv.title,
        "created_at": str(conv.created_at),
        "updated_at": str(conv.updated_at)
    }

@router.get("", response_model=List[ConversationResponse])
async def list_conversations(
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(Conversation)
        .where(
            Conversation.organization_id == org_id,
            Conversation.user_id == current_user["user_id"]
        )
        .order_by(desc(Conversation.updated_at))
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    conversations = result.scalars().all()
    return [{
        "id": c.id,
        "user_id": c.user_id,
        "organization_id": c.organization_id,
        "title": c.title,
        "created_at": str(c.created_at),
        "updated_at": str(c.updated_at)
    } for c in conversations]

@router.get("/{conversation_id}/messages", response_model=List[MessageResponse])
async def get_conversation_messages(
    conversation_id: int,
    limit: int = Query(200, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
    db: AsyncSession = Depends(get_db)
):
    conv_res = await db.execute(select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.organization_id == org_id,
        Conversation.user_id == current_user["user_id"]
    ))
    conv = conv_res.scalars().first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg_stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    msg_res = await db.execute(msg_stmt)
    messages = msg_res.scalars().all()

    return [{
        "id": m.id,
        "conversation_id": m.conversation_id,
        "role": m.role,
        "content": m.content,
        "ai_marked": m.ai_marked,
        "created_at": str(m.created_at)
    } for m in messages]

@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
    db: AsyncSession = Depends(get_db)
):
    conv_res = await db.execute(select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.organization_id == org_id,
        Conversation.user_id == current_user["user_id"]
    ))
    conv = conv_res.scalars().first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await db.delete(conv)
    await db.commit()
    return None
