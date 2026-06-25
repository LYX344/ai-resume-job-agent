from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from app.api.dependencies import get_llm_client
from app.main import app
from app.services.llm_client import LLMChatResult, LLMStreamDelta


class FakeLLMClient:
    async def chat(self, **kwargs) -> LLMChatResult:
        return LLMChatResult(
            content="mock answer",
            model=kwargs.get("model") or "mock-model",
            finish_reason="stop",
            usage={"total_tokens": 3},
        )

    async def stream_chat(self, **kwargs) -> AsyncIterator[LLMStreamDelta]:
        yield LLMStreamDelta(type="reasoning", text="思考")
        yield LLMStreamDelta(type="content", text="mock ")
        yield LLMStreamDelta(type="content", text="stream")
        yield LLMStreamDelta(type="finish", text="stop")


def test_chat_route_returns_llm_response() -> None:
    app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient()
    client = TestClient(app)

    response = client.post(
        "/api/v1/chat",
        json={"messages": [{"role": "user", "content": "Hello"}]},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {
        "content": "mock answer",
        "model": "mock-model",
        "finish_reason": "stop",
        "usage": {"total_tokens": 3},
    }


def test_stream_chat_route_returns_sse_chunks() -> None:
    app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient()
    client = TestClient(app)

    response = client.post(
        "/api/v1/chat/stream",
        json={"messages": [{"role": "user", "content": "Hello"}]},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert "id: 0" in response.text
    assert '"type":"reasoning"' in response.text
    assert '"delta":"mock "' in response.text
    assert '"delta":"stream"' in response.text
    assert '"type":"content"' in response.text
    assert '"done": true' in response.text
    assert '"finish_reason": "stop"' in response.text
