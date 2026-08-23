from types import SimpleNamespace

import pytest

from eiraos.api.v1 import documents


class FakeDB:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_queue_failure_marks_document_failed_and_closes_idempotency(monkeypatch):
    db = FakeDB()
    doc = SimpleNamespace(id=42, status="queued")
    calls = []

    async def complete(*args, **kwargs):
        calls.append((args, kwargs))
        return True

    monkeypatch.setattr(documents.idempotency, "complete_idempotency", complete)

    await documents._fail_document_ingest(
        db,
        SimpleNamespace(),
        doc,
        "doc:ingest:key-1",
        "lease-1",
        "example.txt",
    )

    assert doc.status == "failed"
    assert db.commits == 1
    assert len(calls) == 1
    assert calls[0][1]["lease_token"] == "lease-1"
    assert calls[0][0][3] == documents.status.HTTP_503_SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_queue_failure_without_idempotency_still_marks_failed(monkeypatch):
    db = FakeDB()
    doc = SimpleNamespace(id=43, status="queued")

    await documents._fail_document_ingest(
        db,
        SimpleNamespace(),
        doc,
        None,
        None,
        "example.txt",
    )

    assert doc.status == "failed"
    assert db.commits == 1
