from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from eiraos.core.database import get_db
from eiraos.api.v1.auth import get_current_user, get_current_active_organization
from eiraos.application.providers.factory import AIProviderFactory
from eiraos.domains.bots.models import Bot
from eiraos.domains.conversations.models import Conversation, Message
from eiraos.core.config import settings

router = APIRouter(prefix="/chat", tags=["AI Chat & Completions"])

class ChatMessage(BaseModel):
    role: str = Field(..., description="user, assistant, or system")
    content: str

class ChatCompletionRequest(BaseModel):
    conversation_id: Optional[int] = None
    bot_id: Optional[int] = None
    messages: List[ChatMessage]
    stream: bool = True
    temperature: float = 0.7
    max_tokens: int = 1000

@router.post("/completions")
async def create_chat_completion(
    payload: ChatCompletionRequest,
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
    db: AsyncSession = Depends(get_db)
):
    """
    Execute AI chat completion or SSE stream, persisting messages and utilizing bot configuration.
    """
    model = "gpt-4o"
    provider_name = "openai"
    api_key = settings.OPENAI_API_KEY
    system_prompt = "You are EiraOS, a helpful, secure enterprise AI assistant."

    if payload.bot_id:
        bot_res = await db.execute(select(Bot).where(Bot.id == payload.bot_id))
        bot = bot_res.scalars().first()
        if bot:
            model = bot.model
            provider_name = bot.provider.lower()
            if bot.api_key:
                api_key = bot.api_key
            if bot.description:
                system_prompt = bot.description

    conversation_id = payload.conversation_id
    if conversation_id:
        conv_res = await db.execute(select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user["user_id"]
        ))
        conv = conv_res.scalars().first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found or access denied")
    else:
        title_summary = payload.messages[-1].content[:30] if payload.messages else "New Chat"
        conv = Conversation(
            user_id=current_user["user_id"],
            title=title_summary
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
        conversation_id = conv.id

    if payload.messages:
        last_msg = payload.messages[-1]
        if last_msg.role == "user":
            user_msg_db = Message(
                conversation_id=conversation_id,
                role="user",
                content=last_msg.content,
                bot_id=payload.bot_id,
                ai_marked=False
            )
            db.add(user_msg_db)
            await db.commit()

    try:
        provider = AIProviderFactory.get_provider(provider_name, api_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    formatted_messages = [{"role": m.role, "content": m.content} for m in payload.messages]

    if not payload.stream:
        try:
            ai_response_text = await provider.generate_chat_completion(
                messages=formatted_messages,
                model=model,
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
                system_prompt=system_prompt
            )
            
            assistant_msg_db = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=ai_response_text,
                bot_id=payload.bot_id,
                ai_marked=True
            )
            db.add(assistant_msg_db)
            await db.commit()

            return {"conversation_id": conversation_id, "content": ai_response_text, "role": "assistant"}
        except Exception as ex:
            raise HTTPException(status_code=502, detail=f"AI Provider error: {str(ex)}")

    async def event_generator():
        accumulated_text = ""
        try:
            async for chunk in provider.stream_chat_completion(
                messages=formatted_messages,
                model=model,
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
                system_prompt=system_prompt
            ):
                accumulated_text += chunk
                yield f"data: {chunk}\n\n"
            
            yield "data: [DONE]\n\n"

            if accumulated_text:
                async with AsyncSession(db.bind) as persist_db:
                    assistant_msg_db = Message(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=accumulated_text,
                        bot_id=payload.bot_id,
                        ai_marked=True
                    )
                    persist_db.add(assistant_msg_db)
                    await persist_db.commit()
        except Exception as err:
            yield f"data: [ERROR: {str(err)}]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
