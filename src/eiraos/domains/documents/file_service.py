"""Secure file parsing/storage helpers for document ingestion."""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import BinaryIO

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf", ".csv", ".json"}


def safe_extension(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def validate_upload(filename: str, size: int) -> str:
    extension = safe_extension(filename)
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported document type")
    if size <= 0 or size > MAX_UPLOAD_BYTES:
        raise ValueError("Document exceeds the permitted size")
    return extension


def extract_text(data: bytes, extension: str) -> str:
    if extension == ".pdf":
        try:
            from pypdf import PdfReader
            from io import BytesIO

            reader = PdfReader(BytesIO(data))
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:
            raise ValueError("Unable to extract PDF text") from exc
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Document must be UTF-8 text") from exc
    text = text.replace("\x00", "").strip()
    if not text:
        raise ValueError("Document contains no extractable text")
    return text


def storage_path(root: Path, organization_id: int, extension: str) -> tuple[Path, str]:
    """Create an opaque, tenant-scoped filename; never use the client filename."""
    relative = Path(str(organization_id)) / f"{uuid.uuid4().hex}{extension}"
    root_resolved = root.resolve()
    target = (root_resolved / relative).resolve()
    if root_resolved != target and root_resolved not in target.parents:
        raise ValueError("Invalid storage path")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target, relative.as_posix()


def write_upload(stream: BinaryIO, target: Path) -> int:
    total = 0
    with target.open("xb") as handle:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                handle.close()
                target.unlink(missing_ok=True)
                raise ValueError("Document exceeds the permitted size")
            handle.write(chunk)
    return total
