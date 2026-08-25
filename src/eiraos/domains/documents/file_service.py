"""Secure file parsing/storage helpers for document ingestion."""
from __future__ import annotations

import os
import multiprocessing
import queue
import uuid
from pathlib import Path
from typing import BinaryIO

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_TEXT_CHARS = 500_000
MAX_PDF_PAGES = 200
PDF_PARSE_TIMEOUT_SECONDS = 10
PDF_MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
PDF_CPU_LIMIT_SECONDS = 5
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
        text = _extract_pdf_isolated(data)
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Document must be UTF-8 text") from exc
    if len(text) > MAX_EXTRACTED_TEXT_CHARS:
        raise ValueError("Document exceeds the extracted text limit")
    text = text.replace("\x00", "").strip()
    if not text:
        raise ValueError("Document contains no extractable text")
    return text


def extract_file_text(path: Path, extension: str) -> str:
    return extract_text(path.read_bytes(), extension)


def _extract_pdf_isolated(data: bytes) -> str:
    context = multiprocessing.get_context("spawn")
    results = context.Queue(maxsize=1)
    process = context.Process(target=_pdf_worker, args=(data, results), daemon=True)
    process.start()
    try:
        outcome, value = results.get(timeout=PDF_PARSE_TIMEOUT_SECONDS)
    except queue.Empty as exc:
        _stop_process(process)
        raise ValueError("PDF parsing exceeded the time limit") from exc
    finally:
        if process.is_alive():
            process.join(timeout=0.2)
    if process.is_alive():
        _stop_process(process)
    if outcome != "ok":
        raise ValueError(value)
    return value


def _stop_process(process) -> None:
    process.terminate()
    process.join(timeout=1)
    if process.is_alive():
        process.kill()
        process.join(timeout=1)


def _pdf_worker(data: bytes, results) -> None:
    try:
        import resource
        from io import BytesIO
        from pypdf import PdfReader

        resource.setrlimit(
            resource.RLIMIT_AS,
            (PDF_MEMORY_LIMIT_BYTES, PDF_MEMORY_LIMIT_BYTES),
        )
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (PDF_CPU_LIMIT_SECONDS, PDF_CPU_LIMIT_SECONDS + 1),
        )
        reader = PdfReader(BytesIO(data), strict=True)
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ValueError("PDF exceeds the page limit")
        parts = []
        total = 0
        for page in reader.pages:
            page_text = page.extract_text() or ""
            total += len(page_text)
            if total > MAX_EXTRACTED_TEXT_CHARS:
                raise ValueError("Document exceeds the extracted text limit")
            parts.append(page_text)
        results.put(("ok", "\n\n".join(parts)))
    except Exception:
        results.put(("error", "Unable to extract PDF text"))


def storage_path(root: Path, organization_id: int, extension: str) -> tuple[Path, str]:
    relative = Path(str(organization_id)) / f"{uuid.uuid4().hex}{extension}"
    root_resolved = root.resolve()
    target = (root_resolved / relative).resolve()
    if root_resolved != target and root_resolved not in target.parents:
        raise ValueError("Invalid storage path")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        pass
    return target, relative.as_posix()


def write_upload(stream: BinaryIO, target: Path) -> int:
    total = 0
    with target.open("xb") as handle:
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
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
