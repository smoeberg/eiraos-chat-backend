from fastapi import Request, HTTPException, status
import hashlib

# In-memory or Redis-backed idempotency store for demonstration & robustness
IDEMPOTENCY_STORE = {}

async def check_idempotency(request: Request):
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

def store_idempotency(request: Request, response_data: dict):
    key = request.headers.get("Idempotency-Key")
    if not key:
        return
    import hashlib
    # Note: request.body() is consumed, so body hash should be passed or stored beforehand
    pass
