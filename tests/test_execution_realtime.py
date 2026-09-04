import pytest

from eiraos.api.v1.execution import EventHub, _transition


@pytest.mark.asyncio
async def test_start_publishes_event():
    import eiraos.api.v1.execution as execution

    execution._WORKFLOWS["wf-test"] = {
        "id": "wf-test", "name": "Test", "state": "ready", "stage": "Plan",
        "progress": 0, "next": "Start", "updatedAt": "old",
    }
    try:
        result = await _transition("wf-test", "start", 7)
        assert result["state"] == "running"
        events = await execution.hub.replay(7)
        assert events[-1].aggregate_id == "wf-test"
        assert events[-1].type == "workflow.start"
    finally:
        execution._WORKFLOWS.pop("wf-test", None)


@pytest.mark.asyncio
async def test_event_hub_is_tenant_scoped():
    hub = EventHub()
    await hub.publish(1, "test", "a", "running", {"ok": True})
    await hub.publish(2, "test", "b", "running", {"ok": True})

    assert [e.organization_id for e in await hub.replay(1)] == [1]
    assert [e.organization_id for e in await hub.replay(2)] == [2]
