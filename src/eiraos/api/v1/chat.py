import json
import asyncio
from typing import AsyncIterator
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from eiraos.core.database import get_db
from eiraos.api.v1.auth import get_current_user, get_current_active_organization, require_permission
from eiraos.domains.conversations.models import Conversation, Message
from eiraos.domains.agents.models import Bot
from eiraos.application.providers.factory import AIProviderFactory
from eiraos.core.secrets import SecretService
from eiraos.core import idempotency

router = APIRouter(prefix="/chat", tags=["AI Chat Gateway"])

SSE_HEARTBEAT_SECONDS = 15
SSE_CHUNK_TIMEOUT_SECONDS = 30


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: int
    bot_id: int
    prompt: str
    stream: bool = True
    idempotency_key: str | None = None


def _sanitize() -> str:
    return "An unexpected error occurred while processing your request."


async def _next_chunk(stream, timeout: float):
    try:
        return await asyncio.wait_for(stream.__anext__(), timeout=timeout)
    except StopAsyncIteration:
        return None


async def _build_messages(
    db: AsyncSession,
    conversation_id: int,
    current_prompt: str,
    system_prompt: str | None,
    max_history: int = 20,
) -> list[dict]:
    """Build provider messages: recent history + current user turn."""
    stmt = (
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.status.in_(["completed", "interrupted"]),
        )
        .order_by(Message.created_at.desc())
        .limit(max_history)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    rows.reverse()
    messages: list[dict] = []
    for m in rows:
        if m.role in ("user", "assistant", "system") and m.content:
            messages.append({"role": m.role, "content": m.content})
    if not messages or messages[-1].get("content") != current_prompt:
        messages.append({"role": "user", "content": current_prompt})
    return messages


def _bot_accessible(bot: Bot, org_id: int) -> bool:
    if bot.organization_id is not None and bot.organization_id == org_id:
        return True
    return Bot.visibility(bot) == "public"


@router.post("/completions", dependencies=[Depends(require_permission("conversation:create"))])
async def create_chat_completion(
    request: Request,
    payload: ChatCompletionRequest,
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
    db: AsyncSession = Depends(get_db),
):
    conv_stmt = select(Conversation).where(
        Conversation.id == payload.conversation_id,
        Conversation.organization_id == org_id,
        Conversation.user_id == current_user["user_id"],
    )
    conversation = (await db.execute(conv_stmt)).scalars().first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found or access denied")

    bot_stmt = select(Bot).where(Bot.id == payload.bot_id)
    bot = (await db.execute(bot_stmt)).scalars().first()
    if not bot or not _bot_accessible(bot, org_id):
        raise HTTPException(status_code=404, detail="Bot not found or access denied")

    idem_key = (payload.idempotency_key or "").strip() or None
    if idem_key:
        begin_status = await idempotency.begin_idempotency(db, request, idem_key)
        if begin_status == "completed":
            cached = await idempotency.read_cached_response(db, request, idem_key)
            if cached is not None:
                return json.loads(cached)

    user_msg = Message(
        conversation_id=conversation.id,
        role="user",
        content=payload.prompt,
        bot_id=bot.id,
        status="completed",
        ai_marked=False,
    )
    db.add(user_msg)
    await db.commit()

    try:
        api_key = SecretService.resolve(
            bot.organization_id,
            bot.secret_reference,
            None,
            credential_scope=getattr(bot, "credential_scope", "organization") or "organization",
            caller_org_id=org_id,
        )
        provider = AIProviderFactory.get_provider(bot.provider, api_key)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI provider could not be initialized.",
        )

    provider_messages = await _build_messages(
        db, conversation.id, payload.prompt, bot.system_prompt
    )

    if not payload.stream:
        try:
            full_response = await provider.generate_chat_completion(
                model=bot.model,
                messages=provider_messages,
                system_prompt=bot.system_prompt,
            )
            asst_msg = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=full_response,
                bot_id=bot.id,
                status="completed",
                ai_marked=True,
            )
            db.add(asst_msg)
            await db.commit()
            if idem_key:
                await idempotency.complete_idempotency(
                    db, request, idem_key, status.HTTP_200_OK,
                    json.dumps({"assistant": full_response}),
                )
            return {"role": "assistant", "content": full_response, "ai_marked": True}
        except HTTPException:
            raise
        except Exception:
            if idem_key:
                await idempotency.complete_idempotency(
                    db, request, idem_key, status.HTTP_500_INTERNAL_SERVER_ERROR, "failed",
                )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="AI provider could not fulfil the request.",
            )

    async def event_generator() -> AsyncIterator[str]:
        accumulated = ""
        last_heartbeat = asyncio.get_event_loop().time()
        asst_id = None
        try:
            pending = Message(
                conversation_id=conversation.id,
                role="assistant",
                content="",
                bot_id=bot.id,
                status="streaming",
                ai_marked=True,
            )
            db.add(pending)
            await db.commit()
            await db.refresh(pending)
            asst_id = pending.id

            yield f"data: {json.dumps({'type': 'start', 'bot_id': bot.id, 'conversation_id': conversation.id, 'message_id': asst_id})}\n\n"
            stream = provider.stream_chat_completion(
                model=bot.model,
                messages=provider_messages,
                system_prompt=bot.system_prompt,
            )
            try:
                while True:
                    chunk = await _next_chunk(stream, SSE_CHUNK_TIMEOUT_SECONDS)
                    if chunk is None:
                        break
                    accumulated += chunk
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
                    now = asyncio.get_event_loop().time()
                    if now - last_heartbeat >= SSE_HEARTBEAT_SECONDS:
                        yield ": keep-alive\n\n"
                        last_heartbeat = now
            except asyncio.TimeoutError:
                raise RuntimeError("provider stream timed out")

            if asst_id is not None:
                row = (await db.execute(select(Message).where(Message.id == asst_id))).scalars().first()
                if row:
                    row.content = accumulated
                    row.status = "completed"
                    await db.commit()
            if idem_key:
                await idempotency.complete_idempotency(
                    db, request, idem_key, status.HTTP_200_OK,
                    json.dumps({"assistant": accumulated}),
                )
            yield f"data: {json.dumps({'type': 'done', 'full_content': accumulated})}\n\n"
        except asyncio.CancelledError:
            try:
                interrupted = Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=accumulated,
                    bot_id=bot.id,
                    status="interrupted",
                    ai_marked=True,
                )
                db.add(interrupted)
                await db.commit()
            except Exception:
                pass
            raise
        except Exception:
            try:
                failed = Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=accumulated,
                    bot_id=bot.id,
                    status="failed",
                    ai_marked=True,
                )
                db.add(failed)
                await db.commit()
            except Exception:
                pass
            yield f"data: {json.dumps({'type': 'error', 'detail': _sanitize()})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
