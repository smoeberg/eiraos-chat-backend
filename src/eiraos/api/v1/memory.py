import json

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from eiraos.api.v1.auth import get_current_active_organization, require_permission
from eiraos.application.memory import MemoryClass
from eiraos.application.memory_runtime import DurableMemoryStore, MemoryBoundaryError
from eiraos.application.provenance import ProvenanceNotFound, ProvenanceResolver
from eiraos.core.database import get_db


router = APIRouter(prefix="/memory", tags=["Memory"])


class MemoryCreate(BaseModel):
    memory_class: MemoryClass
    scope_kind: str
    content: str = Field(min_length=1, max_length=20_000)
    provenance: dict
    reason: str = Field(min_length=1, max_length=500)
    source_message_id: int | None = None
    source_memory_item_id: str | None = None


def _view(record):
    return {
        "item_id": record.item_id,
        "memory_class": record.memory_class,
        "scope_kind": record.scope_kind,
        "content": record.content,
        "provenance": json.loads(record.provenance_json),
        "reason": record.reason,
        "created_at": str(record.created_at),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_memory(payload: MemoryCreate, current_user: dict = Depends(require_permission("memory:write")), org_id: int = Depends(get_current_active_organization), db: AsyncSession = Depends(get_db)):
    try:
        record = await DurableMemoryStore(db).create(
            organization_id=org_id, actor_user_id=current_user["user_id"],
            actor_role=current_user["role"], memory_class=payload.memory_class,
            scope_kind=payload.scope_kind, content=payload.content,
            provenance=payload.provenance, reason=payload.reason,
            source_message_id=payload.source_message_id,
            source_memory_item_id=payload.source_memory_item_id,
        )
    except PermissionError as exc:
        raise HTTPException(403, detail=str(exc)) from exc
    except MemoryBoundaryError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return _view(record)


@router.get("")
async def list_memory(current_user: dict = Depends(require_permission("memory:read")), org_id: int = Depends(get_current_active_organization), db: AsyncSession = Depends(get_db)):
    return [_view(item) for item in await DurableMemoryStore(db).list(org_id, current_user["user_id"])]


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(item_id: str, current_user: dict = Depends(require_permission("memory:delete")), org_id: int = Depends(get_current_active_organization), db: AsyncSession = Depends(get_db)):
    try:
        deleted = await DurableMemoryStore(db).delete(item_id, org_id, current_user["user_id"], current_user["role"])
    except PermissionError as exc:
        raise HTTPException(403, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(404, detail="Memory item not found")
    return Response(status_code=204)


@router.get("/{item_id}/provenance")
async def get_memory_provenance(item_id: str, current_user: dict = Depends(require_permission("memory:read")), org_id: int = Depends(get_current_active_organization), db: AsyncSession = Depends(get_db)):
    try:
        return await ProvenanceResolver(db).trace(
            item_id=item_id, organization_id=org_id,
            user_id=current_user["user_id"],
        )
    except ProvenanceNotFound as exc:
        raise HTTPException(404, detail="Memory item not found") from exc