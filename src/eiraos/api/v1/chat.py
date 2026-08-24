from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from eiraos.api.v1.auth import get_current_user, get_current_active_organization, require_permission
from eiraos.core.database import get_db
from eiraos.application.chat_execution import (
    ChatCompletionRequest,
    ChatExecutionService,
    _bot_accessible,
    _verifier_bot_accessible,
    _find_verifier_bot,
    _provider_for_bot,
    _valid_knowledge_scope,
)

router = APIRouter(prefix="/chat", tags=["AI Chat Gateway"])
chat_execution_service = ChatExecutionService()


@router.post("/completions", dependencies=[Depends(require_permission("conversation:create"))])
async def create_chat_completion(
    request: Request,
    payload: ChatCompletionRequest,
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
    db: AsyncSession = Depends(get_db),
):
    # The client cannot supply organization_id because the request schema uses
    # extra="forbid". This trusted dependency context is attached internally.
    object.__setattr__(payload, "organization_id", org_id)
    return await chat_execution_service.execute(
        request=request,
        payload=payload,
        current_user=current_user,
        org_id=org_id,
        db=db,
    )
