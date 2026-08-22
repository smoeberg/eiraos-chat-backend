from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Optional, AsyncGenerator
from eiraos.application.providers.openai_adapter import OpenAIProviderAdapter

router = APIRouter(prefix="/chat", tags=["Chat & AI"])

class ChatMessageSchema(BaseModel):
    role: str = Field(..., description="user, assistant, or system")
    content: str

class ChatCompletionRequest(BaseModel):
    messages: List[ChatMessageSchema]
    model: str = Field(default="gpt-4o-mini", description="AI model identifier")
    api_key: str = Field(..., description="API key for provider")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2000, ge=1)
    system_prompt: Optional[str] = None
    stream: bool = Field(default=True, description="Enable SSE streaming")

@router.post("/completions")
async def chat_completions(payload: ChatCompletionRequest):
    """
    Asynchronous chat completion endpoint with SSE streaming support.
    Follows AIProvider protocol, allowing seamless provider swapping.
    """
    provider = OpenAIProviderAdapter(api_key=payload.api_key)
    formatted_messages = [{"role": m.role, "content": m.content} for m in payload.messages]

    if payload.stream:
        async def event_generator() -> AsyncGenerator[str, None]:
            try:
                async for chunk in provider.stream_chat_completion(
                    messages=formatted_messages,
                    model=payload.model,
                    temperature=payload.temperature,
                    max_tokens=payload.max_tokens,
                    system_prompt=payload.system_prompt
                ):
                    yield f"data: {chunk}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: [ERROR] {str(e)}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")
    else:
        try:
            result = await provider.generate_chat_completion(
                messages=formatted_messages,
                model=payload.model,
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
                system_prompt=payload.system_prompt
            )
            return {"role": "assistant", "content": result}
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
