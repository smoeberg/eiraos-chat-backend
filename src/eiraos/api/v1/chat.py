import json
import asyncio
from typing import AsyncIterator
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from eiraos.core.database import get_db
from eiraos.api.v1.auth import get_current_user, get_current_active_organization
from eiraos.domains.conversations.models import Conversation, Message
from eiraos.domains.agents.models import Bot
from eiraos.application.providers.factory import AIProviderFactory
from eiraos.core.secrets import SecretService
from eiraos.core import idempotency
from eiraos.core.exceptions import EiraOSException

router = APIRouter(prefix="/chat", tags=["AI Chat Gateway"])

# Heartbeat keeps proxies from closing idle SSE connections.
SSE_HEARTBEAT_SECONDS = 15
# If the provider produces no token within this window, treat the stream as dead.
SSE_CHUNK_TIMEOUT_SECONDS = 30


class ChatCompletionRequest(BaseModel):
    conversation_id: int
    bot_id: int
    prompt: str
    stream: bool = True
    idempotency_key: str | None = None


def _sanitize() -> str:
    """Return a generic, non-informative error string for clients."""
    return "An unexpected error occurred while processing your request."


async def _next_chunk(stream, timeout: float):
    """Awaits one chunk from an async iterator with a timeout; None on drain."""
    try:
        return await asyncio.wait_for(stream.__anext__(), timeout=timeout)
    except StopAsyncIteration:
        return None


def _bot_accessible(bot: Bot, org_id: int) -> bool:
    """A bot is reachable if it belongs to the caller's org or is public.

    Uses Bot.visibility (single source of truth) rather than the legacy boolean.
    """
    if bot.organization_id is not None and bot.organization_id == org_id:
        return True
    return Bot.visibility(bot) == "public"


@router.post("/completions")
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

    # Idempotency: replaying a request with the same Idempotency-Key header
    # returns the cached result instead of re-invoking the (paid) provider.
    idem_key = (payload.idempotency_key or "").strip() or None
    if idem_key:
        begin_status = await idempotency.begin_idempotency(db, request, idem_key)
        if begin_status == "completed":
            cached = await idempotency.read_cached_response(request, idem_key)
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

    # Resolve provider credential (fail-closed, never leaks a secret).
    try:
        api_key = SecretService.resolve(bot.organization_id, bot.secret_reference, None)
        provider = AIProviderFactory.get_provider(bot.provider, api_key)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI provider could not be initialized.",
        )

    if not payload.stream:
        try:
            full_response = await provider.generate_chat_completion(
                model=bot.model,
                messages=[{"role": "user", "content": payload.prompt}],
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

    # ---- streaming SSE with message lifecycle + heartbeat + timeout + disconnect handling ----
    async def event_generator() -> AsyncIterator[str]:
        accumulated = ""
        last_heartbeat = asyncio.get_event_loop().time()
        try:
            yield f"data: {json.dumps({'type': 'start', 'bot_id': bot.id, 'conversation_id': conversation.id})}\n\n"
            stream = provider.stream_chat_completion(
                model=bot.model,
                messages=[{"role": "user", "content": payload.prompt}],
                system_prompt=bot.system_prompt,
            )
            try:
                # Draining the provider stream with a per-chunk timeout so a silent
                # upstream stall fails the stream cleanly instead of hanging forever.
                while True:
                    chunk = await _next_chunk(stream, SSE_CHUNK_TIMEOUT_SECONDS)
                    if chunk is None:
                        break  # provider legitimately finished
                    accumulated += chunk
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
                    # Emit a heartbeat if the client has not been written to recently.
                    now = asyncio.get_event_loop().time()
                    if now - last_heartbeat >= SSE_HEARTBEAT_SECONDS:
                        yield ": keep-alive\n\n"
                        last_heartbeat = now
            except asyncio.TimeoutError:
                # No provider output for the full window: fail the stream explicitly.
                raise RuntimeError("provider stream timed out")

            # Save completed assistant message
            asst = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=accumulated,
                bot_id=bot.id,
                status="completed",
                ai_marked=True,
            )
            db.add(asst)
            await db.commit()
            yield f"data: {json.dumps({'type': 'done', 'full_content': accumulated})}\n\n"
        except asyncio.CancelledError:
            # Client disconnected mid-stream: persist the partial transcript so
            # nothing is silently lost, then stop generating cleanly.
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
            # Persist a failed assistant message rather than silently dropping it.
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
