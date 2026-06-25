import json

import httpx
import pytest

from app.models.chat import ChatMessage
from app.services.llm_client import (
    LLMProviderError,
    LLMStreamDelta,
    OpenAICompatibleClient,
)


@pytest.mark.anyio
async def test_chat_posts_openai_compatible_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://example.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {
            "model": "test-model",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.2,
            "max_tokens": 64,
        }
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Hi there"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"total_tokens": 4},
            },
        )

    client = OpenAICompatibleClient(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="test-model",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await client.chat(
        messages=[ChatMessage(role="user", content="Hello")],
        temperature=0.2,
        max_tokens=64,
    )

    assert result.content == "Hi there"
    assert result.model == "test-model"
    assert result.finish_reason == "stop"
    assert result.usage == {"total_tokens": 4}


@pytest.mark.anyio
async def test_chat_wraps_provider_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "invalid api key"}},
        )

    client = OpenAICompatibleClient(
        base_url="https://example.test/v1",
        api_key="bad-key",
        model="test-model",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMProviderError, match="invalid api key"):
        await client.chat(messages=[ChatMessage(role="user", content="Hello")])


@pytest.mark.anyio
async def test_chat_posts_tools_and_tool_choice() -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "Calculate a math expression.",
                "parameters": {
                    "type": "object",
                    "properties": {"expression": {"type": "string"}},
                    "required": ["expression"],
                },
            },
        }
    ]
    tool_choice = {
        "type": "function",
        "function": {"name": "calculator"},
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["tools"] == tools
        assert payload["tool_choice"] == tool_choice
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Tool ready"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    client = OpenAICompatibleClient(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="test-model",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await client.chat(
        messages=[ChatMessage(role="user", content="2 + 2")],
        tools=tools,
        tool_choice=tool_choice,
    )

    assert result.content == "Tool ready"
    assert result.tool_calls == []


@pytest.mark.anyio
async def test_chat_posts_raw_tool_messages() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["messages"] == [
            {"role": "user", "content": "2 + 2"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "calculator",
                            "arguments": '{"expression":"2+2"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_123",
                "name": "calculator",
                "content": '{"display_value":"4"}',
            },
        ]
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "结果是 4。"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    client = OpenAICompatibleClient(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="test-model",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await client.chat(
        messages=[
            ChatMessage(role="user", content="2 + 2"),
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "calculator",
                            "arguments": '{"expression":"2+2"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_123",
                "name": "calculator",
                "content": '{"display_value":"4"}',
            },
        ]
    )

    assert result.content == "结果是 4。"


@pytest.mark.anyio
async def test_chat_parses_tool_calls() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_123",
                                    "type": "function",
                                    "function": {
                                        "name": "calculator",
                                        "arguments": '{"expression":"2 + 2"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"total_tokens": 12},
            },
        )

    client = OpenAICompatibleClient(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="test-model",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await client.chat(messages=[ChatMessage(role="user", content="2 + 2")])

    assert result.content == ""
    assert result.finish_reason == "tool_calls"
    assert result.tool_calls[0].id == "call_123"
    assert result.tool_calls[0].type == "function"
    assert result.tool_calls[0].function.name == "calculator"
    assert result.tool_calls[0].function.arguments == '{"expression":"2 + 2"}'
    assert result.usage == {"total_tokens": 12}


@pytest.mark.anyio
async def test_stream_chat_yields_delta_content() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        stream = "\n".join(
            [
                'data: {"choices":[{"delta":{"role":"assistant","content":""}}]}',
                'data: {"choices":[{"delta":{"content":"Hel"}}]}',
                'data: {"choices":[{"delta":{"content":"lo"}}]}',
                "data: [DONE]",
            ]
        )
        return httpx.Response(200, content=stream)

    client = OpenAICompatibleClient(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="test-model",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    chunks = [
        chunk
        async for chunk in client.stream_chat(
            messages=[ChatMessage(role="user", content="Hello")]
        )
    ]

    assert chunks == [
        LLMStreamDelta(type="content", text="Hel"),
        LLMStreamDelta(type="content", text="lo"),
    ]


@pytest.mark.anyio
async def test_stream_chat_distinguishes_reasoning_and_content() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        stream = "\n".join(
            [
                'data: {"choices":[{"delta":{"role":"assistant","content":null,"reasoning_content":"想"}}]}',
                'data: {"choices":[{"delta":{"content":null,"reasoning_content":"一下"}}]}',
                'data: {"choices":[{"delta":{"content":"答案"}}]}',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
                "data: [DONE]",
            ]
        )
        return httpx.Response(200, content=stream)

    client = OpenAICompatibleClient(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="test-model",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    chunks = [
        chunk
        async for chunk in client.stream_chat(
            messages=[ChatMessage(role="user", content="Hello")]
        )
    ]

    assert chunks == [
        LLMStreamDelta(type="reasoning", text="想"),
        LLMStreamDelta(type="reasoning", text="一下"),
        LLMStreamDelta(type="content", text="答案"),
        LLMStreamDelta(type="finish", text="stop"),
    ]
