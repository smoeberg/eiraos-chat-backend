import json
import asyncio
from typing import AsyncIterator
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from eiraos.core.database import get_db
from eiraos.api.v1.auth import get_current_user, get_current_active_organization, require_permission
from eiraos.domains.conversations.models import Conversation, Message
from eiraos.domains.agents.models import Bot
from eiraos.domains.documents.rag_service import RAGService
from eiraos.api.v1.documents import generate_embedding
from eiraos.application.providers.factory import AIProviderFactory
from eiraos.application.business_features import verify_answer, VERIFIED_BADGE, build_knowledge_system_context
from eiraos.core.secrets import SecretService
from eiraos.core import idempotency

router = APIRouter(prefix="/chat", tags=["AI Chat Gateway"])
SSE_HEARTBEAT_SECONDS = 15
SSE_CHUNK_TIMEOUT_SECONDS = 30
_CHARS_PER_TOKEN = 4
DEFAULT_HISTORY_TOKEN_BUDGET = 8000
MAX_KNOWLEDGE_SCOPE_CHARS = 120


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: int
    bot_id: int
    prompt: str = Field(..., min_length=1)
    stream: bool = True
    idempotency_key: str | None = None
    verify: bool = False
    knowledge_scope: str | None = Field(default=None, max_length=MAX_KNOWLEDGE_SCOPE_CHARS)


def _sanitize() -> str:
    return "An unexpected error occurred while processing your request."


async def _next_chunk(stream, timeout: float):
    try:
        return await asyncio.wait_for(stream.__anext__(), timeout=timeout)
    except StopAsyncIteration:
        return None


async def _build_messages(db: AsyncSession, conversation_id: int, current_prompt: str, system_prompt: str | None,
                          max_history: int = 40, history_token_budget: int = DEFAULT_HISTORY_TOKEN_BUDGET) -> list[dict]:
    """Build messages without filtering by bot, preserving cross-bot history."""
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.status.in_(["completed", "cancelled"]))
        .order_by(Message.created_at.desc(), Message.id.desc())
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


async def _transition_assistant(db: AsyncSession, asst_id: int | None, conversation_id: int, bot_id: int,
                                content: str, status_value: str) -> None:
    if asst_id is not None:
        row = (await db.execute(select(Message).where(Message.id == asst_id))).scalars().first()
        if row is not None:
            row.content = content
            row.status = status_value
            await db.commit()
            return
    db.add(Message(conversation_id=conversation_id, role="assistant", content=content, bot_id=bot_id,
                   status=status_value, ai_marked=True))
    await db.commit()


def _bot_accessible(bot: Bot, org_id: int) -> bool:
    if bot.organization_id is not None and bot.organization_id == org_id:
        return True
    return Bot.visibility(bot) == "public"


def _valid_knowledge_scope(value: str | None) -> str | None:
    if value is None:
        return None
    scope = value.strip()
    if not scope or scope in {".", ".."} or any(part in {".", ".."} for part in scope.split("/")):
        raise HTTPException(status_code=422, detail="Invalid knowledge_scope")
    return scope


async def _find_verifier_bot(db: AsyncSession, primary_bot: Bot, org_id: int) -> Bot:
    """Select another accessible/configured bot, otherwise use the primary bot."""
    candidates = (await db.execute(select(Bot).where(Bot.id != primary_bot.id).order_by(Bot.id.asc()))).scalars().all()
    for candidate in candidates:
        if not _bot_accessible(candidate, org_id) or not candidate.provider or not candidate.model:
            continue
        try:
            SecretService.resolve(candidate.organization_id, candidate.secret_reference, None,
                                  credential_scope=getattr(candidate, "credential_scope", "organization") or "organization",
                                  caller_org_id=org_id)
        except Exception:
            continue
        return candidate
    return primary_bot


async def _provider_for_bot(bot: Bot, org_id: int):
    api_key = SecretService.resolve(candidate_org_id := bot.organization_id, bot.secret_reference, None,
                                    credential_scope=getattr(bot, "credential_scope", "organization") or "organization",
                                    caller_org_id=org_id)
    return AIProviderFactory.get_provider(bot.provider, api_key)


async def _knowledge_context(db: AsyncSession, org_id: int, prompt: str, knowledge_scope: str | None) -> str | None:
    if not knowledge_scope:
        return None
    query_embedding = await generate_embedding(prompt)
    results = await RAGService.hybrid_search(
        db=db, organization_id=org_id, query_embedding=query_embedding,
        query_text=prompt, limit=6, knowledge_scope=knowledge_scope,
    )
    return build_knowledge_system_context(results)


def _combined_system_prompt(bot_prompt: str | None, knowledge_context: str | None) -> str | None:
    parts = [p.strip() for p in (bot_prompt, knowledge_context) if p and p.strip()]
    return "\n\n".join(parts) if parts else None


@router.post("/completions", dependencies=[Depends(require_permission("conversation:create"))])
async def create_chat_completion(request: Request, payload: ChatCompletionRequest,
                                 current_user: dict = Depends(get_current_user),
                                 org_id: int = Depends(get_current_active_organization),
                                 db: AsyncSession = Depends(get_db)):
    conv_stmt = select(Conversation).where(
        Conversation.id == payload.conversation_id,
        Conversation.organization_id == org_id,
        Conversation.user_id == current_user["user_id"],
    )
    conversation = (await db.execute(conv_stmt)).scalars().first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found or access denied")

    bot = (await db.execute(select(Bot).where(Bot.id == payload.bot_id))).scalars().first()
    if not bot or not _bot_accessible(bot, org_id):
        raise HTTPException(status_code=404, detail="Bot not found or access denied")

    knowledge_scope = _valid_knowledge_scope(payload.knowledge_scope)
    idem_key = idempotency.resolve_idempotency_key(request, getattr(payload, "idempotency_key", None))
    lease_token: str | None = None
    if idem_key:
        outcome = await idempotency.begin_idempotency(db, request, idem_key)
        if outcome.status == "completed":
            cached = await idempotency.read_cached_response(db, request, idem_key)
            if cached is not None:
                return json.loads(cached)
        lease_token = outcome.lease_token

    db.add(Message(conversation_id=conversation.id, role="user", content=payload.prompt, bot_id=bot.id,
                   status="completed", ai_marked=False))
    await db.commit()

    try:
        provider = await _provider_for_bot(bot, org_id)
        knowledge_context = await _knowledge_context(db, org_id, payload.prompt, knowledge_scope)
        effective_system_prompt = _combined_system_prompt(bot.system_prompt, knowledge_context)
        provider_messages = await _build_messages(db, conversation.id, payload.prompt, effective_system_prompt)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="AI provider could not be initialized.")

    if not payload.stream:
        try:
            full_response = await provider.generate_chat_completion(model=bot.model, messages=provider_messages,
                                                                     system_prompt=effective_system_prompt)
            verified = False
            if payload.verify:
                verifier_bot = await _find_verifier_bot(db, bot, org_id)
                verifier = await _provider_for_bot(verifier_bot, org_id)
                full_response = await verify_answer(primary_answer=full_response, original_prompt=payload.prompt,
                                                    verifier=verifier, model=verifier_bot.model)
                verified = True
            db.add(Message(conversation_id=conversation.id, role="assistant", content=full_response, bot_id=bot.id,
                           status="completed", ai_marked=True))
            await db.commit()
            if idem_key:
                await idempotency.complete_idempotency(db, request, idem_key, status.HTTP_200_OK,
                                                       json.dumps({"assistant": full_response}), lease_token=lease_token)
            return {"role": "assistant", "content": full_response, "ai_marked": True, "verified": verified}
        except HTTPException:
            raise
        except Exception:
            if idem_key:
                await idempotency.complete_idempotency(db, request, idem_key, 500, "failed", lease_token=lease_token)
            raise HTTPException(status_code=502, detail="AI provider could not fulfil the request.")

    async def event_generator() -> AsyncIterator[str]:
        accumulated = ""
        last_heartbeat = asyncio.get_event_loop().time()
        asst_id = None
        try:
            pending = Message(conversation_id=conversation.id, role="assistant", content="", bot_id=bot.id,
                              status="streaming", ai_marked=True)
            db.add(pending)
            await db.commit()
            await db.refresh(pending)
            asst_id = pending.id
            yield f"data: {json.dumps({'type': 'start', 'bot_id': bot.id, 'conversation_id': conversation.id, 'message_id': asst_id})}\n\n"
            stream = provider.stream_chat_completion(model=bot.model, messages=provider_messages,
                                                     system_prompt=effective_system_prompt)
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

            verified = False
            if payload.verify:
                verifier_bot = await _find_verifier_bot(db, bot, org_id)
                verifier = await _provider_for_bot(verifier_bot, org_id)
                accumulated = await verify_answer(primary_answer=accumulated, original_prompt=payload.prompt,
                                                 verifier=verifier, model=verifier_bot.model)
                verified = True
                yield f"data: {json.dumps({'type': 'verified', 'badge': VERIFIED_BADGE})}\n\n"

            await _transition_assistant(db, asst_id, conversation.id, bot.id, accumulated, "completed")
            if idem_key:
                await idempotency.complete_idempotency(db, request, idem_key, 200,
                                                       json.dumps({"assistant": accumulated}), lease_token=lease_token)
            yield f"data: {json.dumps({'type': 'done', 'full_content': accumulated, 'verified': verified})}\n\n"
        except asyncio.CancelledError:
            try:
                await _transition_assistant(db, asst_id, conversation.id, bot.id, accumulated, "cancelled")
            except Exception:
                pass
            raise
        except Exception:
            try:
                await _transition_assistant(db, asst_id, conversation.id, bot.id, accumulated, "failed")
            except Exception:
                pass
            yield f"data: {json.dumps({'type': 'error', 'detail': _sanitize()})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
