import json
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from eiraos.core.database import get_db
from eiraos.api.v1.auth import get_current_user, get_current_active_organization
from eiraos.domains.conversations.models import Conversation, Message
from eiraos.domains.agents.models import Bot
from eiraos.application.providers.factory import AIProviderFactory

router = APIRouter(prefix="/chat", tags=["AI Chat Gateway"])

class ChatCompletionRequest(BaseModel):
    conversation_id: int
    bot_id: int
    prompt: str
    stream: bool = True

@router.post("/completions")
async def create_chat_completion(
    payload: ChatCompletionRequest,
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
    db: AsyncSession = Depends(get_db)
):
    # Verify conversation belongs to org & user
    conv_stmt = select(Conversation).where(
        Conversation.id == payload.conversation_id,
        Conversation.organization_id == org_id,
        Conversation.user_id == current_user["user_id"]
    )
    conv_res = await db.execute(conv_stmt)
    conversation = conv_res.scalars().first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found or access denied")

    # Verify bot access & visibility scopes
    bot_stmt = select(Bot).where(
        Bot.id == payload.bot_id,
        ((Bot.organization_id == org_id) | (Bot.bot_visibility == "public"))
    )
    bot_res = await db.execute(bot_stmt)
    bot = bot_res.scalars().first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found or access denied")

    # Save user message
    user_msg = Message(
        conversation_id=conversation.id,
        role="user",
        content=payload.prompt,
        bot_id=bot.id,
        status="completed",
        ai_marked=False
    )
    db.add(user_msg)
    await db.commit()

    # Initialize AI Provider
    try:
        provider = AIProviderFactory.get_provider(bot.provider)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initialize AI provider: {str(e)}")

    if not payload.stream:
        # Non-streaming response
        try:
            full_response = await provider.generate_chat_completion(
                model=bot.model,
                messages=[{"role": "user", "content": payload.prompt}],
                system_prompt=bot.system_prompt
            )
            asst_msg = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=full_response,
                bot_id=bot.id,
                status="completed",
                ai_marked=True
            )
            db.add(asst_msg)
            await db.commit()
            return {"role": "assistant", "content": full_response, "ai_marked": True}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"AI provider error: {str(e)}")

    # Streaming SSE response
    async def event_generator():
        accumulated_content = ""
        try:
            yield f"data: {json.dumps({'type': 'start', 'bot_id': bot.id})}\n\n"
            
            async for chunk in provider.stream_chat_completion(
                model=bot.model,
                messages=[{"role": "user", "content": payload.prompt}],
                system_prompt=bot.system_prompt
            ):
                accumulated_content += chunk
                yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

            # Save assistant message on complete
            # Note: For robust session handling in generator, use a new session or commit
            asst_msg = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=accumulated_content,
                bot_id=bot.id,
                status="completed",
                ai_marked=True
            )
            db.add(asst_msg)
            await db.commit()

            yield f"data: {json.dumps({'type': 'done', 'full_content': accumulated_content})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
