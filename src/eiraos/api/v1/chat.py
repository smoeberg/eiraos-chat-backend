import asyncio

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from eiraos.api.v1.auth import get_current_user, get_current_active_organization, require_permission
from eiraos.core.database import get_db
from eiraos.core import idempotency

SSE_HEARTBEAT_SECONDS = 15
SSE_CHUNK_TIMEOUT_SECONDS = 30
_CHARS_PER_TOKEN = 4
DEFAULT_HISTORY_TOKEN_BUDGET = 8000
MAX_KNOWLEDGE_SCOPE_CHARS = 120


class ChatCompletionRequest(BaseModel):
    """HTTP request contract kept at the API boundary.

    The execution service owns orchestration; keeping this schema here avoids
    importing the application service while the API router is being imported.
    """

    model_config = ConfigDict(extra="forbid")
    conversation_id: int
    bot_id: int
    prompt: str = Field(..., min_length=1)
    stream: bool = True
    idempotency_key: str | None = None
    verify: bool = False
    knowledge_scope: str | None = Field(default=None, max_length=MAX_KNOWLEDGE_SCOPE_CHARS)


# Compatibility surface for existing tests/callers. Imports are intentionally
# lazy so the API module cannot participate in an application/API import cycle.
def _sanitize() -> str:
    from eiraos.application.chat_execution import _sanitize as impl
    return impl()


async def _next_chunk(stream, timeout: float):
    from eiraos.application.chat_execution import _next_chunk as impl
    return await impl(stream, timeout)


def _bot_accessible(bot, org_id: int) -> bool:
    from eiraos.application.chat_execution import _bot_accessible as impl
    return impl(bot, org_id)


def _verifier_bot_accessible(bot, org_id: int) -> bool:
    from eiraos.application.chat_execution import _verifier_bot_accessible as impl
    return impl(bot, org_id)


async def _find_verifier_bot(db, primary_bot, org_id):
    from eiraos.application.chat_execution import _find_verifier_bot as impl
    return await impl(db, primary_bot, org_id)


async def _provider_for_bot(bot, org_id):
    from eiraos.application.chat_execution import _provider_for_bot as impl
    return await impl(bot, org_id)


def _valid_knowledge_scope(value):
    from eiraos.application.chat_execution import _valid_knowledge_scope as impl
    return impl(value)


async def _build_messages(
    db,
    conversation_id: int,
    current_prompt: str,
    system_prompt: str | None,
    max_history: int = 40,
    history_token_budget: int = DEFAULT_HISTORY_TOKEN_BUDGET,
):
    from eiraos.application.chat_execution import _build_messages as impl
    return await impl(
        db,
        conversation_id,
        current_prompt,
        system_prompt,
        max_history=max_history,
        history_token_budget=history_token_budget,
    )


async def _lease_heartbeat(db, request, key, lease_token, lost):
    from eiraos.application.chat_execution import _lease_heartbeat as impl
    return await impl(db, request, key, lease_token, lost)


async def _start_lease_heartbeat(db, request, key, lease_token):
    from eiraos.application.chat_execution import _start_lease_heartbeat as impl
    return await impl(db, request, key, lease_token)


async def _stop_lease_heartbeat(task, lost):
    from eiraos.application.chat_execution import _stop_lease_heartbeat as impl
    return await impl(task, lost)


async def _release_preflight_lease(db, request, idem_key, lease_token, status_code):
    from eiraos.application.chat_execution import _release_preflight_lease as impl
    return await impl(db, request, idem_key, lease_token, status_code)


async def _transition_assistant(db, asst_id, conversation_id, bot_id, content, status_value):
    from eiraos.application.chat_execution import _transition_assistant as impl
    return await impl(db, asst_id, conversation_id, bot_id, content, status_value)


chat_execution_service = None


def _get_chat_execution_service():
    global chat_execution_service
    if chat_execution_service is None:
        from eiraos.application.chat_execution import ChatExecutionService
        chat_execution_service = ChatExecutionService()
    return chat_execution_service


router = APIRouter(prefix="/chat", tags=["AI Chat Gateway"])


@router.post("/completions", dependencies=[Depends(require_permission("conversation:create"))])
async def create_chat_completion(
    request: Request,
    payload: ChatCompletionRequest,
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
    db: AsyncSession = Depends(get_db),
):
    object.__setattr__(payload, "organization_id", org_id)
    return await _get_chat_execution_service().execute(
        request=request,
        payload=payload,
        current_user=current_user,
        org_id=org_id,
        db=db,
    )
