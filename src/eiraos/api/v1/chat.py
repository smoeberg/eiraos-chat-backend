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
_CHARS_PER_TOKEN = 4
DEFAULT_HISTORY_TOKEN_BUDGET = 8000


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
    max_history: int = 40,
    history_token_budget: int = DEFAULT_HISTORY_TOKEN_BUDGET,
) -> list[dict]:
    """Build messages with system prompt and a char/token history budget."""
    stmt = (
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.status.in_(["completed", "cancelled"]),
        )
        .order_by(Message.created_at.desc())
        .limit(max_history)
    )
    rows = list((await db.execute(stmt)).scalars().all())

    budget_chars = max(history_token_budget, 0) * _CHARS_PER_TOKEN
    selected: list[dict] = []
    used = 0
    for m in rows:
        if m.role not in ("user", "assistant", "system") or not m.content:
            continue
        size = len(m.content)
        if used + size > budget_chars and selected:
            break
        selected.append({"role": m.role, "content": m.content})
        used += size

    selected.reverse()
    messages: list[dict] = []
    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.extend(selected)
    if not messages or messages[-1].get("content") != current_prompt:
        messages.append({"role": "user", "content": current_prompt})
    return messages


async def _transition_assistant(
    db: AsyncSession,
    asst_id: int | None,
    conversation_id: int,
    bot_id: int,
    content: str,
    status_value: str,
) -> None:
    """Update the streaming row in place; insert only if no row exists."""
    if asst_id is not None:
        row = (
            await db.execute(select(Message).where(Message.id == asst_id))
        ).scalars().first()
        if row is not None:
            row.content = content
            row.status = status_value
            await db.commit()
            return
    db.add(
        Message(
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            bot_id=bot_id,
            status=status_value,
            ai_marked=True,
        )
    )
    await db.commit()


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

    idem_key = idempotency.resolve_idempotency_key(
        request, getattr(payload, "idempotency_key", None)
    )
    lease_token: str | None = None
    if idem_key:
        outcome = await idempotency.begin_idempotency(db, request, idem_key)
        if outcome.status == "completed":
            cached = await idempotency.read_cached_response(db, request, idem_key)
            if cached is not None:
                return json.loads(cached)
        lease_token = outcome.lease_token

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
                    lease_token=lease_token,
                )
            return {"role": "assistant", "content": full_response, "ai_marked": True}
        except HTTPException:
            raise
        except Exception:
            if idem_key:
                await idempotency.complete_idempotency(
                    db, request, idem_key, status.HTTP_500_INTERNAL_SERVER_ERROR, "failed",
                    lease_token=lease_token,
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
                    if await request.is_disconnected():
                        raise asyncio.CancelledError()
                    now = asyncio.get_event_loop().time()
                    if now - last_heartbeat >= SSE_HEARTBEAT_SECONDS:
                        yield ": keep-alive\n\n"
                        last_heartbeat = now
            except asyncio.TimeoutError:
                raise RuntimeError("provider stream timed out")

            await _transition_assistant(
                db, asst_id, conversation.id, bot.id, accumulated, "completed"
            )
            if idem_key:
                await idempotency.complete_idempotency(
                    db, request, idem_key, status.HTTP_200_OK,
                    json.dumps({"assistant": accumulated}),
                    lease_token=lease_token,
                )
            yield f"data: {json.dumps({'type': 'done', 'full_content': accumulated})}\n\n"
        except asyncio.CancelledError:
            try:
                await _transition_assistant(
                    db, asst_id, conversation.id, bot.id, accumulated, "cancelled"
                )
            except Exception:
                pass
            raise
        except Exception:
            try:
                await _transition_assistant(
                    db, asst_id, conversation.id, bot.id, accumulated, "failed"
                )
            except Exception:
                pass
            yield f"data: {json.dumps({'type': 'error', 'detail': _sanitize()})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
