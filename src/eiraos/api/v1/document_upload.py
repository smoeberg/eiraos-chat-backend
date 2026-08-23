"""Multipart document upload endpoint with tenant-scoped storage."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from eiraos.api.v1.auth import get_current_user, get_current_active_organization, require_permission
from eiraos.core.config import settings
from eiraos.core.database import get_db
from eiraos.domains.documents.file_service import (
    MAX_UPLOAD_BYTES,
    extract_text,
    safe_extension,
    storage_path,
    validate_upload,
    write_upload,
)
from eiraos.domains.documents.models import Document
from eiraos.workers.client import enqueue_document_ingestion

router = APIRouter(prefix="/documents", tags=["RAG & Documents"])
MAX_SCOPE_CHARS = 120


def _safe_scope(value: str) -> str:
    value = (value or "organization").strip()
    if not value or len(value) > MAX_SCOPE_CHARS:
        raise HTTPException(status_code=422, detail="Invalid knowledge_scope")
    if value in {".", ".."} or any(part in {".", ".."} for part in Path(value).parts):
        raise HTTPException(status_code=422, detail="Invalid knowledge_scope")
    return value


@router.post(
    "/upload",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permission("document:upload"))],
)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    knowledge_scope: str = Form("organization"),
    storage_folder: str = Form(""),
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_active_organization),
    db: AsyncSession = Depends(get_db),
):
    """Store a tenant-owned document and enqueue its text for RAG ingestion.

    `storage_folder` is only a relative subdirectory beneath the configured
    tenant storage root. Absolute paths and traversal are rejected.
    """
    scope = _safe_scope(knowledge_scope)
    folder = Path(storage_folder or "")
    if folder.is_absolute() or any(part in {"", ".", ".."} for part in folder.parts):
        raise HTTPException(status_code=422, detail="Invalid storage_folder")

    filename = file.filename or "document"
    extension = safe_extension(filename)
    try:
        # Stream to a random opaque filename first. We still enforce the hard
        # limit while writing, so Content-Length cannot be trusted for safety.
        root = Path(settings.STORAGE_ROOT).resolve() / str(org_id)
        if folder.parts:
            root = (root / folder).resolve()
            tenant_root = (Path(settings.STORAGE_ROOT).resolve() / str(org_id)).resolve()
            if tenant_root != root and tenant_root not in root.parents:
                raise ValueError("invalid storage folder")
        root.mkdir(parents=True, exist_ok=True)
        target, relative = storage_path(root, org_id=0, extension=extension)
        size = write_upload(file.file, target)
        validate_upload(filename, size)
        data = target.read_bytes()
        text_content = extract_text(data, extension)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()

    doc = Document(
        organization_id=org_id,
        title=filename[:500],
        source=relative,
        mime_type=file.content_type or "application/octet-stream",
        status="queued",
        owner=current_user["user_id"],
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    job_id = await enqueue_document_ingestion(
        document_id=doc.id,
        organization_id=org_id,
        content=text_content,
        knowledge_scope=scope,
    )
    if job_id is None:
        doc.status = "failed"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document queue is unavailable",
        )

    return {
        "status": "queued",
        "document_id": doc.id,
        "job_id": job_id,
        "knowledge_scope": scope,
        "storage_path": relative,
        "size": size,
    }
