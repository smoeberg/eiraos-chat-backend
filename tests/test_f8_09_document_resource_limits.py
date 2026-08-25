from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eiraos.main import app
from eiraos.core.config import Settings
from eiraos.domains.documents.file_service import (
    MAX_EXTRACTED_TEXT_CHARS,
    MAX_PDF_PAGES,
    PDF_CPU_LIMIT_SECONDS,
    PDF_MEMORY_LIMIT_BYTES,
    PDF_PARSE_TIMEOUT_SECONDS,
    extract_text,
)


ROOT = Path(__file__).parents[1]


def test_extracted_text_is_bounded_independently_of_upload_bytes():
    with pytest.raises(ValueError, match="extracted text limit"):
        extract_text(b"x" * (MAX_EXTRACTED_TEXT_CHARS + 1), ".txt")


def test_pdf_resource_limits_are_finite_and_bounded():
    assert 1 <= MAX_PDF_PAGES <= 500
    assert 1 <= PDF_CPU_LIMIT_SECONDS <= PDF_PARSE_TIMEOUT_SECONDS <= 30
    assert 64 * 1024 * 1024 <= PDF_MEMORY_LIMIT_BYTES <= 512 * 1024 * 1024


def test_pdf_parser_runs_outside_the_api_process_and_is_terminated_on_timeout():
    source = (ROOT / "src/eiraos/domains/documents/file_service.py").read_text()
    endpoint = (ROOT / "src/eiraos/api/v1/document_upload.py").read_text()
    assert 'multiprocessing.get_context("spawn")' in source
    assert "results.get(timeout=PDF_PARSE_TIMEOUT_SECONDS)" in source
    assert "process.terminate()" in source and "process.kill()" in source
    assert "await asyncio.to_thread(write_upload" in endpoint
    assert "await asyncio.to_thread(extract_file_text" in endpoint


def test_upload_path_is_disk_spooled_and_bounded_separately():
    source = (ROOT / "src/eiraos/core/middleware.py").read_text()
    assert "MAX_UPLOAD_REQUEST_BODY_BYTES" in source
    assert "if is_document_upload:" in source
    assert "tempfile.SpooledTemporaryFile(max_size=1024 * 1024)" in source
    assert "if total > body_limit:" in source
    assert "return await call_next(request)" in source
    settings = Settings()
    assert settings.MAX_REQUEST_BODY_BYTES < settings.MAX_UPLOAD_REQUEST_BODY_BYTES


def test_upload_request_uses_dedicated_cap_before_authentication():
    client = TestClient(app)
    within_upload_cap = client.post(
        "/api/v1/documents/upload",
        files={"file": ("large.txt", b"x" * (3 * 1024 * 1024), "text/plain")},
    )
    assert within_upload_cap.status_code != 413

    over_request_cap = client.post(
        "/api/v1/documents/upload",
        files={"file": ("too-large.txt", b"x" * (12 * 1024 * 1024), "text/plain")},
    )
    assert over_request_cap.status_code == 413
