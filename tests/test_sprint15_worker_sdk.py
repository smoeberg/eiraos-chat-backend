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


@pytest.mark.asyncio
async def test_process_document_ingestion_coroutine():
    result = await tasks.process_document_ingestion(ctx=None, document_id=1, organization_id=1, content="x")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_aggregate_usage_metrics_coroutine():
    result = await tasks.aggregate_ai_usage_metrics(ctx=None)
    assert result["status"] == "aggregated"
