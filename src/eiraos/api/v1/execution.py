import asyncio
import time
from datetime import datetime, timezone
from typing import AsyncIterator, Literal

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from eiraos.api.v1.auth import get_current_active_organization, get_current_user
from eiraos.core.database import get_db
from eiraos.domains.execution.models import (
    ExecutionDecision,
    ExecutionEventRecord,
    ExecutionGate,
    ExecutionProposal,
    ExecutionWorkflow,
)

router = APIRouter(prefix="/execution", tags=["Development & Execution"])
WorkflowState = Literal["draft", "ready", "running", "blocked", "completed", "failed"]
STAGES = ("Plan", "Validate", "Approve", "Implement", "Verify", "Complete")

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
        self._subscribers: dict[int, set[asyncio.Queue[ExecutionEvent]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, db: AsyncSession, organization_id: int, event_type: str, aggregate_id: str, state: str, payload: dict) -> ExecutionEvent:
        record = ExecutionEventRecord(
            organization_id=organization_id,
            event_type=event_type,
            aggregate_id=aggregate_id,
            state=state,
            payload=payload,
            occurred_at=datetime.utcnow(),
        )
        db.add(record)
        await db.flush()
        event = ExecutionEvent(
            id=record.id,
            type=record.event_type,
            organization_id=record.organization_id,
            aggregate_id=record.aggregate_id,
            state=record.state,
            payload=record.payload,
            occurred_at=record.occurred_at.replace(tzinfo=timezone.utc).isoformat(),
        )
        async with self._lock:
            for queue in self._subscribers.get(organization_id, set()):
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
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
            if subscribers:
                subscribers.discard(queue)

hub = EventHub()

async def _seed_org(db: AsyncSession, org_id: int) -> None:
    exists = await db.scalar(select(ExecutionWorkflow.id).where(ExecutionWorkflow.organization_id == org_id).limit(1))
    if exists:
        return
    workflows = [
        ("wf-001", "Kommunepilot release", "ready", "Implementation", 68, "Advance pipeline"),
        ("wf-002", "RAG ingestion hardening", "running", "Validation", 84, "Review gate"),
        ("wf-003", "Identity policy rollout", "blocked", "Approval", 42, "Resolve decision"),
    ]
    for workflow_id, name, state, stage, progress, next_action in workflows:
        db.add(ExecutionWorkflow(organization_id=org_id, workflow_id=workflow_id, name=name, state=state, stage=stage, progress=progress, next_action=next_action))
    for gate_id, name, status, detail, required in [
        ("g-1", "Evidence / Veritas", "passed", "Evidence chain is complete", 1),
        ("g-2", "Security review", "passed", "No blocking findings", 1),
        ("g-3", "Owner approval", "pending", "Requires explicit decision", 1),
        ("g-4", "Deployment readiness", "pending", "Waiting for pipeline validation", 0),
    ]:
        db.add(ExecutionGate(organization_id=org_id, gate_id=gate_id, name=name, status=status, detail=detail, required=required))
    for decision_id, title, status, owner, age in [
        ("d-1", "Approve production rollout", "open", "Platform owner", "now"),
        ("d-2", "Accept RAG retrieval threshold", "approved", "AI lead", "41 min"),
    ]:
        db.add(ExecutionDecision(organization_id=org_id, decision_id=decision_id, title=title, status=status, owner=owner, age=age))
    for proposal_id, title, rationale, impact, status in [
        ("p-1", "Promote validated implementation", "All mandatory evidence and security gates passed.", "Low risk · reversible", "proposed"),
        ("p-2", "Split deployment into two stages", "Reduce blast radius while the approval gate remains open.", "Medium effort · safer rollout", "accepted"),
    ]:
        db.add(ExecutionProposal(organization_id=org_id, proposal_id=proposal_id, title=title, rationale=rationale, impact=impact, status=status))
    await db.commit()


def _workflow_dict(w: ExecutionWorkflow) -> dict:
    return {"id": w.workflow_id, "name": w.name, "state": w.state, "stage": w.stage, "progress": w.progress, "next": w.next_action, "updatedAt": w.updated_at.isoformat()}

def _gate_dict(g: ExecutionGate) -> dict:
    return {"id": g.gate_id, "name": g.name, "status": g.status, "detail": g.detail, "required": bool(g.required)}

def _decision_dict(d: ExecutionDecision) -> dict:
    return {"id": d.decision_id, "title": d.title, "status": d.status, "owner": d.owner, "age": d.age}

def _proposal_dict(p: ExecutionProposal) -> dict:
    return {"id": p.proposal_id, "title": p.title, "rationale": p.rationale, "impact": p.impact, "status": p.status}

async def require_execution_role(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role", "").strip().lower() not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Execution control requires owner or admin role")
    return current_user

@router.get("/cockpit")
async def get_cockpit(db: AsyncSession = Depends(get_db), org_id: int = Depends(get_current_active_organization)):
    await _seed_org(db, org_id)
    workflows = (await db.scalars(select(ExecutionWorkflow).where(ExecutionWorkflow.organization_id == org_id).order_by(ExecutionWorkflow.id))).all()
    gates = (await db.scalars(select(ExecutionGate).where(ExecutionGate.organization_id == org_id).order_by(ExecutionGate.id))).all()
    decisions = (await db.scalars(select(ExecutionDecision).where(ExecutionDecision.organization_id == org_id).order_by(ExecutionDecision.id))).all()
    proposals = (await db.scalars(select(ExecutionProposal).where(ExecutionProposal.organization_id == org_id).order_by(ExecutionProposal.id))).all()
    return {"workflows": [_workflow_dict(w) for w in workflows], "gates": [_gate_dict(g) for g in gates], "decisions": [_decision_dict(d) for d in decisions], "proposals": [_proposal_dict(p) for p in proposals]}

async def _transition(workflow_id: str, action: str, org_id: int, db: AsyncSession) -> dict:
    workflow = await db.scalar(select(ExecutionWorkflow).where(ExecutionWorkflow.organization_id == org_id, ExecutionWorkflow.workflow_id == workflow_id).with_for_update())
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    if action == "start":
        if workflow.state not in ("ready", "draft"):
            raise HTTPException(409, f"Cannot start workflow from state '{workflow.state}'")
        workflow.state = "running"
        workflow.stage = "Plan"
        workflow.next_action = "Advance pipeline"
    else:
        if workflow.state not in ("running", "ready"):
            raise HTTPException(409, f"Cannot advance workflow from state '{workflow.state}'")
        required_pending = await db.scalar(select(ExecutionGate.id).where(ExecutionGate.organization_id == org_id, ExecutionGate.required == 1, ExecutionGate.status != "passed").limit(1))
        if required_pending:
            workflow.state = "blocked"
            workflow.next_action = "Resolve required gate"
            workflow.updated_at = datetime.utcnow()
            workflow.version += 1
            payload = _workflow_dict(workflow)
            await hub.publish(db, org_id, "workflow.blocked", workflow_id, workflow.state, payload)
            await db.commit()
            return payload
        workflow.progress = min(100, workflow.progress + 16)
        stage_index = min(len(STAGES) - 1, int((workflow.progress / 100) * (len(STAGES) - 1)))
        workflow.stage = STAGES[stage_index]
        workflow.state = "completed" if workflow.progress == 100 else "running"
        workflow.next_action = "Complete" if workflow.state == "completed" else "Advance pipeline"
    workflow.updated_at = datetime.utcnow()
    workflow.version += 1
    payload = _workflow_dict(workflow)
    await hub.publish(db, org_id, f"workflow.{action}", workflow_id, workflow.state, payload)
    await db.commit()
    return payload

@router.post("/workflows/{workflow_id}/start")
async def start_pipeline(workflow_id: str, _current_user: dict = Depends(require_execution_role), db: AsyncSession = Depends(get_db), org_id: int = Depends(get_current_active_organization)):
    await _seed_org(db, org_id)
    return await _transition(workflow_id, "start", org_id, db)

@router.post("/workflows/{workflow_id}/advance")
async def advance_pipeline(workflow_id: str, _current_user: dict = Depends(require_execution_role), db: AsyncSession = Depends(get_db), org_id: int = Depends(get_current_active_organization)):
    await _seed_org(db, org_id)
    return await _transition(workflow_id, "advance", org_id, db)

@router.post("/decisions/{decision_id}")
async def resolve_decision(decision_id: str, body: DecisionRequest, _current_user: dict = Depends(require_execution_role), db: AsyncSession = Depends(get_db), org_id: int = Depends(get_current_active_organization)):
    await _seed_org(db, org_id)
    decision = await db.scalar(select(ExecutionDecision).where(ExecutionDecision.organization_id == org_id, ExecutionDecision.decision_id == decision_id).with_for_update())
    if not decision:
        raise HTTPException(404, "Decision not found")
    if decision.status != "open":
        raise HTTPException(409, "Decision is already resolved")
    decision.status = body.decision
    decision.age = "just now"
    if decision_id == "d-1":
        gate = await db.scalar(select(ExecutionGate).where(ExecutionGate.organization_id == org_id, ExecutionGate.gate_id == "g-3").with_for_update())
        if gate:
            gate.status = "passed" if body.decision == "approved" else "failed"
            gate.detail = "Owner decision resolved"
            gate.updated_at = datetime.utcnow()
            await hub.publish(db, org_id, "gate.updated", gate.gate_id, gate.status, _gate_dict(gate))
    payload = _decision_dict(decision)
    await hub.publish(db, org_id, "decision.resolved", decision_id, decision.status, payload)
    await db.commit()
    return payload

async def _event_stream(org_id: int, after_id: int) -> AsyncIterator[str]:
    async with __import__("eiraos.core.database", fromlist=["async_session_maker"]).async_session_maker() as db:
        rows = (await db.scalars(select(ExecutionEventRecord).where(ExecutionEventRecord.organization_id == org_id, ExecutionEventRecord.id > after_id).order_by(ExecutionEventRecord.id))).all()
        for row in rows:
            event = ExecutionEvent(id=row.id, type=row.event_type, organization_id=row.organization_id, aggregate_id=row.aggregate_id, state=row.state, payload=row.payload, occurred_at=row.occurred_at.replace(tzinfo=timezone.utc).isoformat())
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
async def events(after_id: int = 0, org_id: int = Depends(get_current_active_organization)):
    return StreamingResponse(_event_stream(org_id, after_id), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})

@router.websocket("/ws")
async def websocket_events(websocket: WebSocket):
    await websocket.accept()
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008, reason="Authentication required")
        return
    from eiraos.api.v1.auth import jwt, TOKEN_ISSUER, TOKEN_AUDIENCE
    from eiraos.core.config import settings
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM], issuer=TOKEN_ISSUER, audience=TOKEN_AUDIENCE, options={"require": ["exp", "iat", "jti", "iss", "aud", "sub", "user_id", "organization_id", "token_version"]})
        org_id = payload.get("organization_id")
        if type(org_id) is not int or org_id <= 0:
            raise ValueError("invalid organization")
    except Exception:
        await websocket.close(code=1008, reason="Invalid authentication")
        return
    after_id = int(websocket.query_params.get("after_id", "0"))
    async with __import__("eiraos.core.database", fromlist=["async_session_maker"]).async_session_maker() as db:
        rows = (await db.scalars(select(ExecutionEventRecord).where(ExecutionEventRecord.organization_id == org_id, ExecutionEventRecord.id > after_id).order_by(ExecutionEventRecord.id))).all()
        for row in rows:
            await websocket.send_text(ExecutionEvent(id=row.id, type=row.event_type, organization_id=row.organization_id, aggregate_id=row.aggregate_id, state=row.state, payload=row.payload, occurred_at=row.occurred_at.replace(tzinfo=timezone.utc).isoformat()).model_dump_json())
    queue = await hub.subscribe(org_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=20)
                await websocket.send_text(event.model_dump_json())
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "heartbeat", "ts": time.time()})
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unsubscribe(org_id, queue)
