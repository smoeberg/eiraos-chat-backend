import pytest
import eiraos.workers.tasks as tasks


def test_worker_module_imports_and_declares_cron():
    # Regression: arq was used without import -> NameError on module import.
    assert callable(tasks.WorkerSettings.functions[0])
    assert tasks.WorkerSettings.cron_jobs


def test_arq_declared_in_pyproject():
    with open("pyproject.toml") as f:
        text = f.read()
    assert "arq" in text


def test_worker_does_real_work_not_fake_sleep():
    import inspect
    src = inspect.getsource(tasks.process_document_ingestion)
    # no fake async-sleep simulation scaffolding
    assert "asyncio.sleep" not in src
    # genuine producer is wired in
    assert "intelligent_chunking" in src


@pytest.mark.asyncio
async def test_process_document_ingestion_document_not_found(monkeypatch):
    from eiraos.domains.documents.rag_service import RAGService

    class FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def execute(self, statement):
            class Result:
                @staticmethod
                def scalar_one_or_none(): return None
            return Result()
        async def commit(self): pass

    monkeypatch.setattr(tasks, "async_session_maker", lambda: FakeSession())
    monkeypatch.setattr(
        RAGService, "intelligent_chunking",
        staticmethod(lambda c, chunk_size=500, overlap=50: ["a", "b"]),
    )
    result = await tasks.process_document_ingestion(ctx=None, document_id=1, organization_id=1, content="x")
    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_aggregate_usage_metrics_honest_skip():
    # No usage table exists -> the cron must not fabricate aggregates.
    result = await tasks.aggregate_ai_usage_metrics(ctx=None)
    assert result["status"] == "skipped"
    assert result["reason"] == "no_usage_table"
