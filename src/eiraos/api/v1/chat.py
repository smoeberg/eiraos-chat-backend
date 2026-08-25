import json
import asyncio
from dataclasses import dataclass
from typing import AsyncIterator
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from eiraos.core.database import get_db
from eiraos.api.v1.auth import get_current_active_organization, require_permission
from eiraos.domains.conversations.models import Conversation, Message
from eiraos.domains.agents.models import Bot
from eiraos.domains.documents.rag_service import RAGService
from eiraos.api.v1.documents import generate_embedding
from eiraos.application.providers.factory import AIProviderFactory
from eiraos.application.business_features import verify_answer, build_knowledge_system_context, VerificationResult, VERIFICATION_FAILED_BADGE
from eiraos.core.secrets import SecretService
from eiraos.core import idempotency
from eiraos.core.config import settings
from eiraos.core.usage_budget import BudgetExceeded, BudgetUnavailable, UsageBudgetGate
from eiraos.application.usage_execution import ProviderExecutionBudget
from eiraos.domains.usage.cost_estimator import CostEstimator
from eiraos.application.chat_execution import ChatExecutionBoundary, IdempotencyReservation
from eiraos.application.chat_persistence import (
    ChatPersistenceContract,
    PersistedChatExecution,
    PersistenceConflict,
    PersistenceUnavailable,
    RetryLimitExceeded,
    execution_identity,
)
from eiraos.application.chat_recovery import FailureCode, failure_policy, provider_with_timeout
from eiraos.application.streaming_lifecycle import (
    StreamEventKind,
    StreamFinalizer,
    StreamPump,
    StreamTerminal,
)
from eiraos.application.provider_execution_policy import (
    ProviderExecutionPermit,
    ProviderPolicyDenied,
    authorize_provider_execution,
)
from eiraos.application.governance_audit import (
    GovernanceAuditTrail,
    GovernanceAuditUnavailable,
    request_fingerprint,
)

router = APIRouter(prefix="/chat", tags=["AI Chat Gateway"])
SSE_HEARTBEAT_SECONDS = 15
SSE_CHUNK_TIMEOUT_SECONDS = 30
_CHARS_PER_TOKEN = 4
DEFAULT_HISTORY_TOKEN_BUDGET = 8000
MAX_KNOWLEDGE_SCOPE_CHARS = 120
_USAGE_BUDGET_GATE: UsageBudgetGate | None = None


def _usage_budget_gate() -> UsageBudgetGate:
    global _USAGE_BUDGET_GATE
    if _USAGE_BUDGET_GATE is None:
        _USAGE_BUDGET_GATE = UsageBudgetGate(
            user_remaining=settings.USER_BUDGET_REMAINING,
            organization_remaining=settings.ORGANIZATION_BUDGET_REMAINING,
            max_execution_cost=settings.EXECUTION_BUDGET_MAX_COST,
        )
    return _USAGE_BUDGET_GATE


def _execution_budget() -> ProviderExecutionBudget:
    return ProviderExecutionBudget(
        estimator=CostEstimator(),
        gate_factory=_usage_budget_gate,
    )


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: int
    bot_id: int
    prompt: str = Field(..., min_length=1)
    stream: bool = True
    idempotency_key: str | None = None
    verify: bool = False
    knowledge_scope: str | None = Field(default=None, max_length=MAX_KNOWLEDGE_SCOPE_CHARS)


@dataclass(frozen=True)
class _AuthorizedChat:
    conversation: Conversation
    bot: Bot
    knowledge_scope: str | None
    provider_permit: ProviderExecutionPermit
    governance_decision_id: str


@dataclass(frozen=True)
class _ProviderContext:
    provider: object
    messages: list[dict]
    system_prompt: str | None


def _sanitize() -> str:
    return "An unexpected error occurred while processing your request."


async def _next_chunk(stream, timeout: float):
    try:
        return await asyncio.wait_for(stream.__anext__(), timeout=timeout)
    except StopAsyncIteration:
        return None


async def _lease_heartbeat(db: AsyncSession, request: Request, key: str, lease_token: str, lost: asyncio.Event) -> None:
    """Keep a chat idempotency lease alive while a long AI operation runs."""
    interval = max(1, min(idempotency.LEASE_RENEWAL_SECONDS, idempotency.LEASE_SECONDS // 2))
    try:
        while True:
            await asyncio.sleep(interval)
            if not await idempotency.renew_idempotency_lease(db, request, key, lease_token):
                lost.set()
                return
    except asyncio.CancelledError:
        raise
    except Exception:
        lost.set()


async def _start_lease_heartbeat(db: AsyncSession, request: Request, key: str | None, lease_token: str | None):
    if not key or not lease_token:
        return None, None
    lost = asyncio.Event()
    task = asyncio.create_task(_lease_heartbeat(db, request, key, lease_token, lost))
    return task, lost


async def _stop_lease_heartbeat(task, lost: asyncio.Event | None) -> bool:
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return not lost.is_set() if lost is not None else True


async def _release_preflight_lease(db: AsyncSession, request: Request, idem_key: str | None,
                                   lease_token: str | None, status_code: int) -> None:
    if idem_key and lease_token:
        await idempotency.complete_idempotency(
            db, request, idem_key, status_code, "failed", lease_token=lease_token
        )


async def _build_messages(db: AsyncSession, conversation_id: int, current_prompt: str, system_prompt: str | None,
                          max_history: int = 40, history_token_budget: int = DEFAULT_HISTORY_TOKEN_BUDGET) -> list[dict]:
    stmt = (select(Message).where(Message.conversation_id == conversation_id,
                                  Message.status.in_(["completed", "cancelled"]))
            .order_by(Message.created_at.desc(), Message.id.desc()).limit(max_history))
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


def _bot_accessible(bot: Bot, org_id: int) -> bool:
    if bot.organization_id is not None and bot.organization_id == org_id:
        return True
    return Bot.visibility(bot) == "public"


def _verifier_bot_accessible(bot: Bot, org_id: int) -> bool:
    """Verification is a privileged server-side operation and is tenant-bound.

    Unlike normal chat access, a public bot belonging to another organization
    must never be selected as a verifier. This prevents cross-organization
    credential/context use through the automatic verifier selection path.
    """
    return bot.organization_id == org_id


def _valid_knowledge_scope(value: str | None) -> str | None:
    if value is None:
        return None
    scope = value.strip()
    if not scope or scope in {".", ".."} or any(part in {".", ".."} for part in scope.split("/")):
        raise HTTPException(status_code=422, detail="Invalid knowledge_scope")
    return scope


async def _find_verifier_bot(
    db: AsyncSession, primary_bot: Bot, org_id: int, authorization,
) -> tuple[Bot, ProviderExecutionPermit]:
    candidates = (await db.execute(select(Bot).where(Bot.id != primary_bot.id).order_by(Bot.id.asc()))).scalars().all()
    for candidate in candidates:
        if not _verifier_bot_accessible(candidate, org_id) or not candidate.provider or not candidate.model:
            continue
        try:
            permit = authorize_provider_execution(
                authorization=authorization, bot=candidate, caller_organization_id=org_id,
            )
        except ProviderPolicyDenied:
            continue
        return candidate, permit
    if not _verifier_bot_accessible(primary_bot, org_id):
        raise ProviderPolicyDenied("verifier_tenant_mismatch")
    return primary_bot, authorize_provider_execution(
        authorization=authorization, bot=primary_bot, caller_organization_id=org_id,
    )


async def _provider_for_bot(bot: Bot, org_id: int, permit: ProviderExecutionPermit):
    permit.assert_matches(bot=bot, caller_organization_id=org_id)
    api_key = SecretService.resolve(bot.organization_id, bot.secret_reference, None,
                                    credential_scope=getattr(bot, "credential_scope", "organization") or "organization",
                                    caller_org_id=org_id)
    return AIProviderFactory.get_provider(bot.provider, api_key)


async def _knowledge_context(db: AsyncSession, org_id: int, prompt: str, knowledge_scope: str | None) -> str | None:
    if not knowledge_scope:
        return None
    query_embedding = await generate_embedding(prompt)
    results = await RAGService.hybrid_search(db=db, organization_id=org_id, query_embedding=query_embedding,
                                              query_text=prompt, limit=6, knowledge_scope=knowledge_scope)
    return build_knowledge_system_context(results)


def _combined_system_prompt(bot_prompt: str | None, knowledge_context: str | None) -> str | None:
    parts = [p.strip() for p in (bot_prompt, knowledge_context) if p and p.strip()]
    return "\n\n".join(parts) if parts else None


def _verification_failure(primary_answer: str, reason: str) -> VerificationResult:
    return VerificationResult(
        status="UNCERTAIN",
        reason=reason,
        answer=primary_answer + VERIFICATION_FAILED_BADGE,
        verified=False,
    )


@router.post("/completions")
async def create_chat_completion(request: Request, payload: ChatCompletionRequest,
                                 current_user: dict = Depends(require_permission("conversation:create")),
                                 org_id: int = Depends(get_current_active_organization),
                                 db: AsyncSession = Depends(get_db)):
    reserved_idem = IdempotencyReservation(None, None)
    budgeted_execution = None
    persisted_execution: PersistedChatExecution | None = None
    persistence = ChatPersistenceContract(db)
    governance_audit = GovernanceAuditTrail(db)
    governance_decision_id: str | None = None
    request_hash = request_fingerprint(getattr(request.state, "cached_body", b""))

    async def authorize() -> _AuthorizedChat:
        nonlocal governance_decision_id
        conversation = (await db.execute(select(Conversation).where(
            Conversation.id == payload.conversation_id,
            Conversation.organization_id == org_id,
            Conversation.user_id == current_user["user_id"],
        ))).scalars().first()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found or access denied")
        bot = (await db.execute(select(Bot).where(Bot.id == payload.bot_id))).scalars().first()
        if not bot or not _bot_accessible(bot, org_id):
            raise HTTPException(status_code=404, detail="Bot not found or access denied")
        try:
            permit = authorize_provider_execution(
                authorization=current_user["authorization"],
                bot=bot,
                caller_organization_id=org_id,
            )
        except ProviderPolicyDenied as exc:
            try:
                await governance_audit.record_provider_decision(
                    request_id=getattr(request.state, "request_id", "unknown"),
                    request_hash=request_hash,
                    authorization=current_user["authorization"],
                    bot_id=bot.id,
                    bot_organization_id=bot.organization_id,
                    allowed=False,
                    reason=exc.reason,
                    provider=getattr(bot, "provider", None),
                    model=getattr(bot, "model", None),
                    permit=None,
                )
            except GovernanceAuditUnavailable as audit_exc:
                raise HTTPException(status_code=503, detail="Governance audit is unavailable.") from audit_exc
            raise HTTPException(status_code=403, detail="Provider execution is not permitted.") from exc
        try:
            governance_decision_id = await governance_audit.record_provider_decision(
                request_id=getattr(request.state, "request_id", "unknown"),
                request_hash=request_hash,
                authorization=current_user["authorization"],
                bot_id=bot.id,
                bot_organization_id=bot.organization_id,
                allowed=True,
                reason="granted",
                provider=permit.provider,
                model=permit.model,
                permit=permit,
            )
        except GovernanceAuditUnavailable as exc:
            raise HTTPException(status_code=503, detail="Governance audit is unavailable.") from exc
        return _AuthorizedChat(
            conversation, bot, _valid_knowledge_scope(payload.knowledge_scope), permit,
            governance_decision_id,
        )

    async def reserve_idempotency() -> IdempotencyReservation:
        nonlocal reserved_idem
        key = idempotency.resolve_idempotency_key(request, payload.idempotency_key)
        if not key:
            return reserved_idem
        outcome = await idempotency.begin_idempotency(db, request, key)
        if outcome.status == "completed":
            cached = await idempotency.read_cached_response(db, request, key)
            if cached is not None:
                reserved_idem = IdempotencyReservation(
                    key=key, lease_token=None, cached_response=json.loads(cached),
                    record_id=outcome.record_id,
                    is_recovery=False,
                )
                return reserved_idem
        reserved_idem = IdempotencyReservation(
            key=key, lease_token=outcome.lease_token, record_id=outcome.record_id,
            is_recovery=outcome.is_recovery,
        )
        if outcome.is_recovery and outcome.record_id is not None:
            await persistence.assert_recovery_allowed(
                execution_id=execution_identity(
                    organization_id=org_id,
                    user_id=current_user["user_id"],
                    idempotency_key=key,
                    idempotency_record_id=outcome.record_id,
                ),
                idempotency_record_id=outcome.record_id,
                lease_token=outcome.lease_token,
            )
        return reserved_idem

    def reserve_budget(_authorized: _AuthorizedChat) -> None:
        nonlocal budgeted_execution
        budgeted_execution = _execution_budget().reserve(
            user_id=current_user["user_id"], organization_id=org_id,
            prompt=payload.prompt, verify=payload.verify,
        )

    async def prepare_provider(authorized: _AuthorizedChat) -> _ProviderContext:
        provider = await _provider_for_bot(
            authorized.bot, org_id, authorized.provider_permit,
        )
        knowledge_context = await _knowledge_context(
            db, org_id, payload.prompt, authorized.knowledge_scope,
        )
        system_prompt = _combined_system_prompt(authorized.bot.system_prompt, knowledge_context)
        messages = await _build_messages(
            db, authorized.conversation.id, payload.prompt, system_prompt,
        )
        return _ProviderContext(provider, messages, system_prompt)

    async def persist_request(authorized: _AuthorizedChat) -> None:
        nonlocal persisted_execution
        if budgeted_execution is None:
            raise PersistenceConflict("budget reservation is missing")
        persisted_execution = await persistence.prepare_exchange(
            execution_id=execution_identity(
                organization_id=org_id, user_id=current_user["user_id"],
                idempotency_key=reserved_idem.key,
                idempotency_record_id=reserved_idem.record_id,
            ),
            request_id=getattr(request.state, "request_id", "unknown"),
            conversation_id=authorized.conversation.id,
            organization_id=org_id,
            user_id=current_user["user_id"],
            bot_id=authorized.bot.id,
            bot_organization_id=authorized.bot.organization_id,
            provider=authorized.bot.provider,
            model=authorized.bot.model,
            prompt=payload.prompt,
            idempotency_record_id=reserved_idem.record_id,
            estimated_tokens=budgeted_execution.estimate.total_tokens,
            estimated_cost=budgeted_execution.reservation.total_reserved_cost,
            verification=payload.verify,
            recover=reserved_idem.is_recovery,
            lease_token=reserved_idem.lease_token,
            max_attempts=settings.CHAT_MAX_ATTEMPTS,
            governance_decision_id=authorized.governance_decision_id,
        )

    boundary = ChatExecutionBoundary(
        authorize=authorize,
        reserve_idempotency=reserve_idempotency,
        reserve_budget=reserve_budget,
        prepare_provider=prepare_provider,
        persist_request=persist_request,
    )

    async def fail_preflight(
        status_code: int, failure_code: FailureCode = FailureCode.PROVIDER_FAILURE,
    ) -> None:
        if persisted_execution is not None:
            try:
                await persistence.finalize(
                    execution_id=persisted_execution.execution_id,
                    terminal_status="failed",
                    content="",
                    response_status=status_code,
                    response_reference="failed",
                    lease_token=reserved_idem.lease_token,
                    failure_code=failure_code,
                )
            except (PersistenceConflict, PersistenceUnavailable):
                pass
            return
        if governance_decision_id is not None:
            try:
                await governance_audit.record_result(
                    governance_decision_id,
                    result_status="preflight_failed",
                    response_status=status_code,
                    failure_code=failure_code.value,
                )
            except GovernanceAuditUnavailable as exc:
                raise HTTPException(status_code=503, detail="Governance audit is unavailable.") from exc
        try:
            await _release_preflight_lease(
                db, request, reserved_idem.key, reserved_idem.lease_token, status_code,
            )
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass

    prepared = None
    try:
        prepared = await boundary.prepare()
    except BudgetExceeded as exc:
        await fail_preflight(429, FailureCode.BUDGET_REJECTED)
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Execution budget exceeded.") from exc
    except BudgetUnavailable as exc:
        await fail_preflight(503, FailureCode.DATABASE_FAILURE)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Execution budget unavailable.") from exc
    except RetryLimitExceeded as exc:
        await fail_preflight(409, FailureCode.RETRY_EXHAUSTED)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Execution retry limit was reached.") from exc
    except PersistenceConflict as exc:
        await fail_preflight(409, FailureCode.IDEMPOTENCY_CONFLICT)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Execution recovery was rejected.") from exc
    except PersistenceUnavailable as exc:
        await fail_preflight(503, FailureCode.DATABASE_FAILURE)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Execution persistence is unavailable.") from exc
    except SQLAlchemyError as exc:
        await fail_preflight(503, FailureCode.DATABASE_FAILURE)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Execution database is unavailable.") from exc
    except HTTPException as exc:
        await fail_preflight(exc.status_code)
        raise
    except Exception as exc:
        await fail_preflight(500)
        raise HTTPException(status_code=500, detail="AI provider could not be initialized.") from exc

    if prepared.is_replay:
        if governance_decision_id is not None:
            await governance_audit.record_result(
                governance_decision_id,
                result_status="replayed",
                response_status=200,
            )
        return prepared.cached_response
    authorized = prepared.authorized
    provider_context = prepared.provider_context
    assert authorized is not None and provider_context is not None
    assert persisted_execution is not None
    conversation, bot = authorized.conversation, authorized.bot
    provider = provider_context.provider
    provider_messages = provider_context.messages
    effective_system_prompt = provider_context.system_prompt
    idem_key = prepared.idempotency.key
    lease_token = prepared.idempotency.lease_token
    execution_id = persisted_execution.execution_id
    assistant_message_id = persisted_execution.assistant_message_id

    async def finalize_failure(code: FailureCode, content: str = "") -> bool:
        policy = failure_policy(code)
        return await persistence.finalize(
            execution_id=execution_id,
            terminal_status="cancelled" if code is FailureCode.CLIENT_CANCELLED else "failed",
            content=content,
            response_status=policy.response_status,
            response_reference="failed",
            lease_token=lease_token,
            failure_code=code,
        )

    if not payload.stream:
        heartbeat_task, lease_lost = await _start_lease_heartbeat(db, request, idem_key, lease_token)
        try:
            full_response = await provider_with_timeout(
                provider.complete(
                    model=bot.model, messages=provider_messages,
                    system_prompt=effective_system_prompt,
                ),
                settings.CHAT_PROVIDER_TIMEOUT_SECONDS,
            )
            if lease_lost is not None and lease_lost.is_set():
                raise HTTPException(status_code=409, detail="Idempotency lease was lost during AI processing.")
            verified = False
            verification_status = None
            verification_reason = None
            if payload.verify:
                try:
                    verifier_bot, verifier_permit = await _find_verifier_bot(
                        db, bot, org_id, current_user["authorization"],
                    )
                    verifier = await _provider_for_bot(verifier_bot, org_id, verifier_permit)
                    result = await provider_with_timeout(
                        verify_answer(
                            primary_answer=full_response,
                            original_prompt=payload.prompt,
                            verifier=verifier,
                            model=verifier_bot.model,
                        ),
                        settings.CHAT_PROVIDER_TIMEOUT_SECONDS,
                    )
                except Exception:
                    result = _verification_failure(full_response, "Verifikationskontrollen kunne ikke gennemføres.")
                full_response = result.answer
                verified = result.verified
                verification_status = result.status
                verification_reason = result.reason
            if lease_lost is not None and lease_lost.is_set():
                raise HTTPException(status_code=409, detail="Idempotency lease was lost during AI processing.")
            response_payload = {"role": "assistant", "content": full_response, "ai_marked": True,
                                "verified": verified, "verification_status": verification_status,
                                "verification_reason": verification_reason}
            if not await persistence.finalize(
                execution_id=execution_id,
                terminal_status="completed",
                content=full_response,
                response_status=status.HTTP_200_OK,
                response_reference=json.dumps(response_payload),
                lease_token=lease_token,
            ):
                raise HTTPException(status_code=409, detail="Execution was already finalized.")
            return response_payload
        except asyncio.TimeoutError as exc:
            try:
                await finalize_failure(FailureCode.PROVIDER_TIMEOUT)
            except PersistenceConflict:
                pass
            except PersistenceUnavailable as persistence_exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Execution persistence is unavailable.",
                ) from persistence_exc
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="AI provider timed out.",
            ) from exc
        except asyncio.CancelledError:
            try:
                await finalize_failure(FailureCode.CLIENT_CANCELLED)
            except (PersistenceConflict, PersistenceUnavailable):
                pass
            raise
        except HTTPException:
            try:
                await finalize_failure(FailureCode.IDEMPOTENCY_LOST)
            except (PersistenceConflict, PersistenceUnavailable):
                pass
            raise
        except PersistenceUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Execution persistence is unavailable.",
            ) from exc
        except Exception:
            try:
                await finalize_failure(FailureCode.PROVIDER_FAILURE)
            except PersistenceConflict:
                pass
            except PersistenceUnavailable as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Execution persistence is unavailable.",
                ) from exc
            raise HTTPException(status_code=502, detail="AI provider could not fulfil the request.")
        finally:
            await _stop_lease_heartbeat(heartbeat_task, lease_lost)

    async def event_generator() -> AsyncIterator[str]:
        accumulated = ""
        asst_id = assistant_message_id
        verified = False
        verification_status = None
        verification_reason = None
        pump = None
        verification_task = None
        stream_failure_code = FailureCode.PROVIDER_FAILURE
        heartbeat_task, lease_lost = await _start_lease_heartbeat(db, request, idem_key, lease_token)

        async def apply_terminal(terminal: StreamTerminal, content: str) -> None:
            if terminal is StreamTerminal.COMPLETED:
                response_payload = {
                    "role": "assistant", "content": content, "ai_marked": True,
                    "verified": verified, "verification_status": verification_status,
                    "verification_reason": verification_reason,
                }
                completed = await persistence.finalize(
                    execution_id=execution_id, terminal_status=terminal.value, content=content,
                    response_status=200, response_reference=json.dumps(response_payload),
                    lease_token=lease_token,
                )
                if not completed:
                    raise RuntimeError("execution was already finalized")
                return
            policy = failure_policy(stream_failure_code)
            await persistence.finalize(
                execution_id=execution_id, terminal_status=terminal.value, content=content,
                response_status=policy.response_status, response_reference="failed", lease_token=lease_token,
                failure_code=stream_failure_code,
            )

        finalizer = StreamFinalizer(apply_terminal)
        try:
            if not await persistence.mark_streaming(execution_id):
                raise RuntimeError("execution was already finalized")
            yield f"data: {json.dumps({'type': 'start', 'bot_id': bot.id, 'conversation_id': conversation.id, 'message_id': asst_id})}\n\n"
            stream = provider.stream(model=bot.model, messages=provider_messages,
                                     system_prompt=effective_system_prompt)
            pump = StreamPump(
                stream,
                is_disconnected=request.is_disconnected,
                lease_lost=lease_lost,
                heartbeat_seconds=SSE_HEARTBEAT_SECONDS,
                chunk_timeout_seconds=SSE_CHUNK_TIMEOUT_SECONDS,
            )
            while True:
                event = await pump.next_event()
                if event.kind is StreamEventKind.CHUNK:
                    accumulated += event.content or ""
                    yield f"data: {json.dumps({'type': 'token', 'content': event.content})}\n\n"
                elif event.kind is StreamEventKind.HEARTBEAT:
                    yield ": keep-alive\n\n"
                elif event.kind is StreamEventKind.END:
                    break
                elif event.kind is StreamEventKind.DISCONNECTED:
                    stream_failure_code = FailureCode.CLIENT_CANCELLED
                    raise asyncio.CancelledError()
                elif event.kind is StreamEventKind.LEASE_LOST:
                    stream_failure_code = FailureCode.IDEMPOTENCY_LOST
                    raise RuntimeError("idempotency lease was lost during AI processing")
                elif event.kind is StreamEventKind.TIMEOUT:
                    stream_failure_code = FailureCode.PROVIDER_TIMEOUT
                    raise RuntimeError("provider stream timed out")
            await pump.aclose()
            pump = None

            if payload.verify:
                async def run_verification() -> VerificationResult:
                    try:
                        verifier_bot, verifier_permit = await _find_verifier_bot(
                            db, bot, org_id, current_user["authorization"],
                        )
                        verifier = await _provider_for_bot(verifier_bot, org_id, verifier_permit)
                        return await provider_with_timeout(
                            verify_answer(
                                primary_answer=accumulated,
                                original_prompt=payload.prompt,
                                verifier=verifier,
                                model=verifier_bot.model,
                            ),
                            settings.CHAT_PROVIDER_TIMEOUT_SECONDS,
                        )
                    except Exception:
                        return _verification_failure(
                            accumulated, "Verifikationskontrollen kunne ikke gennemføres.",
                        )

                verification_task = asyncio.create_task(run_verification())
                while not verification_task.done():
                    done, _ = await asyncio.wait(
                        {verification_task}, timeout=SSE_HEARTBEAT_SECONDS,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if done:
                        break
                    if await request.is_disconnected():
                        raise asyncio.CancelledError()
                    if lease_lost is not None and lease_lost.is_set():
                        raise RuntimeError("idempotency lease was lost during verification")
                    yield ": keep-alive\n\n"
                result = await verification_task
                verification_task = None
                accumulated = result.answer
                verified = result.verified
                verification_status = result.status
                verification_reason = result.reason
                yield f"data: {json.dumps({'type': 'verification', 'status': verification_status, 'verified': verified, 'reason': verification_reason})}\n\n"

            if lease_lost is not None and lease_lost.is_set():
                raise RuntimeError("idempotency lease was lost before completion")
            await finalizer.finalize(StreamTerminal.COMPLETED, accumulated)
            yield f"data: {json.dumps({'type': 'done', 'full_content': accumulated, 'verified': verified, 'verification_status': verification_status, 'verification_reason': verification_reason})}\n\n"
        except asyncio.CancelledError:
            stream_failure_code = FailureCode.CLIENT_CANCELLED
            try:
                await finalizer.finalize(StreamTerminal.CANCELLED, accumulated)
            except Exception:
                pass
            raise
        except Exception:
            try:
                await finalizer.finalize(StreamTerminal.FAILED, accumulated)
            except Exception:
                pass
            yield f"data: {json.dumps({'type': 'error', 'detail': _sanitize()})}\n\n"
        finally:
            if verification_task is not None:
                verification_task.cancel()
                await asyncio.gather(verification_task, return_exceptions=True)
            if pump is not None:
                await pump.aclose()
            await _stop_lease_heartbeat(heartbeat_task, lease_lost)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
