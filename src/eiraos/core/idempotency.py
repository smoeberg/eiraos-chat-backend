from fastapi import Request, HTTPException, status
import hashlib

IDEMPOTENCY_STORE = {}

async def enforce_idempotency(request: Request):
    key = request.headers.get("Idempotency-Key")
    if not key:
        return None
    
    body = await request.body()
    body_hash = hashlib.sha256(body).hexdigest()
    
    if key in IDEMPOTENCY_STORE:
        stored = IDEMPOTENCY_STORE[key]
        if stored["hash"] != body_hash:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Idempotency key reused with different payload"
            )
        return stored["response"]
    return None

async def record_idempotency(request: Request, response_data: dict):
    key = request.headers.get("Idempotency-Key")
    if not key:
        return
    body = await request.body()
    body_hash = hashlib.sha256(body).hexdigest()
    IDEMPOTENCY_STORE[key] = {
        "hash": body_hash,
        "response": response_data
    }

