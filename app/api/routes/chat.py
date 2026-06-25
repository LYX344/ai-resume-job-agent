import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_llm_client
from app.models.chat import ChatRequest, ChatResponse, ChatStreamChunk
from app.services.llm_client import (
    LLMChatResult,
    LLMClientError,
    LLMConfigurationError,
    OpenAICompatibleClient,
)

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    llm_client: OpenAICompatibleClient = Depends(get_llm_client),
) -> ChatResponse:
    try:
        result = await llm_client.chat(
            messages=request.messages,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _to_chat_response(result)


@router.post("/chat/stream")
async def stream_chat(
    request: ChatRequest,
    llm_client: OpenAICompatibleClient = Depends(get_llm_client),
) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        event_id = 0
        finish_reason: str | None = None
        try:
            async for delta in llm_client.stream_chat(
                messages=request.messages,
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            ):
                if delta.type == "finish":
                    finish_reason = delta.text
                    continue
                chunk = ChatStreamChunk(type=delta.type, delta=delta.text)
                yield f"id: {event_id}\ndata: {chunk.model_dump_json()}\n\n"
                event_id += 1
            done_payload = json.dumps(
                {"done": True, "finish_reason": finish_reason}, ensure_ascii=False
            )
            yield f"id: {event_id}\ndata: {done_payload}\n\n"
        except LLMConfigurationError as exc:
            yield _error_event(str(exc), status_code=503, event_id=event_id)
        except LLMClientError as exc:
            yield _error_event(str(exc), status_code=502, event_id=event_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _to_chat_response(result: LLMChatResult) -> ChatResponse:
    return ChatResponse(
        content=result.content,
        model=result.model,
        finish_reason=result.finish_reason,
        usage=result.usage,
    )


def _error_event(message: str, *, status_code: int, event_id: int = 0) -> str:
    payload = {"error": {"status_code": status_code, "message": message}}
    return f"id: {event_id}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

