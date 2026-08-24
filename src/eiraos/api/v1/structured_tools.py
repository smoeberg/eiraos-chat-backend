from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field

from eiraos.api.v1.auth import (
    get_current_active_organization,
    get_current_user,
    require_permission,
)
from eiraos.application.providers.openai_adapter import OpenAIProviderAdapter
from eiraos.application.structured.service import StructuredExtractionService
from eiraos.core.config import settings
from eiraos.core.exceptions import EiraOSException
from eiraos.core.ratelimit import limiter
from eiraos.core.secrets import SecretService

router = APIRouter(prefix="/tools", tags=["Structured Tools"])
MAX_EXTRACTION_CHARS = 100_000
require_structured_tool_permission = require_permission("tool:extract_structure")


class StructuredExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=MAX_EXTRACTION_CHARS)


class StructuredExtractionResponse(BaseModel):
    schema_version: str
    data: dict


@router.post(
    "/extract-structure",
    response_model=StructuredExtractionResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_structured_tool_permission)],
)
@limiter.limit("10/minute")
async def extract_structure(
    request: Request,
    payload: StructuredExtractionRequest,
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
):
    """Convert unstructured text into the versioned F1 structured contract."""
    if not settings.OPENAI_API_KEY or settings.OPENAI_API_KEY in {"sk-placeholder", "replace-me", "xxx"}:
        raise EiraOSException(
            title="Structured extraction unavailable",
            detail="The structured extraction provider is not configured on this deployment.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    api_key = SecretService.resolve(
        bot_owner_org_id=None,
        secret_reference=None,
        platform_api_key=settings.OPENAI_API_KEY,
        credential_scope="platform",
        caller_org_id=org_id,
    )
    provider = OpenAIProviderAdapter(api_key=api_key)
    service = StructuredExtractionService(provider)
    return await service.extract(text=payload.text, model=settings.STRUCTURED_EXTRACTION_MODEL)
