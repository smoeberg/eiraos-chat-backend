import asyncio
import json
import time
from collections import deque
from datetime import datetime, timezone
from typing import AsyncIterator, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from eiraos.api.v1.auth import get_current_active_organization, get_current_user, require_permission

router = APIRouter(prefix="/execution", tags=["Development & Execution"])

WorkflowState = Literal["draft", "ready", "running", "blocked", "completed", "failed"]

class DecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]

class ExecutionEvent(BaseModel):
    id: int
    type: str
    organization_id: int
    aggregate_id: str
    state: str
    payload: dict
    occurred_at: str

class EventHub:
    def __init__(self) -> None:
        self._sequence = 0
        self._events: deque[ExecutionEvent] = deque(maxlen=500)
        self._subscribers: dict[int, set[asyncio.Queue[ExecutionEvent]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, organization_id: int, event_type: str, aggregate_id: str, state: str, payload: dict) -> ExecutionEvent:
        async with self._lock:
            self._sequence += 1
            event = ExecutionEvent(id=self._sequence, type=event_type, organization_id=organization_id, aggregate_id=aggregate_id, state=state, payload=payload, occurred_at=datetime.now(timezone.utc).isoformat())
            self._events.append(event)
            for queue in self._subscribers.get(organization_id, set()):
                if queue.full():
                    try: queue.get_nowait()
                    except asyncio.QueueEmpty: pass
                await queue.put(event)
            return event

    async def subscribe(self, organization_id: int) -> asyncio.Queue[ExecutionEvent]:
        queue: asyncio.Queue[ExecutionEvent] = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers.setdefault(organization_id, set()).add(queue)
        return queue

    async def unsubscribe(self, organization_id: int, queue: asyncio.Queue[ExecutionEvent]) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(organization_id)
            if subscribers: subscribers.discard(queue)

    async def replay(self, organization_id: int, after_id: int = 0) -> list[ExecutionEvent]:
        async with self._lock:
            return [e for e in self._events if e.organization_id == organization_id and e.id > after_id]

hub = EventHub()

# Reference implementation until execution persistence is introduced. The API shape
# is deliberately stable so a database-backed repository can replace this store.
_WORKFLOWS = {
    "wf-001": {"id":"wf-001","name":"Kommunepilot release","state":"ready","stage":"Implementation","progress":68,"next":"Advance pipeline","updatedAt":"just now"},
    "wf-002": {"id":"wf-002","name":"RAG ingestion hardening","state":"running","stage":"Validation","progress":84,"next":"Review gate","updatedAt":"just now"},
    "wf-003": {"id":"wf-003","name":"Identity policy rollout","state":"blocked","stage":"Approval","progress":42,"next":"Resolve decision","updatedAt":"just now"},
}
_GATES = [
    {"id":"g-1","name":"Evidence / Veritas","status":"passed","detail":"Evidence chain is complete","required":True},
    {"id":"g-2","name":"Security review","status":"passed","detail":"No blocking findings","required":True},
    {"id":"g-3","name":"Owner approval","status":"pending","detail":"Requires explicit decision","required":True},
    {"id":"g-4","name":"Deployment readiness","status":"pending","detail":"Waiting for pipeline validation","required":False},
]
_DECISIONS = {"d-1":{"id":"d-1","title":"Approve production rollout","status":"open","owner":"Platform owner","age":"now"},"d-2":{"id":"d-2","title":"Accept RAG retrieval threshold","status":"approved","owner":"AI lead","age":"41 min"}}
_PROPOSALS = [{"id":"p-1","title":"Promote validated implementation","rationale":"All mandatory evidence and security gates passed.","impact":"Low risk · reversible","status":"proposed"},{"id":"p-2","title":"Split deployment into two stages","rationale":"Reduce blast radius while the approval gate remains open.","impact":"Medium effort · safer rollout","status":"accepted"}]

def cockpit() -> dict:
    return {"workflows": list(_WORKFLOWS.values()), "gates": list(_GATES), "decisions": list(_DECISIONS.values()), "proposals": list(_PROPOSALS)}

async def _org(current_user: dict = Depends(get_current_user), organization_id: int = Depends(get_current_active_organization)) -> int:
    return organization_id

@router.get("/cockpit")
async def get_cockpit(_org_id: int = Depends(_org)):
    return cockpit()

async def _transition(workflow_id: str, action: str, org_id: int) -> dict:
    workflow = _WORKFLOWS.get(workflow_id)
    if not workflow: raise HTTPException(404, "Workflow not found")
    if action == "start":
        if workflow["state"] not in ("ready", "draft"): raise HTTPException(409, f"Cannot start workflow from state '{workflow['state']}'")
        workflow["state"] = "running"
    else:
        if workflow["state"] != "running" and workflow["state"] != "ready": raise HTTPException(409, f"Cannot advance workflow from state '{workflow['state']}'")
        if workflow["progress"] >= 100: workflow["state"] = "completed"
        else:
            workflow["progress"] = min(100, workflow["progress"] + 16)
            workflow["state"] = "completed" if workflow["progress"] == 100 else "running"
    workflow["updatedAt"] = "just now"
    await hub.publish(org_id, f"workflow.{action}", workflow_id, workflow["state"], dict(workflow))
    return workflow

@router.post("/workflows/{workflow_id}/start")
async def start_pipeline(workflow_id: str, _current_user: dict = Depends(require_permission("execution:start")), org_id: int = Depends(get_current_active_organization)):
    return await _transition(workflow_id, "start", org_id)

@router.post("/workflows/{workflow_id}/advance")
async def advance_pipeline(workflow_id: str, _current_user: dict = Depends(require_permission("execution:advance")), org_id: int = Depends(get_current_active_organization)):
    return await _transition(workflow_id, "advance", org_id)

@router.post("/decisions/{decision_id}")
async def resolve_decision(decision_id: str, body: DecisionRequest, _current_user: dict = Depends(require_permission("execution:decide")), org_id: int = Depends(get_current_active_organization)):
    decision = _DECISIONS.get(decision_id)
    if not decision: raise HTTPException(404, "Decision not found")
    if decision["status"] != "open": raise HTTPException(409, "Decision is already resolved")
    decision["status"] = body.decision
    decision["age"] = "just now"
    await hub.publish(org_id, "decision.resolved", decision_id, body.decision, dict(decision))
    return decision

async def _event_stream(org_id: int, after_id: int) -> AsyncIterator[str]:
    for event in await hub.replay(org_id, after_id):
        yield f"id: {event.id}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n"
    queue = await hub.subscribe(org_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=20)
                yield f"id: {event.id}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n"
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
    finally:
        await hub.unsubscribe(org_id, queue)

@router.get("/events")
async def events(request: Request, after_id: int = 0, org_id: int = Depends(get_current_active_organization)):
    return StreamingResponse(_event_stream(org_id, after_id), media_type="text/event-stream", headers={"Cache-Control":"no-cache","Connection":"keep-alive","X-Accel-Buffering":"no"})

@router.websocket("/ws")
async def websocket_events(websocket: WebSocket):
    # Browser WebSocket cannot reliably carry the Authorization header, so the
    # initial version requires an access token query parameter. Reverse proxies
    # should use TLS; clients must never log the URL.
    await websocket.accept()
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008, reason="Authentication required")
        return
    # Reuse the JWT verifier without introducing a second auth policy.
    from eiraos.api.v1.auth import get_current_user
    from eiraos.api.v1.auth import jwt, TOKEN_ISSUER, TOKEN_AUDIENCE
    from eiraos.core.config import settings
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM], issuer=TOKEN_ISSUER, audience=TOKEN_AUDIENCE, options={"require":["exp","iat","jti","iss","aud","sub","user_id","organization_id","token_version"]})
        org_id = payload.get("organization_id")
        if type(org_id) is not int or org_id <= 0: raise ValueError("invalid organization")
    except Exception:
        await websocket.close(code=1008, reason="Invalid authentication")
        return
    after_id = int(websocket.query_params.get("after_id", "0"))
    for event in await hub.replay(org_id, after_id):
        await websocket.send_text(event.model_dump_json())
    queue = await hub.subscribe(org_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=20)
                await websocket.send_text(event.model_dump_json())
            except asyncio.TimeoutError:
                await websocket.send_json({"type":"heartbeat","ts":time.time()})
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unsubscribe(org_id, queue)
